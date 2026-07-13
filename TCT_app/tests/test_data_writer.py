from __future__ import annotations

from dataclasses import dataclass

import h5py
import numpy as np
import pytest

from data.hdf5_writer import HDF5Writer
from data.influx_writer import InfluxWriter
from data.save_options import SaveOptions


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


def _make_result(x_mm: float = 0.0, y_mm: float = 0.0, z_mm: float = 0.0,
                  camera_frame: np.ndarray | None = None) -> _Result:
    """Minimal-boilerplate ``_Result`` builder for the camera-frame tests below.

    Only point coordinates and the camera frame vary; every other field is a
    fixed, valid value irrelevant to camera-group behaviour.
    """
    t = np.linspace(0, 1e-6, 8)
    return _Result(
        point=_Point(x_mm, y_mm, z_mm),
        timestamp=0.0,
        ref_amplitude_V=0.1,
        ref_charge_pC=1.0,
        dut_amplitude_V=0.2,
        dut_charge_pC=2.0,
        dut_charge_norm=2.0,
        baseline_rms_V=0.01,
        drift_time_s=None,
        rise_time_s=None,
        cfd_time_s=None,
        onset_time_s=None,
        camera_frame=camera_frame,
        ref_waveform=np.ones_like(t),
        dut_waveform=np.ones_like(t) * 2,
        time_axis=t,
    )


def test_save_options_forces_mandatory_groups():
    opts = SaveOptions.from_config({"waveforms": False, "positions": False})
    assert opts.waveforms is True
    assert opts.positions is True


def test_hdf5_writer_saves_xy_point(tmp_path):
    t = np.linspace(0, 1e-6, 8)
    result = _Result(
        point=_Point(1.0, 2.0, 3.0),
        timestamp=123.0,
        ref_amplitude_V=0.1,
        ref_charge_pC=1.0,
        dut_amplitude_V=0.2,
        dut_charge_pC=2.0,
        dut_charge_norm=2.0,
        baseline_rms_V=0.01,
        drift_time_s=None,
        rise_time_s=2e-9,
        cfd_time_s=3e-9,
        onset_time_s=1e-9,
        camera_frame=None,
        ref_waveform=np.ones_like(t),
        dut_waveform=np.ones_like(t) * 2,
        time_axis=t,
        bias_voltage_V=-100.0,
        bias_current_A=1e-6,
        slow_control={"temperature_C": 22.0},
    )
    writer = HDF5Writer(tmp_path / "run_00001", save_options=SaveOptions(slow_control=True))
    writer.open()
    writer.save_point(result)
    writer.save_voltage_point(-100.0, 2.0, 1e-6)
    writer.save_z_focus_point(0.1, 5.0)
    writer.close()

    with h5py.File(tmp_path / "run_00001" / "waveforms.h5", "r") as f:
        assert f["points/x_mm"][0] == 1.0
        assert f["waveforms/dut_ch2"].shape == (1, 8)
        assert f["analysis/rise_time_ns"][0] == 2.0
        assert f["bias/voltage_V"][0] == -100.0
        assert f["slow_control/temperature_C"][0] == 22.0
        assert f["voltage_scan/charge_pC"][0] == 2.0
        assert f["z_focus/metric"][0] == 5.0


def test_influx_writer_disabled_is_noop():
    writer = InfluxWriter.from_config({"enabled": False})
    writer.write_readings({"temperature_C": 22.0})
    writer.close()


# =========================================================================== #
# Camera-frame honesty: counted/logged drops, no zero-backfill, frame_point_index
# =========================================================================== #

