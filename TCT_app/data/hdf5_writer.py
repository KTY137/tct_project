"""Incremental HDF5 writer for TCT scan output."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from .save_options import SaveOptions


class HDF5Writer:
    """Write scan results incrementally into ``waveforms.h5``.

    The writer follows ``SCAN_DATA_FORMAT.md`` and creates extensible datasets
    on first use.  It is deliberately tolerant of disabled optional groups so
    scans can keep running in simulation and during partial hardware setup.
    """

    def __init__(
        self,
        run_dir: str | Path,
        save_options: SaveOptions | None = None,
        run_info: dict[str, Any] | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / "waveforms.h5"
        self.save_options = save_options or SaveOptions()
        self.run_info = run_info or {}
        self._file: h5py.File | None = None
        self._n_points = 0
        self._voltage_n = 0
        self._z_focus_n = 0
        self._waveform_len: int | None = None
        self._camera_shape: tuple[int, ...] | None = None

    def open(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._file = h5py.File(self.path, "w")
        self._file.attrs["start_time"] = datetime.now().isoformat(timespec="seconds")
        if self.save_options.run_metadata:
            grp = self._file.require_group("run_info")
            for key, value in self.run_info.items():
                grp.attrs[key] = self._serialise_attr(value)
            grp.attrs["start_time"] = self._file.attrs["start_time"]

    def close(self) -> None:
        if self._file is None:
            return
        self._file.attrs["stop_time"] = datetime.now().isoformat(timespec="seconds")
        self._file.flush()
        self._file.close()
        self._file = None

    def save_point(self, result: Any) -> None:
        f = self._require_open()
        idx = self._n_points
        point = result.point

        points = f.require_group("points")
        self._append_scalar(points, "x_mm", idx, point.x_mm)
        self._append_scalar(points, "y_mm", idx, point.y_mm)
        self._append_scalar(points, "z_mm", idx, point.z_mm)
        if self.save_options.timestamp:
            self._append_scalar(points, "timestamp", idx, result.timestamp)

        if self.save_options.waveforms:
            self._save_waveforms(f, idx, result)

        if self.save_options.analysis:
            analysis = f.require_group("analysis")
            for name in (
                "ref_amplitude_V",
                "ref_charge_pC",
                "dut_amplitude_V",
                "dut_charge_pC",
                "dut_charge_norm",
                "baseline_rms_V",
            ):
                self._append_scalar(analysis, name, idx, getattr(result, name, np.nan))
            if getattr(result, "dut_charge_cal", None) is not None:
                self._append_scalar(analysis, "dut_charge_cal", idx, result.dut_charge_cal)
                if getattr(result, "charge_units", None):
                    analysis["dut_charge_cal"].attrs["units"] = result.charge_units
            for attr, name in (
                ("drift_time_s", "drift_time_ns"),
                ("rise_time_s", "rise_time_ns"),
                ("cfd_time_s", "cfd_time_ns"),
                ("onset_time_s", "onset_time_ns"),
            ):
                val = getattr(result, attr, None)
                self._append_scalar(analysis, name, idx, np.nan if val is None else val * 1e9)

        if self.save_options.bias:
            bias = f.require_group("bias")
            self._append_scalar(bias, "voltage_V", idx, _nan_if_none(result.bias_voltage_V))
            self._append_scalar(bias, "current_A", idx, _nan_if_none(result.bias_current_A))

        if self.save_options.slow_control and result.slow_control:
            sc = f.require_group("slow_control")
            for name, value in result.slow_control.items():
                self._append_scalar(sc, str(name), idx, value)

        if self.save_options.camera_frame and result.camera_frame is not None:
            self._save_camera_frame(f, idx, result.camera_frame)

        self._n_points += 1
        f.flush()

    def save_voltage_point(self, voltage_V: float, charge_pC: float, current_A: float) -> None:
        grp = self._require_open().require_group("voltage_scan")
        idx = self._voltage_n
        self._append_scalar(grp, "voltage_V", idx, voltage_V)
        self._append_scalar(grp, "charge_pC", idx, charge_pC)
        self._append_scalar(grp, "current_A", idx, current_A)
        self._voltage_n += 1

    def save_z_focus_point(self, z_mm: float, metric: float) -> None:
        grp = self._require_open().require_group("z_focus")
        idx = self._z_focus_n
        self._append_scalar(grp, "z_mm", idx, z_mm)
        self._append_scalar(grp, "metric", idx, metric)
        self._z_focus_n += 1

    def _save_waveforms(self, f: h5py.File, idx: int, result: Any) -> None:
        grp = f.require_group("waveforms")
        time_axis = _array_or_empty(result.time_axis)
        ref = _array_or_empty(result.ref_waveform)
        dut = _array_or_empty(result.dut_waveform)
        if self._waveform_len is None:
            self._waveform_len = int(len(time_axis))
            if self._waveform_len == 0:
                return
            grp.create_dataset("time_s", data=time_axis.astype("f8"))
        if len(ref) != self._waveform_len or len(dut) != self._waveform_len:
            return
        self._append_array(grp, "ref_ch1", idx, ref.astype("f4"), (self._waveform_len,))
        self._append_array(grp, "dut_ch2", idx, dut.astype("f4"), (self._waveform_len,))

    def _save_camera_frame(self, f: h5py.File, idx: int, frame: Any) -> None:
        arr = np.asarray(frame)
        if arr.ndim < 2:
            return
        grp = f.require_group("camera")
        if self._camera_shape is None:
            self._camera_shape = tuple(arr.shape)
        if tuple(arr.shape) != self._camera_shape:
            return
        self._append_array(grp, "frames", idx, arr, self._camera_shape)

    def _append_scalar(self, group: h5py.Group, name: str, idx: int, value: Any) -> None:
        if name not in group:
            group.create_dataset(
                name,
                shape=(0,),
                maxshape=(None,),
                dtype="f8",
                chunks=(64,),
                compression="gzip",
            )
        ds = group[name]
        ds.resize((idx + 1,))
        ds[idx] = _nan_if_none(value)

    def _append_array(
        self,
        group: h5py.Group,
        name: str,
        idx: int,
        value: np.ndarray,
        item_shape: tuple[int, ...],
    ) -> None:
        if name not in group:
            group.create_dataset(
                name,
                shape=(0, *item_shape),
                maxshape=(None, *item_shape),
                dtype=value.dtype,
                chunks=(1, *item_shape),
                compression="gzip",
            )
        ds = group[name]
        ds.resize((idx + 1, *item_shape))
        ds[idx] = value

    def _require_open(self) -> h5py.File:
        if self._file is None:
            raise RuntimeError("HDF5Writer is not open")
        return self._file

    @staticmethod
    def _serialise_attr(value: Any) -> str | float | int | bool:
        if isinstance(value, (str, int, float, bool)):
            return value
        return json.dumps(value, default=str)


def _array_or_empty(value: Any) -> np.ndarray:
    if value is None:
        return np.asarray([], dtype=float)
    return np.asarray(value)


def _nan_if_none(value: Any) -> float:
    if value is None:
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
