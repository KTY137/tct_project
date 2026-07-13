"""gui/analysis_panel.py Survey (mosaic) mode — E6b part 2.

Covers the position-source ladder (camera/frame_pos_mm preferred, older-file
safety['survey'] geometry fallback, honest EmptyState when neither exists),
the NaN-position gap contract, the affine/calibration notice, and the E4
diagnostics readout. All fixtures are written through the REAL
``data.hdf5_writer.HDF5Writer`` (never hand-built HDF5), matching the house
test idiom in ``tests/test_analysis_panel_load_run.py``.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import h5py
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from controller.survey_plan import plan_survey
from data.hdf5_writer import HDF5Writer
from data.save_options import SaveOptions
from gui.analysis_panel import AnalysisPanel, _affine_from_stored


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _frame(value: float = 100.0, shape=(20, 20)) -> np.ndarray:
    return np.full(shape, value, dtype=np.float64)


def _write_calibrated_run(run_dir, *, with_gap: bool = False) -> str:
    """A camera-only run written via ``save_camera_frame`` +
    ``set_camera_calibration`` — a real ``camera/frame_pos_mm`` dataset with
    one deliberately unknown (``pos_mm=None`` -> NaN row) frame when
    *with_gap* is set."""
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    writer.set_camera_calibration(
        px_per_mm=10.0,
        affine=np.array([[10.0, 0.0, 0.0], [0.0, 10.0, 0.0]]),
    )
    positions = [(0.0, 0.0, 0.0), (1.5, 0.0, 0.0), (1.5, 1.5, 0.0), (0.0, 1.5, 0.0)]
    for i, pos in enumerate(positions):
        p = None if (with_gap and i == 2) else pos
        writer.save_camera_frame(_frame(100.0 + i), pos_mm=p)
    writer.close()
    return str(writer.path)


def _write_uncalibrated_run(run_dir) -> str:
    """Camera frames with real positions but NO ``set_camera_calibration``
    call at all — the "no calibration recorded" case."""
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    for pos in [(0.0, 0.0, 0.0), (1.5, 0.0, 0.0)]:
        writer.save_camera_frame(_frame(), pos_mm=pos)
    writer.close()
    return str(writer.path)


def _write_old_geometry_run(run_dir) -> str:
    """Simulates a file written BEFORE E6b part 1 (``camera/frame_pos_mm``
    did not exist yet): a real survey plan's ``safety['survey']`` geometry
    is stashed into ``run_info/scan_config`` (the shape
    ``controller/scan_controller.py::_build_run_info`` produces for a
    plan-based run — ``{"safety": {"survey": {...}}}``), frames are written
    with no position at all, and the resulting ``camera/frame_pos_mm``
    dataset (E6b part 1 still writes it, NaN-filled) is then deleted to
    faithfully reproduce an actually-older file."""
    plan = plan_survey((3.0, 3.0), (2.2, 2.2), overlap_frac=0.2, origin_mm=(0.0, 0.0))
    geom = plan.safety["survey"]

    writer = HDF5Writer(run_dir, save_options=SaveOptions(run_metadata=True))
    writer.open()
    writer._file["run_info"].attrs["scan_config"] = json.dumps(
        {"safety": {"survey": geom}}
    )
    for _ in range(4):   # matches plan_grid's 2x2 tile count for this geometry
        writer.save_camera_frame(_frame(), pos_mm=None)
    writer.close()

    with h5py.File(writer.path, "a") as f:
        del f["camera"]["frame_pos_mm"]
    return str(writer.path)


def _write_no_camera_run(run_dir) -> str:
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    writer.close()
    return str(writer.path)


# --------------------------------------------------------------------------- #
# Page wiring                                                                  #
# --------------------------------------------------------------------------- #

def test_survey_segment_switches_to_survey_page(tmp_path):
    _app()
    h5_path = _write_calibrated_run(tmp_path / "run_00001")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    assert panel._segmented.current_key() == "map"
    panel._segmented.set_current("survey")
    assert panel._modes.currentIndex() == 2
    # Nothing built yet — the empty page, not a stale/previous canvas.
    assert panel._survey_stack.currentIndex() == 0


def test_survey_starts_stale_before_any_load():
    _app()
    panel = AnalysisPanel()
    for tile in (
        panel._tile_survey_placed, panel._tile_survey_omitted_write,
        panel._tile_survey_omitted_pos, panel._tile_survey_clamped,
        panel._tile_survey_offset,
    ):
        assert tile.value() == "—"
        assert tile.is_stale()


# --------------------------------------------------------------------------- #
# Position source ladder                                                       #
# --------------------------------------------------------------------------- #

def test_calibrated_run_mosaic_has_mm_scaled_extent(tmp_path):
    """frame_pos_mm + a real affine -> calibrated placement; the ImageItem's
    transform must resolve to real mm axes (dx/dy = origin_mm, m11/m22 =
    1/px_per_mm) — the "REAL mm axes" requirement."""
    _app()
    h5_path = _write_calibrated_run(tmp_path / "run_00002")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    assert panel._survey_stack.currentIndex() == 1
    assert panel._survey_position_source == "frame_pos_mm"
    tr = panel._survey_image_item.transform()
    assert tr.m11() == pytest.approx(1.0 / 10.0)
    assert tr.m22() == pytest.approx(1.0 / 10.0)
    # 4 tiles at (0,0)/(1.5,0)/(1.5,1.5)/(0,1.5) with a 20px/10px-per-mm=2mm
    # footprint -> canvas origin at (-1.0, -1.0) mm (half a tile before the
    # first tile centre).
    assert tr.dx() == pytest.approx(-1.0)
    assert tr.dy() == pytest.approx(-1.0)
    assert panel._tile_survey_placed.value() == "4"
    assert panel._tile_survey_omitted_pos.value() == "0"


def test_nan_position_frame_is_a_gap_and_counted(tmp_path):
    """A NaN-positioned written frame must be OMITTED from placement (never
    interpolated/guessed at) and surfaced as an honest count, and the
    resulting canvas must contain a real NaN gap."""
    _app()
    h5_path = _write_calibrated_run(tmp_path / "run_00003", with_gap=True)
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    # 3rd frame's position is unknown -> exactly one NaN row.
    pos = panel._camera["frame_pos_mm"]
    assert np.isnan(pos[2]).all()

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    assert panel._survey_stack.currentIndex() == 1
    assert panel._tile_survey_placed.value() == "3"
    assert panel._tile_survey_omitted_pos.value() == "1"
    assert panel._tile_survey_omitted_pos.state() == "warn"
    canvas_img = panel._survey_image_item.image
    assert np.isnan(canvas_img).any(), "a dropped/omitted tile must leave a visible gap"


def test_old_file_without_frame_pos_mm_falls_back_to_survey_geometry(tmp_path):
    """No 'camera/frame_pos_mm' dataset at all (a truly older file) but a
    real safety['survey'] geometry in run_info/scan_config -> tiles are
    reconstructed via analysis.mosaic_stitch.plan_grid, not an EmptyState."""
    _app()
    h5_path = _write_old_geometry_run(tmp_path / "run_00004")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    assert "frame_pos_mm" not in panel._camera
    assert panel._survey_geom is not None
    assert panel._survey_geom["area_mm"] == [3.0, 3.0]

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    assert panel._survey_stack.currentIndex() == 1
    assert panel._survey_position_source == "geometry"
    assert panel._tile_survey_placed.value() == "4"
    assert panel._tile_survey_omitted_pos.value() == "0"


def test_neither_position_source_shows_empty_state_with_reason(tmp_path):
    """Frames exist, but neither camera/frame_pos_mm nor safety['survey']
    geometry does -> a clean, explained EmptyState, never a crash/blank."""
    _app()
    writer_path = _write_old_geometry_run(tmp_path / "run_00005")
    # Strip the geometry too, so NEITHER ladder rung has anything to offer.
    with h5py.File(writer_path, "a") as f:
        del f["run_info"].attrs["scan_config"]

    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(writer_path) is True
    assert panel._survey_geom is None

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    assert panel._survey_stack.currentIndex() == 0
    assert panel._survey_empty._label.text() == "No frame positions available"
    assert "frame_pos_mm" in panel._survey_empty._hint.text()


def test_no_camera_frames_shows_honest_empty_state(tmp_path):
    _app()
    h5_path = _write_no_camera_run(tmp_path / "run_00006")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    assert panel._survey_stack.currentIndex() == 0
    assert panel._survey_empty._label.text() == "No camera frames in this run"


# --------------------------------------------------------------------------- #
# Calibration / affine notice                                                  #
# --------------------------------------------------------------------------- #

def test_calibrated_run_shows_calibrated_notice(tmp_path):
    _app()
    h5_path = _write_calibrated_run(tmp_path / "run_00007")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    assert panel._chip_survey_cal.text() == "Calibrated"
    assert panel._chip_survey_cal.property("state") == "good"
    assert "Calibrated" in panel._lbl_survey_calib.text()


def test_uncalibrated_run_shows_nominal_placement_notice(tmp_path):
    """No set_camera_calibration call at all on this run -> honest
    'uncalibrated - nominal placement' notice (place_tiles(affine=None))."""
    _app()
    h5_path = _write_uncalibrated_run(tmp_path / "run_00008")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)

    assert panel._camera.get("px_per_mm") is None
    assert panel._camera.get("affine_fit") is None

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    # No calibration AND no survey geometry to infer a scale from either ->
    # an honest "cannot place" EmptyState, not a fabricated pixel scale.
    assert panel._survey_stack.currentIndex() == 0
    assert panel._survey_empty._label.text() == "No pixel scale available"


def test_uncalibrated_run_with_survey_geometry_infers_nominal_scale(tmp_path):
    """No camera calibration recorded, but this IS a survey run (geometry
    ladder rung) -> place_tiles(affine=None) with a px/mm inferred from the
    tile pixel shape vs. the plan's own fov_mm, clearly marked nominal."""
    _app()
    h5_path = _write_old_geometry_run(tmp_path / "run_00009")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    assert panel._camera.get("px_per_mm") is None
    assert panel._camera.get("affine_fit") is None

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    assert panel._survey_stack.currentIndex() == 1
    assert panel._chip_survey_cal.text() == "Uncalibrated"
    assert panel._chip_survey_cal.property("state") == "warn"
    assert "survey FOV geometry" in panel._lbl_survey_calib.text()


