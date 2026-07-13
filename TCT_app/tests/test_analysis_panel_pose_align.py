"""gui/analysis_panel.py Survey mode's sensor-pose alignment UI — E7c.

HARD LAW under test: this UI computes and displays pose numbers; it commands
nothing. "Detect sensor pose" only calls ``vision.sensor_align`` (numbers
in, numbers out); "Align scan grid" only displays/copies a suggested
correction and emits ``AnalysisPanel.grid_alignment_suggested`` — neither
button reaches a controller, a scan plan, or motion.

Real ArUco detection tests need ``cv2`` and use ``pytest.importorskip`` (same
pattern as ``tests/test_sensor_align.py``); the degradation-path tests
deliberately force ``cv2`` unavailable via monkeypatch regardless of whether
it is actually installed here, matching that file's own idiom.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from data.hdf5_writer import HDF5Writer
from data.save_options import SaveOptions
from gui.analysis_panel import AnalysisPanel
from vision import sensor_align


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _blank_canvas(size: int) -> np.ndarray:
    return np.full((size, size), 255, dtype=np.uint8)


def _write_no_camera_run(run_dir) -> str:
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    writer.close()
    return str(writer.path)


def _write_blank_frames_run(run_dir, *, n_frames: int = 2, size: int = 40) -> str:
    """Camera frames with real positions but no fiducial content at all —
    enough to exercise BUTTON GATING (frames loaded) without needing cv2 at
    write time; detection itself is expected to fail honestly (no markers)
    if ever clicked against these frames."""
    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    writer.set_camera_calibration(px_per_mm=10.0)
    for i in range(n_frames):
        writer.save_camera_frame(_blank_canvas(size), pos_mm=(float(i), 0.0, 0.0))
    writer.close()
    return str(writer.path)


# --------------------------------------------------------------------------- #
# Button gating                                                               #
# --------------------------------------------------------------------------- #

def test_pose_button_disabled_before_any_run_loaded():
    _app()
    panel = AnalysisPanel()
    panel._segmented.set_current("survey")
    # cv2 availability is whatever this environment has; either way, no
    # frames are loaded yet, so the button must be disabled.
    assert panel._btn_detect_pose.isEnabled() is False
    assert panel._btn_align_grid.isEnabled() is False


def test_pose_button_disabled_when_run_has_no_camera_frames(tmp_path):
    _app()
    h5_path = _write_no_camera_run(tmp_path / "run_nocam")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True
    assert panel._btn_detect_pose.isEnabled() is False
    assert "camera/frames" in panel._btn_detect_pose.toolTip() or "Load a run" in (
        panel._btn_detect_pose.toolTip())


def test_pose_button_enabled_when_cv2_available_and_frames_loaded(tmp_path):
    pytest.importorskip("cv2")
    _app()
    h5_path = _write_blank_frames_run(tmp_path / "run_frames")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    assert sensor_align.is_available() is True
    assert panel._btn_detect_pose.isEnabled() is True
    assert "commands nothing" in panel._btn_detect_pose.toolTip()


def test_pose_button_disabled_with_install_hint_when_cv2_missing(tmp_path, monkeypatch):
    _app()
    monkeypatch.setitem(sys.modules, "cv2", None)
    h5_path = _write_blank_frames_run(tmp_path / "run_frames2")
    panel = AnalysisPanel(runs_dir=tmp_path)
    assert panel.load_run(h5_path) is True

    assert sensor_align.is_available() is False
    assert panel._btn_detect_pose.isEnabled() is False
    tooltip = panel._btn_detect_pose.toolTip()
    assert "opencv-python-headless" in tooltip.lower() or "install" in tooltip.lower()


def test_pose_gating_refreshes_across_loads(tmp_path, monkeypatch):
    """cv2 missing -> loading a run with frames must NOT enable the button;
    the gating recomputes on every load, it is not cached from
    construction."""
    _app()
    monkeypatch.setitem(sys.modules, "cv2", None)
    h5_path = _write_blank_frames_run(tmp_path / "run_frames3")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    assert panel._btn_detect_pose.isEnabled() is False


# --------------------------------------------------------------------------- #
# Real detection: overlay items created in mm coords                          #
# --------------------------------------------------------------------------- #

cv2 = pytest.importorskip("cv2")  # noqa: E402 -- overlay tests need real cv2


def _stamp_marker(canvas: np.ndarray, marker_id: int, marker_px: int,
                   offset_xy: tuple[int, int]) -> None:
    marker_img = sensor_align.generate_marker_image(marker_id, marker_px)
    ox, oy = offset_xy
    canvas[oy: oy + marker_px, ox: ox + marker_px] = marker_img


def _write_pose_run(
    run_dir, *, marker_id: int = 5, marker_px: int = 100, canvas_size: int = 300,
    ref_offset: tuple[int, int] = (50, 50), cur_offset: tuple[int, int] = (70, 50),
    px_per_mm: float = 10.0,
) -> str:
    """Two frames with the SAME ArUco marker stamped at a known, purely
    axis-aligned pixel shift (no warpAffine needed): frame 0 ("reference")
    has the marker at *ref_offset*, frame 1 ("current", also frames[-1])
    has it shifted by ``cur_offset - ref_offset`` px. Written via the real
    ``HDF5Writer`` (house idiom — see tests/test_analysis_panel_survey.py).
    """
    ref = _blank_canvas(canvas_size)
    _stamp_marker(ref, marker_id, marker_px, ref_offset)
    cur = _blank_canvas(canvas_size)
    _stamp_marker(cur, marker_id, marker_px, cur_offset)

    writer = HDF5Writer(run_dir, save_options=SaveOptions())
    writer.open()
    writer.set_camera_calibration(px_per_mm=px_per_mm)
    writer.save_camera_frame(ref, pos_mm=(0.0, 0.0, 0.0))
    writer.save_camera_frame(cur, pos_mm=(5.0, 0.0, 0.0))
    writer.close()
    return str(writer.path)


def test_detect_pose_populates_tiles_and_chip(tmp_path):
    _app()
    h5_path = _write_pose_run(tmp_path / "run_pose1")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._segmented.set_current("survey")

    assert panel._btn_detect_pose.isEnabled() is True
    panel._on_detect_sensor_pose()

    assert panel._survey_pose is not None
    # Pure +20px X shift, no rotation -> theta near 0.
    assert panel._survey_pose.theta_deg == pytest.approx(0.0, abs=1.0)
    assert panel._tile_pose_theta.value() != "—"
    assert panel._tile_pose_theta.is_stale() is False
    assert panel._tile_pose_baseline.value().endswith("px")
    # +20 px / 10 px_per_mm * 1000 = 2000 um magnitude.
    assert "µm" in panel._tile_pose_translation.value()
    assert panel._chip_pose_precision.text() in ("Meets target", "Below target")
    assert panel._btn_align_grid.isEnabled() is True


def test_detect_pose_creates_mm_scaled_overlay_items(tmp_path):
    _app()
    h5_path = _write_pose_run(tmp_path / "run_pose2")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._segmented.set_current("survey")

    panel._on_detect_sensor_pose()

    # One marker detected in the "current" (last) frame -> one corner-
    # outline curve, plus the rotated-bbox indicator.
    assert len(panel._survey_pose_items) == 1
    assert panel._survey_pose_bbox is not None

    # frame center_mm = (5.0, 0.0) (frame_pos_mm[-1]), px_per_mm=10,
    # canvas 300x300 -> half footprint = 15mm. Marker corners (cur_offset
    # (70,50), marker_px=100) span u in [70,170], v in [50,150] ->
    # x_mm in [5 + (70-150)/10, 5 + (170-150)/10] = [-3.0, 7.0]
    # y_mm in [0 + (50-150)/10, 0 + (150-150)/10] = [-10.0, 0.0]
    # (generous tolerance for sub-pixel corner-refinement jitter).
    curve = panel._survey_pose_items[0]
    xs, ys = curve.getData()
    assert min(xs) == pytest.approx(-3.0, abs=1.0)
    assert max(xs) == pytest.approx(7.0, abs=1.0)
    assert min(ys) == pytest.approx(-10.0, abs=1.0)
    assert max(ys) == pytest.approx(0.0, abs=1.0)

    bbox_xs, bbox_ys = panel._survey_pose_bbox.getData()
    # Bbox is centred on center_mm=(5, 0) with a 30x30mm nominal footprint
    # (half=15mm), near-zero rotation.
    assert min(bbox_xs) == pytest.approx(-10.0, abs=1.0)
    assert max(bbox_xs) == pytest.approx(20.0, abs=1.0)
    assert min(bbox_ys) == pytest.approx(-15.0, abs=1.0)
    assert max(bbox_ys) == pytest.approx(15.0, abs=1.0)


def test_detection_failure_no_markers_is_honest_not_a_crash(tmp_path):
    _app()
    h5_path = _write_blank_frames_run(tmp_path / "run_blank")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._segmented.set_current("survey")

    assert panel._btn_detect_pose.isEnabled() is True
    panel._on_detect_sensor_pose()   # must not raise

    assert panel._survey_pose is None
    assert panel._tile_pose_theta.is_stale() is True
    assert panel._chip_pose_precision.text() == "Detection failed"
    assert panel._btn_align_grid.isEnabled() is False


def test_loading_new_run_resets_pose_state(tmp_path):
    _app()
    h5_a = _write_pose_run(tmp_path / "run_pose_a")
    h5_b = _write_no_camera_run(tmp_path / "run_pose_b")
    panel = AnalysisPanel(runs_dir=tmp_path)

    panel.load_run(h5_a)
    panel._on_detect_sensor_pose()
    assert panel._survey_pose is not None
    assert panel._survey_pose_items

    panel.load_run(h5_b)
    assert panel._survey_pose is None
    assert panel._survey_pose_items == []
    assert panel._survey_pose_bbox is None
    assert panel._tile_pose_theta.is_stale() is True
    assert panel._btn_align_grid.isEnabled() is False


# --------------------------------------------------------------------------- #
# "Align scan grid" — numbers only, no controller, spy                        #
# --------------------------------------------------------------------------- #

def test_analysis_panel_module_never_imports_controller():
    """Static proof "Align scan grid" cannot reach a controller: the whole
    module has no ``controller`` import at all (AnalysisPanel's __init__
    doesn't even accept one — this is a standalone post-scan viewer)."""
    import gui.analysis_panel as ap
    from pathlib import Path

    src = Path(ap.__file__).read_text(encoding="utf-8")
    assert "import controller" not in src
    assert "from controller" not in src


def test_align_scan_grid_emits_numbers_and_no_controller_call(tmp_path):
    """Dynamic spy: connect a plain slot to grid_alignment_suggested and
    assert the emitted payload is a plain numbers dict — no controller-like
    object is ever constructed or referenced by the click path (see the
    static test above for the complementary "cannot even import one"
    proof)."""
    _app()
    h5_path = _write_pose_run(tmp_path / "run_pose_align")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._segmented.set_current("survey")
    panel._on_detect_sensor_pose()
    assert panel._btn_align_grid.isEnabled() is True

    received: list[dict] = []
    panel.grid_alignment_suggested.connect(received.append)

    panel._on_align_scan_grid()

    assert len(received) == 1
    payload = received[0]
    for key in (
        "theta_deg", "dx_mm", "dy_mm", "baseline_px",
        "estimated_precision_deg", "meets_precision_target",
    ):
        assert key in payload
    assert payload["theta_deg"] == pytest.approx(panel._survey_pose.theta_deg)
    # isHidden() (not isVisible()) — the panel itself is never .show()n in
    # this headless test, so isVisible() would read False regardless of
    # setVisible(True); isHidden() reflects the widget's own explicit
    # visibility flag independent of an unshown ancestor chain.
    assert panel._lbl_align_grid_result.isHidden() is False
    assert "theta_deg=" in panel._lbl_align_grid_result.text()
    # No new attribute referencing a controller/plan/device got created as
    # a side effect of the click.
    for name in dir(panel):
        assert "controller" not in name.lower()


def test_align_scan_grid_disabled_before_a_detect(tmp_path):
    _app()
    h5_path = _write_pose_run(tmp_path / "run_pose_align2")
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.load_run(h5_path)
    panel._segmented.set_current("survey")

    assert panel._btn_align_grid.isEnabled() is False
    assert "applies nothing" in panel._btn_align_grid.toolTip()
    # Clicking while disabled/ungated is still a defensive no-op, never a
    # crash (e.g. a programmatic call bypassing the disabled QPushButton).
    panel._on_align_scan_grid()
    assert panel._lbl_align_grid_result.isHidden() is True


# --------------------------------------------------------------------------- #
# Degradation: cv2 forcibly unavailable -> Survey page still works otherwise  #
# --------------------------------------------------------------------------- #

def test_survey_page_functional_without_cv2_minus_pose(tmp_path, monkeypatch):
    """cv2 forcibly missing: construction never raises, the mosaic still
    builds normally, and only the pose feature is honestly gated off."""
    _app()
    monkeypatch.setitem(sys.modules, "cv2", None)

    h5_path = _write_blank_frames_run(tmp_path / "run_degraded")
    panel = AnalysisPanel(runs_dir=tmp_path)   # must not raise
    assert panel.load_run(h5_path) is True

    panel._segmented.set_current("survey")
    panel._build_survey_mosaic()   # unrelated to vision/cv2 -- must still work
    assert panel._survey_stack.currentIndex() == 1
    assert panel._tile_survey_placed.value() == "2"

    assert panel._btn_detect_pose.isEnabled() is False
    # Clicking a disabled/gated action programmatically must still be a
    # clean no-op, never a crash.
    panel._on_detect_sensor_pose()
    assert panel._survey_pose is None
