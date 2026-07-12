"""gui/analysis_panel.py::AnalysisPanel.load_run — the public programmatic
load seam a future ScanViewer's "Open in Analysis" button will call with
``ScanController.last_run_path`` right after a scan finishes (design review
Q6i).

Follows the existing headless gui test idiom (QT_QPA_PLATFORM=offscreen, no
pytest-qt) used by test_panel_kit_rollout_batch3.py.
"""
from __future__ import annotations

import csv
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import dataclass

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from data.hdf5_writer import HDF5Writer
from data.save_options import SaveOptions
from gui.analysis_panel import AnalysisPanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@dataclass
class _Point:
    x_mm: float
    y_mm: float
    z_mm: float
    index: int = 0


@dataclass
class _Result:
    point: _Point
    timestamp: float
    ref_amplitude_V: float
    ref_charge_pC: float
    dut_amplitude_V: float
    dut_charge_pC: float
    dut_charge_norm: float
    baseline_rms_V: float
    drift_time_s: float | None
    rise_time_s: float | None
    cfd_time_s: float | None
    onset_time_s: float | None
    camera_frame: np.ndarray | None
    ref_waveform: np.ndarray
    dut_waveform: np.ndarray
    time_axis: np.ndarray
    bias_voltage_V: float | None = None
    bias_current_A: float | None = None
    slow_control: dict | None = None
    dut_charge_cal: float | None = None
    charge_units: str | None = None


def _write_tiny_run(run_dir) -> str:
    """Write a minimal 2x2 xy-map run HDF5 (same fixture idiom as
    test_data_writer.py::test_hdf5_writer_saves_xy_point) and return the
    path to the resulting waveforms.h5, i.e. what
    ScanController.last_run_path would point to."""
    t = np.linspace(0, 1e-6, 8)
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    for i, (x, y, q) in enumerate([(0.0, 0.0, 1.0), (0.0, 1.0, 2.0),
                                    (1.0, 0.0, 3.0), (1.0, 1.0, 4.0)]):
        writer.save_point(_Result(
            point=_Point(x, y, 0.0, index=i),
            timestamp=float(i),
            ref_amplitude_V=0.1,
            ref_charge_pC=1.0,
            dut_amplitude_V=0.2,
            dut_charge_pC=q,
            dut_charge_norm=q,
            baseline_rms_V=0.01,
            drift_time_s=None,
            rise_time_s=None,
            cfd_time_s=None,
            onset_time_s=None,
            camera_frame=None,
            ref_waveform=np.ones_like(t),
            dut_waveform=np.ones_like(t) * q,
            time_axis=t,
        ))
    writer.close()
    return str(writer.path)


def test_load_run_valid_file_returns_true_and_populates_state(tmp_path):
    _app()
    h5_path = _write_tiny_run(tmp_path / "run_00001")
    panel = AnalysisPanel()

    ok = panel.load_run(h5_path)

    assert ok is True
    assert panel._run_path == h5_path
    assert "dut_charge_pC" in panel._data
    assert list(panel._data["dut_charge_pC"]) == [1.0, 2.0, 3.0, 4.0]
    assert panel._chip_file.text() == "File loaded"
    assert panel._chip_file.property("state") == "good"


def test_load_run_accepts_pathlib_path(tmp_path):
    _app()
    h5_path = _write_tiny_run(tmp_path / "run_00002")
    panel = AnalysisPanel()

    from pathlib import Path
    ok = panel.load_run(Path(h5_path))

    assert ok is True
    assert panel._run_path == h5_path


def test_load_run_missing_path_returns_false_and_does_not_raise(tmp_path):
    _app()
    panel = AnalysisPanel()

    ok = panel.load_run(str(tmp_path / "does_not_exist.h5"))

    assert ok is False
    assert panel._data == {}
    assert panel._chip_file.text() == "Load error"
    assert panel._chip_file.property("state") == "crit"


