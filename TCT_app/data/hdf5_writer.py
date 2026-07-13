"""Incremental HDF5 writer for TCT scan output."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from .save_options import SaveOptions

logger = logging.getLogger(__name__)


class HDF5Writer:
    """Write scan results incrementally into ``waveforms.h5``.

    The writer follows ``SCAN_DATA_FORMAT.md`` and creates extensible datasets
    on first use.  It is deliberately tolerant of disabled optional groups so
    scans can keep running in simulation and during partial hardware setup.
    """

    #: Legal values for the ``outcome`` root attribute — see :meth:`set_outcome`.
    VALID_OUTCOMES = frozenset({"finished", "aborted", "error"})
    #: Written when :meth:`close` runs without a prior :meth:`set_outcome` call
    #: (crash, killed process, forgotten call site).  Deliberately NOT one of
    #: ``VALID_OUTCOMES`` and never "finished" — an unrecorded outcome must
    #: read as "we don't know what happened", never as quiet success.
    UNKNOWN_OUTCOME = "unknown"

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
        # camera/frames is append-only and indexed by frame count, NOT point
        # index — see _save_camera_frame.  A dropped/omitted frame must never
        # zero-backfill the dataset, so it needs its own counter.
        self._n_frames_written = 0
        self._n_frames_omitted = 0
        # Set only via set_outcome(); left None if the caller never calls it
        # (crash / killed process / a bug), in which case close() writes
        # UNKNOWN_OUTCOME rather than silently defaulting to success.
        self._outcome: str | None = None
        self._abort_reason: str = ""

    def open(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._file = h5py.File(self.path, "w")
        self._file.attrs["start_time"] = datetime.now().isoformat(timespec="seconds")
        if self.save_options.run_metadata:
            grp = self._file.require_group("run_info")
            for key, value in self.run_info.items():
                grp.attrs[key] = self._serialise_attr(value)
            grp.attrs["start_time"] = self._file.attrs["start_time"]

    def set_outcome(self, outcome: str, reason: str | None = None) -> None:
        """Record how the run ended; written into the file by :meth:`close`.

        *outcome* must be one of :attr:`VALID_OUTCOMES` (``"finished"``,
        ``"aborted"``, ``"error"``).  *reason* is free text — an abort/error
        cause such as "operator abort", "bias compliance trip", or a latched
        HV-trip message; leave it ``None``/empty for a clean finish.

        Call this **before** :meth:`close`.  It only records the caller's
        intent in memory; nothing touches disk until ``close()`` runs, so
        calling it more than once (a caller changing its mind, or a retry) is
        fine — the last call wins.  A writer that is closed WITHOUT this ever
        having been called writes :attr:`UNKNOWN_OUTCOME`, never
        ``"finished"`` — see :meth:`close`.
        """
        if outcome not in self.VALID_OUTCOMES:
            raise ValueError(
                f"invalid outcome {outcome!r}; must be one of "
                f"{sorted(self.VALID_OUTCOMES)}"
            )
        self._outcome = outcome
        self._abort_reason = reason or ""

    def close(self) -> None:
        if self._file is None:
            return
        self._file.attrs["stop_time"] = datetime.now().isoformat(timespec="seconds")
        # Outcome/abort_reason are ROOT attrs (like start_time/stop_time), NOT
        # gated behind the optional `run_metadata` group: they are integrity
        # information, not reconstructable scan metadata, so they must survive
        # even when run_metadata saving is off.  A writer closed without a
        # prior set_outcome() call (crash, killed process, a missed call site)
        # writes UNKNOWN_OUTCOME — the honest default for "we don't know how
        # this run ended" is never "finished". This is the guarantee that a
        # crashed/killed run can never masquerade as a clean one.
        self._file.attrs["outcome"] = self._outcome or self.UNKNOWN_OUTCOME
        self._file.attrs["abort_reason"] = self._abort_reason
        if "camera" in self._file:
            # Same always-written honesty pattern as the root outcome attr
            # above: a dropped camera frame must never be silently invisible.
            # Written whenever the camera group exists (i.e. camera_frame
            # saving was on for at least one point) — even when the count is
            # zero, so "no attr" never has to be read as "no drops".
            self._file["camera"].attrs["n_frames_omitted"] = self._n_frames_omitted
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

        if self.save_options.camera_frame:
            # Group is created here (whenever camera saving is on for this
            # point), not only on a successful frame write, so a run whose
            # every grab fails still gets an honest n_frames_omitted on close.
            cam = f.require_group("camera")
            if result.camera_frame is not None:
                # point is already known here (it is `points/` row `idx`,
                # written above), so it costs nothing to tag this frame's
                # true position too — same honesty contract as the
                # standalone save_camera_frame() path below.
                self._save_camera_frame(
                    cam, idx, result.camera_frame,
                    pos_mm=(point.x_mm, point.y_mm, point.z_mm),
                )
            else:
                self._n_frames_omitted += 1
                logger.warning(
                    "Point %d: camera_frame is None (grab failed); frame omitted", idx
                )

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

    def set_camera_calibration(
        self, px_per_mm: float | None = None, affine: Any = None
    ) -> None:
        """Record object-plane camera calibration as ``camera`` group attrs.

        Feeds from the metrology track (``analysis/camera_calibration.py``),
        not from a per-point frame — so it lazily creates the ``camera`` group
        itself if no frame has been saved yet.  ``px_per_mm`` is the scalar
        mean scale (``AffineFit.mean_px_per_mm``); ``affine`` is stored as a
        flat float64 array attr (e.g. the 2x3 ``matrix_px_per_mm``/``offset_px``
        the caller assembles) — the writer does not interpret its shape.
        Either argument may be omitted; passing neither is a no-op other than
        creating the group.
        """
        f = self._require_open()
        grp = f.require_group("camera")
        if px_per_mm is not None:
            grp.attrs["px_per_mm"] = float(px_per_mm)
        if affine is not None:
            grp.attrs["affine"] = np.asarray(affine, dtype="f8")

    def save_camera_frame(self, frame: Any, pos_mm: Any = None) -> None:
        """Persist one standalone camera frame (e.g. a CAPTURE_PHOTO plan step).

        Appends to ``camera/frames`` and tags it with the CURRENT point index
        (:attr:`_n_points`) in ``camera/frame_point_index`` — the SAME honesty
        contract as the per-point frame in :meth:`save_point`, via the same
        :meth:`_save_camera_frame` primitive: ``frames[k]`` belongs to
        ``points`` row ``frame_point_index[k]`` (``M <= N``), and a
        ``None`` / ``ndim < 2`` / shape-mismatch frame is counted in
        ``n_frames_omitted`` and logged rather than zero-backfilled.  The
        ``camera`` group is created on first use.

        *pos_mm* is the optional ``(x_mm, y_mm, z_mm)`` stage position the
        frame was grabbed at (e.g. from a photo-only survey, where ``points/``
        stays empty — see ``controller/survey_plan.py``'s "KNOWN GAP" note).
        When an accepted frame is written, ``camera/frame_pos_mm`` gets exactly
        one row (index-aligned with ``frames``/``frame_point_index``, so it
        stays ``M``-long too): the given ``(x, y, z)`` cast to float, or
        ``(NaN, NaN, NaN)`` when *pos_mm* is ``None`` (E6b honesty contract —
        an unknown position is an explicit NaN row, never a fake ``(0, 0, 0)``
        and never a skipped row that would desync the three ``M``-indexed
        arrays). See :meth:`_save_camera_frame` and SCAN_DATA_FORMAT.md.

        Unlike :meth:`save_point`, this writes ONLY the camera group: a
        standalone photo has no waveform / analysis / bias row, and routing it
        through ``save_point`` would write the mandatory (and, for a photo-only
        capture, empty) ``waveforms`` group — which crashes on the zero-size
        waveform chunk or desyncs the waveforms/points parallel arrays.  It does
        NOT advance ``_n_points`` (only a real point does); a following
        ``SAVE_POINT`` at the same coordinate occupies that point row.

        Caveat (dangling tag): the tagged index NAMES the point row this frame
        will belong to once that following ``SAVE_POINT`` is written — it does
        not require one to already exist.  A plan that calls this and then
        never writes a ``SAVE_POINT`` for that coordinate (run ends early, or
        moves on to a different point without saving this one) leaves a
        dangling tag: ``frame_point_index[k] >= len(points/x_mm)`` at read
        time.  Readers must bounds-check ``frame_point_index`` against
        ``points/`` length before indexing — the same discipline any
        ``camera/`` consumer already needs for ``M <= N`` (SCAN_DATA_FORMAT.md
        "Datasets (XY scans)" — a follow-up should call this out there too).
        """
        f = self._require_open()
        cam = f.require_group("camera")
        self._save_camera_frame(cam, self._n_points, frame, pos_mm=pos_mm)
        f.flush()

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

    def _save_camera_frame(
        self, grp: h5py.Group, point_idx: int, frame: Any, pos_mm: Any = None
    ) -> None:
        """Append one frame, or count+log why it was dropped.

        ``camera/frames`` is indexed by *frame count*, not point index: a
        dropped frame is never zero-backfilled, and ``camera/frame_point_index``
        records which point each written frame actually belongs to (see
        SCAN_DATA_FORMAT.md). Every drop path here increments
        ``self._n_frames_omitted`` and logs the reason — a dropped frame must
        never be byte-indistinguishable from a real one.

        *pos_mm* (optional ``(x_mm, y_mm, z_mm)``) is written to
        ``camera/frame_pos_mm`` in lockstep with ``frames``/``frame_point_index``
        (one row per ACCEPTED frame, ``M``-long, never appended on a drop —
        the three arrays stay index-aligned). A ``None`` component or a
        ``None`` *pos_mm* itself becomes ``NaN`` in that row — an unknown
        position is explicit, never a fabricated ``(0, 0, 0)`` (E6b).
        """
        arr = np.asarray(frame)
        if arr.ndim < 2:
            self._n_frames_omitted += 1
            logger.warning(
                "Point %d: camera frame has ndim=%d (<2); frame omitted",
                point_idx, arr.ndim,
            )
            return
        if self._camera_shape is None:
            self._camera_shape = tuple(arr.shape)
        if tuple(arr.shape) != self._camera_shape:
            self._n_frames_omitted += 1
            logger.warning(
                "Point %d: camera frame shape %s != first-frame shape %s; frame omitted",
                point_idx, tuple(arr.shape), self._camera_shape,
            )
            return
        frame_idx = self._n_frames_written
        self._append_array(grp, "frames", frame_idx, arr, self._camera_shape)
        self._append_scalar(grp, "frame_point_index", frame_idx, point_idx, dtype="i8")
        xyz = list(pos_mm) if pos_mm is not None else [None, None, None]
        xyz = (xyz + [None, None, None])[:3]  # tolerate a short/long caller tuple
        pos_row = np.array([_nan_if_none(v) for v in xyz], dtype="f8")
        self._append_array(grp, "frame_pos_mm", frame_idx, pos_row, (3,))
        grp["frame_pos_mm"].attrs["columns"] = ["x_mm", "y_mm", "z_mm"]
        self._n_frames_written += 1

    def _append_scalar(
        self, group: h5py.Group, name: str, idx: int, value: Any, dtype: str = "f8"
    ) -> None:
        if name not in group:
            group.create_dataset(
                name,
                shape=(0,),
                maxshape=(None,),
                dtype=dtype,
                chunks=(64,),
                compression="gzip",
            )
        ds = group[name]
        ds.resize((idx + 1,))
        ds[idx] = _nan_if_none(value) if dtype == "f8" else value

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