# --------------------------------------------------------------------------- #
# E4 diagnostics readout                                                       #
# --------------------------------------------------------------------------- #

def test_diagnostics_readout_reflects_place_tiles_output(tmp_path):
    _app()
    h5_path = _write_calibrated_run(tmp_path / "run_00010")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)

    panel._segmented.set_current("survey")
    panel._chk_survey_refine.setChecked(False)   # place_tiles's own default
    panel._build_survey_mosaic()

    assert panel._tile_survey_clamped.value() == "0"
    assert panel._tile_survey_offset.value() == "0.000 px"
    assert panel._tile_survey_omitted_write.value() == "0"


def test_write_time_omission_surfaced_in_diagnostics(tmp_path):
    """camera group attr n_frames_omitted (a grab failure, distinct from a
    NaN-position drop) must show up in its own tile."""
    _app()
    writer = HDF5Writer(tmp_path / "run_00011", save_options=SaveOptions())
    writer.open()
    writer.set_camera_calibration(px_per_mm=10.0)
    good = _frame()
    writer.save_camera_frame(good, pos_mm=(0.0, 0.0, 0.0))
    writer.save_camera_frame(None, pos_mm=(1.5, 0.0, 0.0))   # grab failure -> dropped at write
    writer.close()

    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(str(writer.path))
    assert panel._camera["n_frames_omitted"] == 1

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    assert panel._tile_survey_omitted_write.value() == "1"
    assert panel._tile_survey_omitted_write.state() == "warn"
    assert panel._tile_survey_placed.value() == "1"