def test_load_run_malformed_file_returns_false_and_does_not_raise(tmp_path):
    _app()
    bad_path = tmp_path / "not_hdf5.h5"
    bad_path.write_text("this is not an hdf5 file")
    panel = AnalysisPanel()

    ok = panel.load_run(str(bad_path))

    assert ok is False
    assert panel._chip_file.text() == "Load error"
    assert panel._chip_file.property("state") == "crit"


def test_open_file_routes_through_load_run(tmp_path, monkeypatch):
    """_open_file still works and now has exactly one load path underneath
    it: the file dialog result is handed to load_run()."""
    _app()
    h5_path = _write_tiny_run(tmp_path / "run_00003")
    panel = AnalysisPanel()

    calls = []
    original_load_run = panel.load_run

    def _spy_load_run(path):
        calls.append(path)
        return original_load_run(path)

    monkeypatch.setattr(panel, "load_run", _spy_load_run)
    monkeypatch.setattr(
        "gui.analysis_panel.QFileDialog.getOpenFileName",
        lambda *a, **k: (h5_path, "HDF5 (*.h5 *.hdf5)"),
    )

    panel._open_file()

    assert calls == [h5_path]
    assert panel._run_path == h5_path
    assert "dut_charge_pC" in panel._data


def test_open_file_dialog_cancel_does_not_call_load_run(monkeypatch):
    _app()
    panel = AnalysisPanel()

    calls = []
    monkeypatch.setattr(panel, "load_run", lambda path: calls.append(path) or True)
    monkeypatch.setattr(
        "gui.analysis_panel.QFileDialog.getOpenFileName",
        lambda *a, **k: ("", ""),
    )

    panel._open_file()

    assert calls == []


# --------------------------------------------------------------------------- #
# Cockpit v5 batch A: recent-runs empty state + segmented modes (§7)          #
# --------------------------------------------------------------------------- #

def test_empty_state_lists_recent_runs_newest_first(tmp_path):
    import os

    _app()
    runs = tmp_path / "runs"
    old = _write_tiny_run(runs / "run_00001")
    new = _write_tiny_run(runs / "run_00002")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    os.utime(new, (2_000_000_000, 2_000_000_000))

    panel = AnalysisPanel(runs_dir=runs)
    # Starts on the empty (recent-runs) page.
    assert panel._stack.currentIndex() == 0
    texts = [panel._list_recent.item(i).text()
             for i in range(panel._list_recent.count())]
    assert len(texts) == 2
    assert "run_00002" in texts[0]     # newest first
    assert "run_00001" in texts[1]


def test_empty_runs_dir_shows_honest_hint(tmp_path):
    _app()
    panel = AnalysisPanel(runs_dir=tmp_path / "no_such_dir")
    assert panel._list_recent.count() == 0
    assert "No run files found" in panel._lbl_recent_hint.text()


def test_recent_run_click_loads_and_swaps_to_loaded_page(tmp_path):
    _app()
    runs = tmp_path / "runs"
    _write_tiny_run(runs / "run_00001")
    panel = AnalysisPanel(runs_dir=runs)

    item = panel._list_recent.item(0)
    panel._on_recent_clicked(item)

    assert panel._chip_file.text() == "File loaded"
    assert panel._stack.currentIndex() == 1     # loaded page
    assert "dut_charge_pC" in panel._data


def test_failed_load_stays_on_recent_runs_page(tmp_path):
    _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    ok = panel.load_run(str(tmp_path / "missing.h5"))
    assert ok is False
    assert panel._stack.currentIndex() == 0


def test_segmented_modes_switch_between_map_and_cce(tmp_path):
    _app()
    h5_path = _write_tiny_run(tmp_path / "run_00003")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    assert panel._segmented.current_key() == "map"
    assert panel._modes.currentIndex() == 0
    panel._segmented.set_current("cce")
    assert panel._modes.currentIndex() == 1
    panel._segmented.set_current("map")
    assert panel._modes.currentIndex() == 0