def test_camera_frame_omitted_counter_counts_all_three_drop_causes(tmp_path, caplog):
    good = np.ones((4, 4), dtype=np.uint16)
    none_frame = None
    bad_ndim = np.ones(4, dtype=np.uint16)          # ndim < 2
    bad_shape = np.ones((3, 3), dtype=np.uint16)     # shape mismatch vs first (4, 4)

    writer = HDF5Writer(tmp_path / "run_00010", save_options=SaveOptions(camera_frame=True))
    writer.open()
    with caplog.at_level("WARNING"):
        writer.save_point(_make_result(x_mm=0.0, camera_frame=good))
        writer.save_point(_make_result(x_mm=1.0, camera_frame=none_frame))
        writer.save_point(_make_result(x_mm=2.0, camera_frame=bad_ndim))
        writer.save_point(_make_result(x_mm=3.0, camera_frame=bad_shape))
    writer.close()

    assert writer._n_frames_omitted == 3
    assert any("None" in r.message or "grab failed" in r.message for r in caplog.records)
    assert any("ndim" in r.message for r in caplog.records)
    assert any("shape" in r.message for r in caplog.records)

    with h5py.File(tmp_path / "run_00010" / "waveforms.h5", "r") as f:
        assert f["camera/frames"].shape == (1, 4, 4)
        assert f["camera"].attrs["n_frames_omitted"] == 3


