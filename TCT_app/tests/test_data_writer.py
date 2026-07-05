from __future__ import annotations

from dataclasses import dataclass

import h5py
import numpy as np

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