def test_map_mode_uses_shared_scan_map_view_with_data(tmp_path):
    from gui.scan_map_view import ScanMapView

    _app()
    h5_path = _write_tiny_run(tmp_path / "run_00004")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    assert isinstance(panel._map_view, ScanMapView)
    assert panel._map_view.point_count() == 4
    assert panel._map_view.is_showing_map()
    assert "4 arrays" in panel._chip_dataset.text() or panel._chip_dataset.text()
    assert panel._chip_map.text().startswith("Map ")
    # Info line carries range + missing count.
    assert "missing" in panel._lbl_map_info.text()


# --------------------------------------------------------------------------- #
# CCE V_dep marker sign convention (D3-gate finding 2)                        #
# --------------------------------------------------------------------------- #

def test_cce_vdep_line_matches_negative_bias_data_sign(monkeypatch):
    """estimate_depletion_voltage() only ever returns a positive magnitude
    (|V|); _plot_cce must re-apply the sign convention read from the data
    itself so the marker lands on the same side / within the range of a
    negative-bias dataset, instead of guessing positive."""
    _app()
    panel = AnalysisPanel()
    panel._data = {
        "bias_V": np.array([0.0, -20.0, -40.0, -60.0, -80.0, -100.0]),
        "dut_charge_pC": np.array([-0.1, -0.6, -0.95, -0.99, -1.0, -1.0]),
    }

    warned = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        staticmethod(lambda *a, **k: warned.append(a)),
    )

    panel._plot_cce()

    assert warned == []   # no "no bias data" popup
    assert panel._vdep_line.isVisible()
    v_dep = panel._vdep_line.value()
    # Correct side (negative, matching the data's sign) and within range.
    assert v_dep < 0
    assert -100.0 <= v_dep <= 0.0
    assert "V_dep estimate:" in panel._lbl_vdep.text()
    assert "(|V| convention)" in panel._lbl_vdep.text()


def test_cce_vdep_line_positive_bias_stays_positive(monkeypatch):
    _app()
    panel = AnalysisPanel()
    panel._data = {
        "bias_V": np.array([0.0, 20.0, 40.0, 60.0, 80.0, 100.0]),
        "dut_charge_pC": np.array([0.1, 0.6, 0.95, 0.99, 1.0, 1.0]),
    }
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", staticmethod(lambda *a, **k: None))

    panel._plot_cce()

    v_dep = panel._vdep_line.value()
    assert v_dep > 0
    assert 0.0 <= v_dep <= 100.0


# --------------------------------------------------------------------------- #
# Real voltage_scan group (D3-gate finding 3)                                 #
# --------------------------------------------------------------------------- #

def _write_voltage_scan_run(run_dir) -> str:
    """Write a real IV-scan HDF5 via HDF5Writer.save_voltage_point — same
    writer path as test_data_writer.py — with no XY/analysis data at all,
    i.e. exactly what a voltage-scan-only run produces on disk."""
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    for v, q, i in [(0.0, -0.1, 1e-9), (-20.0, -0.6, 2e-9), (-40.0, -0.95, 3e-9),
                    (-60.0, -0.99, 4e-9), (-80.0, -1.0, 5e-9), (-100.0, -1.0, 6e-9)]:
        writer.save_voltage_point(v, q, i)
    writer.close()
    return str(writer.path)


def test_load_run_reads_voltage_scan_group(tmp_path):
    _app()
    h5_path = _write_voltage_scan_run(tmp_path / "run_00006")
    panel = AnalysisPanel()

    assert panel.load_run(h5_path) is True

    assert panel._voltage_scan.get("voltage_V") is not None
    assert list(panel._voltage_scan["charge_pC"]) == pytest.approx(
        [-0.1, -0.6, -0.95, -0.99, -1.0, -1.0])
    # Legacy points/analysis reads untouched (empty for a pure voltage scan).
    assert panel._data == {}


