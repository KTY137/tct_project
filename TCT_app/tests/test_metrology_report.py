"""Tests for ``scripts/metrology_report.py`` (E5).

Covers: file gets written, key numbers land in the HTML, PASS/FAIL verdict
vs. ``tolerance_um`` (including "no tolerance" and the ``cal.affine is None``
FAILED-CALIBRATION path), a tile-diagnostics section, and byte-identical
output across two calls once the timestamp hook is pinned.
"""
from __future__ import annotations

import numpy as np
import pytest

from controller.repeatability import StageCameraCal, fit_stage_camera_affine
from scripts import metrology_report
from scripts.metrology_report import write_report


def _grid_points(xs, ys):
    return np.array([(x, y) for y in ys for x in xs], dtype=float)


# Ground-truth affine used by every "real" cal in this file: mild anisotropic
# scale + rotation + shear, same style as tests/test_affine_selfcal.py.
_M = np.array([[38.0, -5.0], [4.0, 41.0]])
_OFFSET = np.array([80.0, 70.0])


def _clean_cal(tolerance_um: float | None = None) -> StageCameraCal:
    obj = _grid_points((0.0, 0.5, 1.0), (0.0, 0.5, 1.0))
    measured = obj @ _M.T + _OFFSET
    return fit_stage_camera_affine(obj, measured, tolerance_um=tolerance_um)


def _noisy_cal(tolerance_um: float | None = None) -> StageCameraCal:
    obj = _grid_points((0.0, 0.5, 1.0), (0.0, 0.5, 1.0))
    measured = obj @ _M.T + _OFFSET
    measured[0, 0] += 0.5  # inject a known ~0.5 px residual
    return fit_stage_camera_affine(obj, measured, tolerance_um=tolerance_um)


@pytest.fixture(autouse=True)
def _pin_timestamp(monkeypatch):
    monkeypatch.setattr(metrology_report, "_now_iso", lambda: "2026-01-01T00:00:00Z")


# --------------------------------------------------------------------------- #
# Basic write + key numbers                                                   #
# --------------------------------------------------------------------------- #
def test_write_report_creates_file_with_key_numbers(tmp_path):
    cal = _clean_cal()
    out = write_report(cal, tmp_path / "report.html")

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "<html" in text.lower()
    assert f"{cal.affine.rms_um:.3f}" in text
    assert f"{cal.affine.px_per_mm_x:.4f}" in text
    assert f"{cal.affine.px_per_mm_y:.4f}" in text
    assert str(cal.n_points) in text
    assert cal.notes in text  # verbatim, unescaped-content check via substring


def test_no_tolerance_means_no_verdict(tmp_path):
    cal = _clean_cal()
    out = write_report(cal, tmp_path / "report.html", tolerance_um=None)
    text = out.read_text(encoding="utf-8")
    assert "no tolerance set" in text.lower()
    assert "banner pass" not in text
    assert "banner fail" not in text


# --------------------------------------------------------------------------- #
# PASS / FAIL verdict                                                         #
# --------------------------------------------------------------------------- #
def test_pass_case(tmp_path):
    cal = _clean_cal()
    out = write_report(cal, tmp_path / "report.html", tolerance_um=1000.0)
    text = out.read_text(encoding="utf-8")
    assert "PASS" in text
    assert "banner fail" not in text


def test_fail_case(tmp_path):
    cal = _noisy_cal()
    out = write_report(cal, tmp_path / "report.html", tolerance_um=0.001)
    text = out.read_text(encoding="utf-8")
    assert "FAIL" in text
    assert "banner pass" not in text


# --------------------------------------------------------------------------- #
# cal.affine is None                                                          #
# --------------------------------------------------------------------------- #
def test_affine_none_renders_failed_calibration_and_notes(tmp_path):
    cal = StageCameraCal(
        affine=None,
        backlash_mm=(0.0, 0.0),
        rms_um=0.0,
        passes=None,
        n_points=0,
        notes="aborted: danger-gate confirmation denied",
    )
    out = write_report(cal, tmp_path / "report.html", tolerance_um=5.0)
    text = out.read_text(encoding="utf-8")
    assert "FAILED CALIBRATION" in text
    assert "aborted: danger-gate confirmation denied" in text
    # No quiver should be attempted with no affine to draw residuals from.
    assert "<svg" not in text


# --------------------------------------------------------------------------- #
# Tile diagnostics section                                                    #
# --------------------------------------------------------------------------- #
def test_tile_diagnostics_section_renders_when_given(tmp_path):
    cal = _clean_cal()
    diag = {
        "applied_offset_px": [(0.1, -0.2), (0.0, 0.0)],
        "n_clamped": 1,
        "mean_abs_offset_px": 0.15,
    }
    out = write_report(cal, tmp_path / "report.html", tile_diagnostics=diag)
    text = out.read_text(encoding="utf-8")
    assert "tile-placement diagnostics" in text.lower()
    assert "1" in text  # n_clamped
    assert "0.1500" in text  # mean_abs_offset_px, 4dp formatting


def test_tile_diagnostics_omitted_when_none(tmp_path):
    cal = _clean_cal()
    out = write_report(cal, tmp_path / "report.html", tile_diagnostics=None)
    text = out.read_text(encoding="utf-8")
    assert "tile-placement diagnostics" not in text.lower()


# --------------------------------------------------------------------------- #
# Determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_deterministic_across_two_calls(tmp_path):
    cal = _clean_cal()
    diag = {"applied_offset_px": [(0.1, -0.2)], "n_clamped": 0, "mean_abs_offset_px": 0.05}

    out1 = write_report(cal, tmp_path / "r1.html", tile_diagnostics=diag, tolerance_um=2.0)
    out2 = write_report(cal, tmp_path / "r2.html", tile_diagnostics=diag, tolerance_um=2.0)

    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_quiver_present_for_real_affine(tmp_path):
    cal = _clean_cal()
    out = write_report(cal, tmp_path / "report.html")
    text = out.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "&micro;m" in text  # scale legend labels both px and um
    assert "px" in text
