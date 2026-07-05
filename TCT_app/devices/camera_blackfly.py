"""
FLIR Blackfly BFLY-U3-23S6M-C camera driver (Spinnaker SDK / PySpin).

Sensor  : Sony IMX249  —  1920 × 1200 pixels, 5.86 µm pitch, USB3 Vision
Formats : Mono8 (8-bit), Mono16 (16-bit, camera outputs 12-bit zero-padded)

Features implemented
--------------------
* Continuous acquisition (one BeginAcquisition per session, not per frame)
* GenICam chunk data — FrameID, Timestamp, ExposureTime, Gain, BlackLevel
* ROI  (OffsetX / OffsetY / Width / Height)
* Symmetric binning  (1, 2, 4)
* Pixel format selection  (Mono8 | Mono16)
* Gamma  (enable/disable + value)
* Black-level correction
* Auto-exposure / auto-gain  (Continuous or Off)
* Frame-rate control  (AcquisitionFrameRate)
* Hardware trigger on Line0 (falling edge) / free-running
* Device temperature readout  (DeviceTemperature node)
* Background frame capture + per-pixel subtraction
* Beam statistics via image moments  (centroid, σx, σy, min/max/mean/std)
* Simulation mode — drifting Gaussian + Poisson-like noise, no hardware needed

Config keys  (devices.yaml → camera)
-------------------------------------
    serial_number : "19112408"
    exposure_us   : 5000
    gain_db       : 0.0
    pixel_format  : "Mono8"          # Mono8 | Mono16
    gamma_enabled : true
    gamma_value   : 1.0
    binning       : 1                # 1 | 2 | 4
    fps           : 10.0
    simulation    : false
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from .base import BaseDevice, DeviceError

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Per-frame metadata
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FrameMeta:
    """Per-frame metadata returned alongside image data."""
    # ── Chunk data from camera ────────────────────────────────────────────
    frame_id     : int   = 0
    timestamp_ns : int   = 0      # hardware camera timestamp (ns)
    exposure_us  : float = 0.0    # actual exposure applied
    gain_db      : float = 0.0    # actual gain applied
    black_level  : float = 0.0
    # ── Frame geometry ────────────────────────────────────────────────────
    width        : int   = 0
    height       : int   = 0
    pixel_format : str   = ""
    # ── Pixel statistics ─────────────────────────────────────────────────
    pix_min  : float = 0.0
    pix_max  : float = 0.0
    pix_mean : float = 0.0
    pix_std  : float = 0.0
    # ── Beam parameters (image-moment method) ────────────────────────────
    centroid_x : float = 0.0   # sub-pixel, in sensor pixels
    centroid_y : float = 0.0
    sigma_x    : float = 0.0   # 1-σ beam radius in X, pixels
    sigma_y    : float = 0.0   # 1-σ beam radius in Y, pixels


# ──────────────────────────────────────────────────────────────────────────────
# Camera driver
# ──────────────────────────────────────────────────────────────────────────────

class BlackflyCamera(BaseDevice):
    """
    FLIR Blackfly BFLY-U3-23S6M-C via PySpin (Spinnaker SDK 3.x / 4.x).

    Falls back to simulation when PySpin is not installed so the GUI can
    be developed without camera hardware.
    """

    SENSOR_W = 1920
    SENSOR_H = 1200

    def __init__(
        self,
        serial_number : str   = "",
        exposure_us   : float = 5000.0,
        gain_db       : float = 0.0,
        pixel_format  : str   = "Mono8",
        gamma_enabled : bool  = True,
        gamma_value   : float = 1.0,
        binning       : int   = 1,
        fps           : float = 10.0,
        simulation    : bool  = False,
    ) -> None:
        super().__init__(simulation=simulation)
        self._serial        = serial_number
        self._exposure_us   = exposure_us
        self._gain_db       = gain_db
        self._pixel_format  = pixel_format
        self._gamma_enabled = gamma_enabled
        self._gamma_value   = gamma_value
        self._binning       = int(binning)
        self._fps_target    = float(fps)
        self._auto_exposure = False
        self._auto_gain     = False
        self._trigger_enabled = False
        self._background    : Optional[np.ndarray] = None
        self._acquiring     = False

        self._system  : Any = None
        self._cam     : Any = None
        self._pyspin  : Any = None   # PySpin module reference

        # Simulation counters
        self._sim_frame_id = 0
        self._sim_t0       = 0.0

    # ──────────────────────────────────────────────────────────────────── #
    # BaseDevice interface                                                 #
    # ──────────────────────────────────────────────────────────────────── #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            self._sim_t0 = time.monotonic()
            logger.info("BlackflyCamera connected (simulation)")
            return

        try:
            import PySpin as ps  # type: ignore[import]
            self._pyspin = ps
        except ImportError:
            logger.warning("PySpin not available — falling back to simulation mode")
            self.simulation = True
            self._connected = True
            self._sim_t0 = time.monotonic()
            return

        ps = self._pyspin
        self._system = ps.System.GetInstance()
        cam_list = self._system.GetCameras()
        if cam_list.GetSize() == 0:
            cam_list.Clear()
            raise DeviceError("No FLIR cameras detected on USB bus.")

        self._cam = (
            cam_list.GetBySerial(self._serial)
            if self._serial
            else cam_list.GetByIndex(0)
        )
        cam_list.Clear()

        self._cam.Init()
        self._configure_transport_layer()
        self._apply_all_settings()
        self._enable_chunk_data()
        self._start_acquisition()
        self._connected = True
        logger.info(
            "BlackflyCamera connected  serial=%s  format=%s  %dx%d  %.1f fps",
            self._serial or "auto",
            self._pixel_format,
            self._cam.Width.GetValue(),
            self._cam.Height.GetValue(),
            self.get_fps_actual(),
        )

    def disconnect(self) -> None:
        self._stop_acquisition()
        if self._cam is not None:
            try:
                self._cam.DeInit()
            except Exception:
                pass
        if self._system is not None:
            try:
                self._system.ReleaseInstance()
            except Exception:
                pass
        self._cam     = None
        self._system  = None
        self._pyspin  = None
        self._connected = False

    # ──────────────────────────────────────────────────────────────────── #
    # Camera settings                                                      #
    # ──────────────────────────────────────────────────────────────────── #

    def set_exposure(self, exposure_us: float, auto: bool = False) -> None:
        """Set exposure time in µs.  auto=True → ExposureAuto_Continuous."""
        self._exposure_us   = exposure_us
        self._auto_exposure = auto
        if self._cam is None:
            return
        ps = self._pyspin
        if auto:
            self._cam.ExposureAuto.SetValue(ps.ExposureAuto_Continuous)
        else:
            self._cam.ExposureAuto.SetValue(ps.ExposureAuto_Off)
            clipped = float(np.clip(
                exposure_us,
                self._cam.ExposureTime.GetMin(),
                self._cam.ExposureTime.GetMax(),
            ))
            self._cam.ExposureTime.SetValue(clipped)

    def set_gain(self, gain_db: float, auto: bool = False) -> None:
        """Set analog gain in dB.  auto=True → GainAuto_Continuous."""
        self._gain_db  = gain_db
        self._auto_gain = auto
        if self._cam is None:
            return
        ps = self._pyspin
        if auto:
            self._cam.GainAuto.SetValue(ps.GainAuto_Continuous)
        else:
            self._cam.GainAuto.SetValue(ps.GainAuto_Off)
            clipped = float(np.clip(
                gain_db,
                self._cam.Gain.GetMin(),
                self._cam.Gain.GetMax(),
            ))
            self._cam.Gain.SetValue(clipped)

    def set_pixel_format(self, fmt: str) -> None:
        """Set pixel format: 'Mono8' or 'Mono16'."""
        self._pixel_format = fmt
        if self._cam is None:
            return
        ps = self._pyspin
        fmt_map = {
            "Mono8":  ps.PixelFormat_Mono8,
            "Mono16": ps.PixelFormat_Mono16,
        }
        if fmt not in fmt_map:
            logger.warning("Unknown pixel format '%s'; using Mono8", fmt)
            fmt = "Mono8"
        was = self._acquiring
        if was:
            self._stop_acquisition()
        try:
            self._cam.PixelFormat.SetValue(fmt_map[fmt])
        except Exception as exc:
            logger.warning("PixelFormat set failed: %s", exc)
        if was:
            self._start_acquisition()

    def set_gamma(self, enabled: bool, value: float = 1.0) -> None:
        """Enable/disable gamma correction and set the gamma exponent."""
        self._gamma_enabled = enabled
        self._gamma_value   = value
        if self._cam is None:
            return
        try:
            self._cam.GammaEnable.SetValue(enabled)
            if enabled:
                clipped = float(np.clip(
                    value,
                    self._cam.Gamma.GetMin(),
                    self._cam.Gamma.GetMax(),
                ))
                self._cam.Gamma.SetValue(clipped)
        except Exception as exc:
            logger.debug("Gamma node not accessible: %s", exc)

    def set_black_level(self, value: float) -> None:
        """Set black-level offset (camera counts)."""
        if self._cam is None:
            return
        try:
            self._cam.BlackLevelSelector.SetValue(
                self._pyspin.BlackLevelSelector_All
            )
            clipped = float(np.clip(
                value,
                self._cam.BlackLevel.GetMin(),
                self._cam.BlackLevel.GetMax(),
            ))
            self._cam.BlackLevel.SetValue(clipped)
        except Exception as exc:
            logger.debug("BlackLevel not settable: %s", exc)

    def set_binning(self, n: int) -> None:
        """Set symmetric horizontal + vertical binning (1, 2, or 4)."""
        self._binning = int(n)
        if self._cam is None:
            return
        was = self._acquiring
        if was:
            self._stop_acquisition()
        try:
            self._cam.BinningHorizontal.SetValue(n)
            self._cam.BinningVertical.SetValue(n)
        except Exception as exc:
            logger.warning("Binning set failed: %s", exc)
        if was:
            self._start_acquisition()

    def set_roi(
        self,
        offset_x: int,
        offset_y: int,
        width: int,
        height: int,
    ) -> None:
        """
        Set region of interest.
        Pass width=0 or height=0 to reset to full sensor.
        """
        if self._cam is None:
            return
        was = self._acquiring
        if was:
            self._stop_acquisition()
        try:
            if width == 0 or height == 0:
                # Full sensor
                self._cam.OffsetX.SetValue(0)
                self._cam.OffsetY.SetValue(0)
                self._cam.Width.SetValue(self._cam.Width.GetMax())
                self._cam.Height.SetValue(self._cam.Height.GetMax())
            else:
                # Must zero offsets first before changing dimensions
                self._cam.OffsetX.SetValue(0)
                self._cam.OffsetY.SetValue(0)
                self._cam.Width.SetValue(
                    int(np.clip(width,  1, self._cam.Width.GetMax()))
                )
                self._cam.Height.SetValue(
                    int(np.clip(height, 1, self._cam.Height.GetMax()))
                )
                self._cam.OffsetX.SetValue(
                    int(np.clip(offset_x, 0, self._cam.OffsetX.GetMax()))
                )
                self._cam.OffsetY.SetValue(
                    int(np.clip(offset_y, 0, self._cam.OffsetY.GetMax()))
                )
        except Exception as exc:
            logger.warning("ROI set failed: %s", exc)
        if was:
            self._start_acquisition()

    def set_frame_rate(self, fps: float) -> None:
        """Set target acquisition frame rate."""
        self._fps_target = fps
        if self._cam is None:
            return
        try:
            self._cam.AcquisitionFrameRateEnable.SetValue(True)
            clipped = float(np.clip(
                fps,
                self._cam.AcquisitionFrameRate.GetMin(),
                self._cam.AcquisitionFrameRate.GetMax(),
            ))
            self._cam.AcquisitionFrameRate.SetValue(clipped)
        except Exception as exc:
            logger.debug("Frame-rate control unavailable: %s", exc)

    def set_trigger(self, enabled: bool) -> None:
        """
        Enable hardware trigger on Line0 (falling edge).
        When disabled the camera free-runs at the configured frame rate.
        """
        self._trigger_enabled = enabled
        if self._cam is None:
            return
        ps = self._pyspin
        was = self._acquiring
        if was:
            self._stop_acquisition()
        try:
            self._cam.TriggerMode.SetValue(ps.TriggerMode_Off)
            if enabled:
                self._cam.TriggerSource.SetValue(ps.TriggerSource_Line0)
                self._cam.TriggerActivation.SetValue(
                    ps.TriggerActivation_FallingEdge
                )
                self._cam.TriggerMode.SetValue(ps.TriggerMode_On)
        except Exception as exc:
            logger.warning("Trigger setup failed: %s", exc)
        if was:
            self._start_acquisition()

    # ──────────────────────────────────────────────────────────────────── #
    # Read-only camera state                                               #
    # ──────────────────────────────────────────────────────────────────── #

    def get_temperature(self) -> float:
        """Device temperature in °C (NaN in simulation or if unavailable)."""
        if self.simulation or self._cam is None:
            return float("nan")
        try:
            return float(self._cam.DeviceTemperature.GetValue())
        except Exception:
            return float("nan")

    def get_fps_actual(self) -> float:
        """Resulting frame rate reported by the camera."""
        if self.simulation or self._cam is None:
            return self._fps_target
        try:
            return float(self._cam.AcquisitionResultingFrameRate.GetValue())
        except Exception:
            return float("nan")

    def get_camera_info(self) -> dict:
        """Static camera properties (vendor, model, serial, firmware, …)."""
        if self.simulation:
            return {
                "vendor":   "FLIR (simulated)",
                "model":    "BFLY-U3-23S6M-C",
                "serial":   self._serial or "SIM",
                "firmware": "sim",
                "sensor_w": self.SENSOR_W,
                "sensor_h": self.SENSOR_H,
                "pixel_size_um": 5.86,
            }
        if self._cam is None:
            return {}
        ps  = self._pyspin
        tl  = self._cam.GetTLDeviceNodeMap()

        def _str(name: str) -> str:
            try:
                n = ps.CStringPtr(tl.GetNode(name))
                return n.GetValue() if ps.IsAvailable(n) and ps.IsReadable(n) else ""
            except Exception:
                return ""

        return {
            "vendor":        _str("DeviceVendorName"),
            "model":         _str("DeviceModelName"),
            "serial":        _str("DeviceSerialNumber"),
            "firmware":      _str("DeviceFirmwareVersion"),
            "sensor_w":      self.SENSOR_W,
            "sensor_h":      self.SENSOR_H,
            "pixel_size_um": 5.86,
        }

    def get_roi(self) -> tuple[int, int, int, int]:
        """Return current ROI as (offset_x, offset_y, width, height)."""
        if self._cam is None:
            return (0, 0, self.SENSOR_W, self.SENSOR_H)
        try:
            return (
                int(self._cam.OffsetX.GetValue()),
                int(self._cam.OffsetY.GetValue()),
                int(self._cam.Width.GetValue()),
                int(self._cam.Height.GetValue()),
            )
        except Exception:
            return (0, 0, self.SENSOR_W, self.SENSOR_H)

    # ──────────────────────────────────────────────────────────────────── #
    # Frame acquisition                                                    #
    # ──────────────────────────────────────────────────────────────────── #

    def get_frame(self) -> np.ndarray:
        """Capture one frame; return uint8 or uint16 ndarray (H × W)."""
        arr, _ = self.get_frame_with_meta()
        return arr

    def get_frame_with_meta(self) -> tuple[np.ndarray, FrameMeta]:
        """
        Capture one frame and return *(array, FrameMeta)*.

        The FrameMeta includes GenICam chunk data (frame ID, hardware
        timestamp, actual exposure + gain) and computed beam statistics
        (centroid, σx/σy, min/max/mean/std).
        """
        if self.simulation or self._cam is None:
            return self._simulated_frame_with_meta()

        try:
            image = self._cam.GetNextImage(2000)   # 2 s timeout
        except self._pyspin.SpinnakerException as exc:
            raise DeviceError(f"GetNextImage failed: {exc}") from exc

        if image.IsIncomplete():
            image.Release()
            raise DeviceError("Blackfly: incomplete frame received")

        arr = image.GetNDArray().copy()   # H × W  uint8 or uint16

        meta = FrameMeta(
            width=arr.shape[1],
            height=arr.shape[0],
            pixel_format=self._pixel_format,
        )

        # ── Chunk data (best-effort) ──────────────────────────────────
        try:
            chunk = image.GetChunkData()
            meta.frame_id      = int(chunk.GetFrameID())
            meta.timestamp_ns  = int(chunk.GetTimestamp())
            meta.exposure_us   = float(chunk.GetExposureTime())
            meta.gain_db       = float(chunk.GetGain())
            meta.black_level   = float(chunk.GetBlackLevel())
        except Exception:
            meta.exposure_us = self._exposure_us
            meta.gain_db     = self._gain_db

        image.Release()

        # ── Background subtraction ────────────────────────────────────
        if self._background is not None and self._background.shape == arr.shape:
            arr = np.clip(
                arr.astype(np.int32) - self._background.astype(np.int32),
                0, None,
            ).astype(arr.dtype)

        # ── Beam statistics ───────────────────────────────────────────
        self._fill_beam_stats(arr, meta)
        return arr, meta

    def capture_background(self) -> None:
        """Store the current frame as background for subtraction."""
        frame, _ = self.get_frame_with_meta()
        self._background = frame.copy()
        logger.info("Background captured  shape=%s", frame.shape)

    def clear_background(self) -> None:
        """Remove stored background."""
        self._background = None

    # ──────────────────────────────────────────────────────────────────── #
    # Internal helpers                                                     #
    # ──────────────────────────────────────────────────────────────────── #

    def _configure_transport_layer(self) -> None:
        """Keep only the newest buffer to avoid latency build-up."""
        ps = self._pyspin
        try:
            tl = self._cam.GetTLStreamNodeMap()
            mode_node = ps.CEnumerationPtr(tl.GetNode("StreamBufferHandlingMode"))
            if ps.IsAvailable(mode_node) and ps.IsWritable(mode_node):
                entry = mode_node.GetEntryByName("NewestOnly")
                if ps.IsAvailable(entry) and ps.IsReadable(entry):
                    mode_node.SetIntValue(entry.GetValue())
        except Exception as exc:
            logger.debug("TL stream config: %s", exc)

    def _apply_all_settings(self) -> None:
        self.set_exposure(self._exposure_us, self._auto_exposure)
        self.set_gain(self._gain_db, self._auto_gain)
        self.set_pixel_format(self._pixel_format)
        self.set_gamma(self._gamma_enabled, self._gamma_value)
        self.set_binning(self._binning)
        self.set_frame_rate(self._fps_target)

    def _enable_chunk_data(self) -> None:
        """Enable GenICam chunk: FrameID, Timestamp, ExposureTime, Gain, BlackLevel."""
        if self._cam is None:
            return
        ps = self._pyspin
        try:
            self._cam.ChunkModeActive.SetValue(True)
            for name in ("FrameID", "Timestamp", "ExposureTime", "Gain", "BlackLevel"):
                try:
                    self._cam.ChunkSelector.SetValue(
                        getattr(ps, f"ChunkSelector_{name}")
                    )
                    self._cam.ChunkEnable.SetValue(True)
                except Exception as exc:
                    logger.debug("Chunk '%s' unavailable: %s", name, exc)
        except Exception as exc:
            logger.warning("Chunk data enable failed: %s", exc)

    def _start_acquisition(self) -> None:
        if self._cam is None or self._acquiring:
            return
        ps = self._pyspin
        self._cam.AcquisitionMode.SetValue(ps.AcquisitionMode_Continuous)
        self._cam.BeginAcquisition()
        self._acquiring = True

    def _stop_acquisition(self) -> None:
        if self._cam is None or not self._acquiring:
            return
        try:
            self._cam.EndAcquisition()
        except Exception:
            pass
        self._acquiring = False

    # ──────────────────────────────────────────────────────────────────── #
    # Beam statistics                                                      #
    # ──────────────────────────────────────────────────────────────────── #

    @staticmethod
    def _fill_beam_stats(arr: np.ndarray, meta: FrameMeta) -> None:
        """
        Compute pixel statistics and beam centroid / widths from image moments.
        Fast (no scipy fit) — uses weighted centroid and 2nd central moments.
        """
        f = arr.astype(np.float64)
        meta.pix_min  = float(f.min())
        meta.pix_max  = float(f.max())
        meta.pix_mean = float(f.mean())
        meta.pix_std  = float(f.std())

        total = f.sum()
        if total <= 0.0:
            return

        h, w = f.shape
        xs = np.arange(w, dtype=np.float64)
        ys = np.arange(h, dtype=np.float64)

        row_sum = f.sum(axis=1)   # shape (H,)
        col_sum = f.sum(axis=0)   # shape (W,)

        cx = float(col_sum @ xs / total)
        cy = float(row_sum @ ys / total)
        meta.centroid_x = cx
        meta.centroid_y = cy

        # 2nd central moments → beam 1-σ radii
        dx = xs - cx
        dy = ys - cy
        meta.sigma_x = float(np.sqrt(col_sum @ (dx * dx) / total))
        meta.sigma_y = float(np.sqrt(row_sum @ (dy * dy) / total))

    # ──────────────────────────────────────────────────────────────────── #
    # Simulation                                                           #
    # ──────────────────────────────────────────────────────────────────── #

    def _simulated_frame_with_meta(self) -> tuple[np.ndarray, FrameMeta]:
        """Return a slowly drifting Gaussian beam with Poisson-like noise."""
        h, w = 480, 640
        t    = time.monotonic() - self._sim_t0

        cx     = w / 2 + 20 * np.sin(0.31 * t)
        cy     = h / 2 + 15 * np.cos(0.19 * t)
        sig_x  = 38 + 6 * np.sin(0.11 * t)
        sig_y  = 30 + 4 * np.cos(0.14 * t)

        xs, ys = np.meshgrid(np.arange(w), np.arange(h))
        beam   = np.exp(
            -((xs - cx) ** 2) / (2 * sig_x ** 2)
            - ((ys - cy) ** 2) / (2 * sig_y ** 2)
        )
        # Poisson noise scaled to bit depth
        dtype  = np.uint16 if self._pixel_format == "Mono16" else np.uint8
        scale  = 65535 if dtype == np.uint16 else 255
        signal = (beam * scale * 0.85).clip(0, scale)
        noisy  = np.random.poisson(signal.clip(0, 1e7)).clip(0, scale).astype(dtype)

        meta = FrameMeta(
            frame_id     = self._sim_frame_id,
            timestamp_ns = int(t * 1e9),
            exposure_us  = self._exposure_us,
            gain_db      = self._gain_db,
            black_level  = 0.0,
            width        = w,
            height       = h,
            pixel_format = self._pixel_format,
        )
        self._sim_frame_id += 1
        self._fill_beam_stats(noisy, meta)
        return noisy, meta