def test_plot_cce_renders_from_real_voltage_scan_group_no_warning(tmp_path, monkeypatch):
    """AnalysisPanel._load_h5 must read the real 'voltage_scan/{voltage_V,
    charge_pC,current_A}' group and _plot_cce must render from it — no
    'no bias data' warning dialog."""
    _app()
    h5_path = _write_voltage_scan_run(tmp_path / "run_00007")
    panel = AnalysisPanel()

    warned = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        staticmethod(lambda *a, **k: warned.append(a)),
    )

    assert panel.load_run(h5_path) is True
    panel._plot_cce()

    assert warned == []
    xdata, ydata = panel._cce_curve_cce.getData()
    assert xdata is not None and len(xdata) == 6
    assert np.allclose(sorted(xdata), [-100.0, -80.0, -60.0, -40.0, -20.0, 0.0])
    assert panel._vdep_line.isVisible()
    assert panel._vdep_line.value() < 0   # negative-bias convention from the data


def test_theme_switch_smoke_both_themes(tmp_path):
    from gui.style import apply_theme

    app = _app()
    apply_theme(app, "light")
    h5_path = _write_tiny_run(tmp_path / "run_00005")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    apply_theme(app, "dark")
    panel.refresh_theme("dark")
    assert not panel.grab().isNull()
    apply_theme(app, "light")
    panel.refresh_theme("light")
    assert not panel.grab().isNull()


# --------------------------------------------------------------------------- #
# 1D map slicer (Kaya request: measurement-vs-axis profile)                   #
# --------------------------------------------------------------------------- #

def _write_grid_run(run_dir, *, xs=(0.0, 1.0, 2.0), ys=(0.0, 1.0, 2.0, 3.0)):
    """A non-square (3 X x 4 Y) run with dut_charge_pC = x*100 + y*10 (a
    deterministic, position-dependent value so a slice's averaging math can
    be checked against a hand-computable expectation) and dut_amplitude_V =
    x + y (a second quantity, for the quantity-switch recompute test)."""
    t = np.linspace(0, 1e-6, 8)
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    i = 0
    for x in xs:
        for y in ys:
            q = x * 100.0 + y * 10.0
            writer.save_point(_Result(
                point=_Point(x, y, 0.0, index=i),
                timestamp=float(i),
                ref_amplitude_V=0.1,
                ref_charge_pC=1.0,
                dut_amplitude_V=x + y,
                dut_charge_pC=q,
                dut_charge_norm=q,
                baseline_rms_V=0.01,
                drift_time_s=None,
                rise_time_s=None,
                cfd_time_s=None,
                onset_time_s=None,
                camera_frame=None,
                ref_waveform=np.ones_like(t),
                dut_waveform=np.ones_like(t) * q,
                time_axis=t,
            ))
            i += 1
    writer.close()
    return str(writer.path)


def test_slice_controls_hidden_until_toggled_on(tmp_path):
    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_01")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    for w in panel._slice_control_widgets:
        assert w.isHidden()
    assert panel._slice_figure.isHidden()
    # pg items (GraphicsObject, not QWidget) — isVisible() is the right
    # check for these; it reflects the item's own flag directly, unlike
    # QWidget.isVisible() which also requires a shown top-level window
    # (this panel is never .show()n in a headless test — see isHidden()
    # above for the QWidget half of this same assertion).
    assert panel._slice_line.isVisible() is False

    panel._btn_slice.setChecked(True)

    for w in panel._slice_control_widgets:
        assert not w.isHidden()
    assert not panel._slice_figure.isHidden()
    assert panel._slice_line.isVisible() is True


def test_slice_profile_matches_slice_grid_at_default_position(tmp_path):
    from analysis.map_slice import slice_grid_at_mm

    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_02")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._combo_qty.setCurrentText("dut_charge_pC")
    panel._btn_slice.setChecked(True)

    result = panel._map_view.grid_result()
    axis_key = panel._slice_seg.current_key()
    position_mm = panel._spin_slice_pos.value()
    width = panel._spin_slice_width.value()
    exp_positions, exp_values = slice_grid_at_mm(
        result.grid, result.x_mm, result.y_mm, axis_key, position_mm, width)

    xdata, ydata = panel._slice_curve.getData()
    assert np.allclose(xdata, exp_positions)
    # Charge is displayed in fC (x1000) on the slicer's own profile plot.
    assert np.allclose(ydata, exp_values * 1000.0)