# --------------------------------------------------------------------------- #
# New-run reset                                                                #
# --------------------------------------------------------------------------- #

def test_loading_new_run_resets_previous_mosaic(tmp_path):
    _app()
    h5_a = _write_calibrated_run(tmp_path / "run_00012a")
    h5_b = _write_no_camera_run(tmp_path / "run_00012b")
    panel = AnalysisPanel(runs_dir=tmp_path)

    panel.load_run(h5_a)
    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()
    assert panel._survey_stack.currentIndex() == 1

    panel.load_run(h5_b)
    assert panel._survey_stack.currentIndex() == 0
    assert panel._survey_empty._label.text() == "No mosaic built"
    for tile in (panel._tile_survey_placed, panel._tile_survey_omitted_pos):
        assert tile.is_stale()


# --------------------------------------------------------------------------- #
# Affine reconstruction helper                                                 #
# --------------------------------------------------------------------------- #

def test_affine_from_stored_round_trip():
    raw = np.array([[10.0, 0.0, 1.0], [0.0, 10.0, -2.0]])
    fit = _affine_from_stored(raw)
    assert fit is not None
    np.testing.assert_allclose(fit.matrix_px_per_mm, [[10.0, 0.0], [0.0, 10.0]])
    np.testing.assert_allclose(fit.offset_px, [1.0, -2.0])
    assert fit.mean_px_per_mm == pytest.approx(10.0)


def test_affine_from_stored_unparseable_shape_returns_none():
    assert _affine_from_stored(np.array([1.0, 2.0, 3.0])) is None
    assert _affine_from_stored(None) is None


# --------------------------------------------------------------------------- #
# Theme                                                                        #
# --------------------------------------------------------------------------- #

def test_survey_theme_switch_smoke(tmp_path):
    from gui.style import apply_theme

    app = _app()
    apply_theme(app, "light")
    h5_path = _write_calibrated_run(tmp_path / "run_00013")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()

    apply_theme(app, "dark")
    panel.refresh_theme("dark")
    assert not panel.grab().isNull()
    apply_theme(app, "light")
    panel.refresh_theme("light")
    assert not panel.grab().isNull()
