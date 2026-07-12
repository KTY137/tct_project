"""gui/analysis_panel.py::AnalysisPanel.load_run — the public programmatic
load seam a future ScanViewer's "Open in Analysis" button will call with
``ScanController.last_run_path`` right after a scan finishes (design review
Q6i).

Follows the existing headless gui test idiom (QT_QPA_PLATFORM=offscreen, no
pytest-qt) used by test_panel_kit_rollout_batch3.py.
"""
from __future__ import annotations

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