def test_moving_position_spin_updates_profile_and_line(tmp_path):
    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_03")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._combo_qty.setCurrentText("dut_charge_pC")
    panel._btn_slice.setChecked(True)

    panel._spin_slice_pos.setValue(1.0)   # y = 1.0 mm -> index 1
    assert panel._slice_line.value() == pytest.approx(1.0)
    xdata, ydata = panel._slice_curve.getData()
    # axis="x": profile over x_mm=[0,1,2] at fixed y=1.0 -> x*100+10.
    assert np.allclose(sorted(xdata), [0.0, 1.0, 2.0])
    assert np.allclose(sorted(ydata), sorted([10000.0, 110000.0, 210000.0]))


def test_dragging_cut_line_updates_spin_and_profile(tmp_path):
    """Simulates a drag by calling setValue() on the InfiniteLine directly
    (sigPositionChanged fires the same as a real mouse drag)."""
    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_04")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._combo_qty.setCurrentText("dut_charge_pC")
    panel._btn_slice.setChecked(True)

    panel._slice_line.setValue(3.0)   # y = 3.0 mm -> index 3 (last)
    assert panel._spin_slice_pos.value() == pytest.approx(3.0)
    _, ydata = panel._slice_curve.getData()
    assert np.allclose(sorted(ydata), sorted([30000.0, 130000.0, 230000.0]))


def test_no_feedback_loop_between_spin_and_line(tmp_path):
    """Regression guard: moving the line must not recurse infinitely through
    spin<->line sync. Bounded call count is the observable proxy — an
    infinite loop would hang the test (pytest.ini's 60s per-test timeout is
    the real backstop) rather than raise, so this also asserts a small,
    stable number of _update_slice_profile calls per single move."""
    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_05")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._btn_slice.setChecked(True)

    calls = []
    original = panel._update_slice_profile

    def _spy():
        calls.append(1)
        assert len(calls) < 10, "possible feedback loop"
        return original()

    panel._update_slice_profile = _spy
    # Toggling on recentres the line at the grid midpoint (y=2.0 for the
    # default 4-long ys fixture) — pick values that are genuine changes from
    # that (and from each other), since pyqtgraph/Qt do not re-emit
    # value-changed signals for a no-op setValue() of an already-current
    # value (verified against pyqtgraph 0.14's InfiniteLine.setValue).
    assert panel._spin_slice_pos.value() == pytest.approx(2.0)
    panel._slice_line.setValue(0.0)
    assert 1 <= len(calls) <= 3
    calls.clear()
    panel._spin_slice_pos.setValue(3.0)
    assert 1 <= len(calls) <= 3


def test_axis_toggle_switches_orientation_and_recentres(tmp_path):
    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_06")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._combo_qty.setCurrentText("dut_charge_pC")
    panel._btn_slice.setChecked(True)

    assert panel._slice_line.angle == 0   # axis "x" -> horizontal cut line
    assert panel._slice_band_h.isVisible() is True
    assert panel._slice_band_v.isVisible() is False

    panel._slice_seg.set_current("y")

    assert panel._slice_line.angle == 90   # axis "y" -> vertical cut line
    assert panel._slice_band_h.isVisible() is False
    assert panel._slice_band_v.isVisible() is True
    xdata, ydata = panel._slice_curve.getData()
    assert np.allclose(sorted(xdata), [0.0, 1.0, 2.0, 3.0])   # now walks Y