def test_camera_frame_point_index_maps_correctly_when_a_frame_drops_mid_run(tmp_path):
    good = np.ones((2, 2), dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00011", save_options=SaveOptions(camera_frame=True))
    writer.open()
    writer.save_point(_make_result(x_mm=0.0, camera_frame=good))
    writer.save_point(_make_result(x_mm=1.0, camera_frame=None))   # dropped
    writer.save_point(_make_result(x_mm=2.0, camera_frame=good))
    writer.save_point(_make_result(x_mm=3.0, camera_frame=good))
    writer.close()

    with h5py.File(tmp_path / "run_00011" / "waveforms.h5", "r") as f:
        # No zero-backfill: frames has exactly the 3 real frames, not 4.
        assert f["camera/frames"].shape == (3, 2, 2)
        assert list(f["camera/frame_point_index"][:]) == [0, 2, 3]
        assert f["camera"].attrs["n_frames_omitted"] == 1
        # points/ itself is untouched by the drop — still 4 rows.
        assert f["points/x_mm"].shape == (4,)


def test_camera_n_frames_omitted_attr_present_and_zero_on_clean_run(tmp_path):
    good = np.ones((2, 2), dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00012", save_options=SaveOptions(camera_frame=True))
    writer.open()
    writer.save_point(_make_result(x_mm=0.0, camera_frame=good))
    writer.save_point(_make_result(x_mm=1.0, camera_frame=good))
    writer.close()

    with h5py.File(tmp_path / "run_00012" / "waveforms.h5", "r") as f:
        assert f["camera"].attrs["n_frames_omitted"] == 0
        assert f["camera/frames"].shape == (2, 2, 2)
        assert list(f["camera/frame_point_index"][:]) == [0, 1]


def test_set_camera_calibration_attrs_round_trip(tmp_path):
    affine = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    writer = HDF5Writer(tmp_path / "run_00013", save_options=SaveOptions())
    writer.open()
    writer.set_camera_calibration(px_per_mm=118.5, affine=affine)
    writer.close()

    with h5py.File(tmp_path / "run_00013" / "waveforms.h5", "r") as f:
        assert f["camera"].attrs["px_per_mm"] == pytest.approx(118.5)
        np.testing.assert_allclose(f["camera"].attrs["affine"], affine)
        # n_frames_omitted is written too: the group now exists at close(),
        # and honestly, zero frames were ever attempted on this run.
        assert f["camera"].attrs["n_frames_omitted"] == 0


def test_camera_disabled_run_has_no_camera_group_and_no_attrs(tmp_path):
    good = np.ones((2, 2), dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00014", save_options=SaveOptions(camera_frame=False))
    writer.open()
    writer.save_point(_make_result(x_mm=0.0, camera_frame=good))
    writer.close()

    with h5py.File(tmp_path / "run_00014" / "waveforms.h5", "r") as f:
        assert "camera" not in f


# =========================================================================== #
# save_camera_frame (B2 deviation sign-off): standalone CAPTURE_PHOTO path.
# Reuses B1's _save_camera_frame honesty primitive, but tags the frame with
# the writer's CURRENT point index and never advances _n_points itself.
# =========================================================================== #

def test_save_camera_frame_tags_current_point_index_and_never_advances_points(tmp_path):
    """A standalone frame is tagged with the point row it WILL belong to (the
    writer's current _n_points at call time); save_camera_frame itself never
    advances that counter -- only a real save_point() call occupies a row.
    Also proves an explicit capture persists even though camera_frame defaults
    to off (it does not gate on save_options, per the method's docstring)."""
    frame_a = np.full((3, 3), 10, dtype=np.uint16)
    frame_b = np.full((3, 3), 20, dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00020", save_options=SaveOptions())  # camera_frame off
    writer.open()

    writer.save_camera_frame(frame_a)
    assert writer._n_points == 0, "a standalone frame must never advance _n_points"
    writer.save_point(_make_result(x_mm=0.0))            # occupies points row 0
    writer.save_camera_frame(frame_b)
    writer.save_point(_make_result(x_mm=1.0))            # occupies points row 1
    writer.close()

    with h5py.File(tmp_path / "run_00020" / "waveforms.h5", "r") as f:
        assert f["camera/frames"].shape == (2, 3, 3)
        assert list(f["camera/frame_point_index"][:]) == [0, 1]
        assert f["points/x_mm"].shape == (2,)
        np.testing.assert_array_equal(f["camera/frames"][0], frame_a)
        np.testing.assert_array_equal(f["camera/frames"][1], frame_b)


def test_save_camera_frame_shares_drop_counter_and_index_space_with_save_point(tmp_path, caplog):
    """save_camera_frame() and save_point()'s implicit per-point grab both
    route through the SAME B1 primitive (_save_camera_frame), so interleaving
    them must share ONE n_frames_omitted counter and ONE contiguous
    camera/frames index space -- not two independent tallies that could
    silently disagree with each other."""
    good = np.full((4, 4), 1, dtype=np.uint16)
    bad_ndim = np.ones(4, dtype=np.uint16)  # ndim < 2 -> dropped

    writer = HDF5Writer(tmp_path / "run_00021", save_options=SaveOptions(camera_frame=True))
    writer.open()
    with caplog.at_level("WARNING"):
        writer.save_point(_make_result(x_mm=0.0, camera_frame=good))  # frame 0 -> point 0
        writer.save_camera_frame(good)                                # frame 1 -> point 1 (tag)
        writer.save_camera_frame(bad_ndim)                            # dropped, standalone path
        writer.save_point(_make_result(x_mm=1.0, camera_frame=None))  # dropped, per-point path
        writer.save_camera_frame(good)                                # frame 2 -> point 2 (tag)
    writer.close()

    with h5py.File(tmp_path / "run_00021" / "waveforms.h5", "r") as f:
        assert f["camera/frames"].shape == (3, 4, 4)
        assert list(f["camera/frame_point_index"][:]) == [0, 1, 2]
        assert f["points/x_mm"].shape == (2,)
        # Both drop paths (standalone bad_ndim + per-point None) land in the
        # SAME counter -- this is the crux of the sign-off: one honesty
        # contract, not two.
        assert f["camera"].attrs["n_frames_omitted"] == 2
    assert any("ndim" in r.message for r in caplog.records)
    assert any("None" in r.message or "grab failed" in r.message for r in caplog.records)


# =========================================================================== #
# camera/frame_pos_mm (E6b): per-frame stage position, honest-absence,
# index-aligned with frames/frame_point_index (M-long, never zero-backfilled).
# =========================================================================== #

def test_save_camera_frame_with_pos_mm_writes_aligned_row(tmp_path):
    frame_a = np.full((3, 3), 10, dtype=np.uint16)
    frame_b = np.full((3, 3), 20, dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00030", save_options=SaveOptions())
    writer.open()
    writer.save_camera_frame(frame_a, pos_mm=(1.5, 2.5, 0.1))
    writer.save_camera_frame(frame_b, pos_mm=(3.5, 4.5, 0.2))
    writer.close()

    with h5py.File(tmp_path / "run_00030" / "waveforms.h5", "r") as f:
        pos = f["camera/frame_pos_mm"][:]
        assert pos.shape == (2, 3)
        np.testing.assert_allclose(pos[0], [1.5, 2.5, 0.1])
        np.testing.assert_allclose(pos[1], [3.5, 4.5, 0.2])
        assert list(f["camera/frame_pos_mm"].attrs["columns"]) == ["x_mm", "y_mm", "z_mm"]


def test_save_camera_frame_without_pos_mm_is_honest_nan_never_zero(tmp_path):
    """pos_mm=None (the default) must land as NaN, NOT a fake (0, 0, 0) --
    the same honesty contract as the rest of the camera group."""
    frame = np.full((2, 2), 7, dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00031", save_options=SaveOptions())
    writer.open()
    writer.save_camera_frame(frame)  # pos_mm omitted
    writer.close()

    with h5py.File(tmp_path / "run_00031" / "waveforms.h5", "r") as f:
        row = f["camera/frame_pos_mm"][0]
        assert np.all(np.isnan(row))
        assert not np.any(row == 0.0)  # never mistakable for a real (0,0,0)


def test_camera_frame_pos_mm_mixed_run_known_and_unknown_stay_aligned(tmp_path):
    """A run mixing per-point frames (position always known, from save_point's
    own `point`) with standalone survey frames (position sometimes withheld)
    keeps frame_pos_mm exactly M rows long and aligned with frame_point_index,
    same as frames/frame_point_index themselves."""
    good = np.full((2, 2), 1, dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00032", save_options=SaveOptions(camera_frame=True))
    writer.open()
    writer.save_point(_make_result(x_mm=0.0, y_mm=10.0, z_mm=0.5, camera_frame=good))  # frame 0
    writer.save_camera_frame(good, pos_mm=(1.0, 20.0, 0.6))                             # frame 1
    writer.save_camera_frame(good)                                                      # frame 2, unknown pos
    writer.close()

    with h5py.File(tmp_path / "run_00032" / "waveforms.h5", "r") as f:
        pos = f["camera/frame_pos_mm"][:]
        assert pos.shape == (3, 3)
        # frame 0: per-point path auto-populates from the point it belongs to.
        np.testing.assert_allclose(pos[0], [0.0, 10.0, 0.5])
        # frame 1: explicit standalone pos_mm.
        np.testing.assert_allclose(pos[1], [1.0, 20.0, 0.6])
        # frame 2: withheld -> honest NaN, still a row (M stays 3, aligned).
        assert np.all(np.isnan(pos[2]))
        assert list(f["camera/frame_point_index"][:]) == [0, 1, 1]


def test_camera_frame_pos_mm_short_tuple_pads_missing_axis_with_nan(tmp_path):
    """A caller passing only (x, y) -- e.g. a 2-D-only stage read -- must not
    crash the append; the missing z lands as NaN, not a silent 0.0."""
    frame = np.full((2, 2), 3, dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00033", save_options=SaveOptions())
    writer.open()
    writer.save_camera_frame(frame, pos_mm=(5.0, 6.0))
    writer.close()

    with h5py.File(tmp_path / "run_00033" / "waveforms.h5", "r") as f:
        row = f["camera/frame_pos_mm"][0]
        np.testing.assert_allclose(row[:2], [5.0, 6.0])
        assert np.isnan(row[2])


def test_old_file_without_frame_pos_mm_dataset_still_reads_fine(tmp_path):
    """Backward compatibility: a file written before E6b (no frame_pos_mm
    dataset at all) must not break a reader that only touches the datasets
    that already existed -- frame_pos_mm is purely additive."""
    good = np.full((2, 2), 1, dtype=np.uint16)

    writer = HDF5Writer(tmp_path / "run_00034", save_options=SaveOptions(camera_frame=True))
    writer.open()
    writer.save_point(_make_result(x_mm=0.0, camera_frame=good))
    writer.close()

    # Simulate a pre-E6b file by deleting the new dataset after the fact.
    path = tmp_path / "run_00034" / "waveforms.h5"
    with h5py.File(path, "a") as f:
        del f["camera/frame_pos_mm"]

    with h5py.File(path, "r") as f:
        assert "frame_pos_mm" not in f["camera"]
        # Everything that existed pre-E6b is untouched and still reads fine.
        assert f["camera/frames"].shape == (1, 2, 2)
        assert list(f["camera/frame_point_index"][:]) == [0]
        assert f["camera"].attrs["n_frames_omitted"] == 0