def test_avg_width_matches_slice_grid_averaging(tmp_path):
    from analysis.map_slice import slice_grid_at_mm

    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_07")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._combo_qty.setCurrentText("dut_charge_pC")
    panel._btn_slice.setChecked(True)
    panel._spin_slice_pos.setValue(1.0)
    panel._spin_slice_width.setValue(1)

    result = panel._map_view.grid_result()
    exp_positions, exp_values = slice_grid_at_mm(
        result.grid, result.x_mm, result.y_mm, "x", 1.0, 1)
    _, ydata = panel._slice_curve.getData()
    assert np.allclose(ydata, exp_values * 1000.0)


def test_nan_gap_in_partial_scan_stays_nan_in_profile(tmp_path):
    """A partially-written run (missing points -> NaN grid cells) must show
    up as NaN in the profile, never dropped or zero-filled."""
    _app()
    run_dir = tmp_path / "run_slice_08"
    t = np.linspace(0, 1e-6, 8)
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    # Only the two diagonal corners of a 2x2 raster sampled -> the other
    # two cells (never visited) are NaN gaps in the reconstructed grid.
    for i, (x, y, q) in enumerate([(0.0, 0.0, 1.0), (1.0, 1.0, 2.0)]):
        writer.save_point(_Result(
            point=_Point(x, y, 0.0, index=i), timestamp=float(i),
            ref_amplitude_V=0.1, ref_charge_pC=1.0, dut_amplitude_V=0.2,
            dut_charge_pC=q, dut_charge_norm=q, baseline_rms_V=0.01,
            drift_time_s=None, rise_time_s=None, cfd_time_s=None, onset_time_s=None,
            camera_frame=None, ref_waveform=np.ones_like(t), dut_waveform=np.ones_like(t) * q,
            time_axis=t,
        ))
    writer.close()

    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(str(writer.path))
    panel._combo_qty.setCurrentText("dut_charge_pC")
    panel._btn_slice.setChecked(True)
    panel._spin_slice_pos.setValue(0.0)   # y=0.0 -> only x=0.0 sampled there

    _, ydata = panel._slice_curve.getData()
    assert np.isnan(ydata).any()
    assert not np.isnan(ydata).all()


def test_quantity_switch_recomputes_profile_without_resetting_toggle(tmp_path):
    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_09")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._combo_qty.setCurrentText("dut_charge_pC")
    panel._btn_slice.setChecked(True)
    assert panel._slice_figure.plot.getAxis("left").labelUnits == "fC"

    panel._combo_qty.setCurrentText("dut_amplitude_V")

    assert panel._slice_active is True
    assert panel._btn_slice.isChecked() is True
    assert panel._slice_figure.plot.getAxis("left").labelUnits == "V"
    _, ydata = panel._slice_curve.getData()
    # dut_amplitude_V = x + y; axis "x" at recentred y -> not the charge values.
    assert not np.allclose(sorted(ydata), sorted([10000.0, 110000.0, 210000.0]))


def test_new_run_load_resets_slicer_off(tmp_path):
    _app()
    h5_first = _write_grid_run(tmp_path / "run_slice_10a")
    h5_second = _write_grid_run(tmp_path / "run_slice_10b", xs=(5.0, 6.0))
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_first)
    panel._btn_slice.setChecked(True)
    panel._spin_slice_width.setValue(2)
    assert panel._slice_active is True

    panel.load_run(h5_second)

    assert panel._slice_active is False
    assert panel._btn_slice.isChecked() is False
    assert panel._spin_slice_width.value() == 0
    assert panel._slice_seg.current_key() == "x"


def test_export_slice_csv_writes_expected_rows_and_default_name(tmp_path, monkeypatch):
    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_11")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._combo_qty.setCurrentText("dut_charge_pC")
    panel._btn_slice.setChecked(True)
    panel._spin_slice_pos.setValue(1.0)

    seen_default_name = []
    out = tmp_path / "exported_slice.csv"

    def _fake_save(*args, **kwargs):
        # QFileDialog.getSaveFileName(self, caption, dir, filter)
        seen_default_name.append(args[2] if len(args) > 2 else kwargs.get("dir", ""))
        return (str(out), "CSV (*.csv)")

    monkeypatch.setattr("gui.analysis_panel.QFileDialog.getSaveFileName", _fake_save)

    panel._export_slice_csv()

    assert "run_slice_11" in seen_default_name[0]
    assert "slice_x_1.0000mm" in seen_default_name[0]
    assert out.exists()
    with open(out, newline="") as fh:
        rows = list(csv.reader(fh))
    # base_label strips the quantity's own native-unit suffix ("_pC") before
    # appending the displayed one ("_fC") — never the doubled-up
    # "dut_charge_pC_fC" (analysis.map_slice.strip_unit_suffix).
    assert rows[0] == ["x_mm", "dut_charge_fC"]
    assert len(rows) == 4   # header + 3 x positions
    values = {float(r[0]): float(r[1]) for r in rows[1:]}
    assert values[0.0] == pytest.approx(10000.0)
    assert values[1.0] == pytest.approx(110000.0)
    assert values[2.0] == pytest.approx(210000.0)


def test_slice_export_button_no_op_when_slice_inactive(tmp_path, monkeypatch):
    """Export must never crash / open a dialog when the slicer is off."""
    _app()
    h5_path = _write_grid_run(tmp_path / "run_slice_12")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)

    called = []
    monkeypatch.setattr(
        "gui.analysis_panel.QFileDialog.getSaveFileName",
        lambda *a, **k: called.append(1) or ("", ""),
    )
    panel._export_slice_csv()
    assert called == []


def test_cce_mode_has_no_slice_controls():
    """The slicer only exists inside map mode's own page — switching to CCE
    mode naturally hides it (a different QStackedWidget page), and CCE mode
    carries none of the slicer's widgets."""
    _app()
    panel = AnalysisPanel()
    panel._segmented.set_current("cce")
    assert panel._modes.currentIndex() == 1
    assert not hasattr(panel, "_btn_slice_on_cce_page")   # sanity: no such attr exists
    # The slice toggle itself lives on the map page, which is simply not shown.
    assert panel._btn_slice.parentWidget() is not panel._modes.widget(1)


def test_freeze_levels_unaffected_by_slicer():
    """Toggling the slicer must not touch ScanMapView's own freeze-levels
    state — the two features are independent."""
    _app()
    panel = AnalysisPanel()
    assert panel._map_view._freeze_levels is False
    panel._btn_slice.setChecked(True)
    assert panel._map_view._freeze_levels is False
    panel._map_view._btn_freeze.setChecked(True)
    assert panel._map_view._freeze_levels is True
    panel._btn_slice.setChecked(False)
    assert panel._map_view._freeze_levels is True


def test_slice_overlay_items_have_no_graphics_effect():
    """Rule 3: no QGraphicsEffect on the hot-path map/plot overlay items."""
    _app()
    panel = AnalysisPanel()
    assert panel._slice_figure.graphicsEffect() is None
    assert panel._slice_figure.plot.graphicsEffect() is None


def test_slice_toggled_on_with_no_data_does_not_crash_and_shows_honest_subtitle():
    """Regression: FigureCard only builds a subtitle QLabel at all when
    constructed with non-empty initial text (gui/panel_kit.py Card /
    section_header) — constructing with an empty string would leave
    set_subtitle() a silent permanent no-op. Also covers toggling the
    slicer on/off, and touching its controls, before any run is loaded."""
    _app()
    panel = AnalysisPanel()

    panel._btn_slice.setChecked(True)
    assert panel._slice_active is True
    assert panel._slice_curve.getData() == (None, None)
    assert panel._slice_figure._subtitle_label is not None
    assert panel._slice_figure._subtitle_label.text() == "no map data"

    # Touching controls with no grid behind them must not raise.
    panel._spin_slice_pos.setValue(5.0)
    panel._spin_slice_width.setValue(3)
    panel._slice_seg.set_current("y")

    panel._btn_slice.setChecked(False)
    assert panel._slice_active is False
