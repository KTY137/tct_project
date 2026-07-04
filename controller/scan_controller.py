"""
TCT scan controller.

Drives the full automated scan loop:
  move → settle → image → trigger → acquire → analyse → save → update map.

References only abstract base classes (MotorStageBase, IntensityMonitorBase)
so the scan logic is completely decoupled from the hardware backend.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from controller.state_machine import StateMachine, AppState
from controller.device_manager import DeviceManager
from devices.base import DeviceError
from analysis.waveform_analysis import analyse_waveform, WaveformResult
from analysis.laser_normalization import normalise
from data.hdf5_writer import HDF5Writer

logger = logging.getLogger(__name__)


@dataclass
class ScanConfig:
    x_start_mm: float = -1.0
    x_stop_mm:  float =  1.0
    x_step_mm:  float =  0.1
    y_start_mm: float = -1.0
    y_stop_mm:  float =  1.0
    y_step_mm:  float =  0.1
    z_mm:       float =  0.0
    n_averages: int   =  1
    settle_time_s: float = 0.05


@dataclass
class ZFocusScanConfig:
    """
    Z-axis focal-point calibration scan.

    Two modes
    ---------
    mode = "amplitude"
        Legacy mode: hold (x_mm, y_mm) fixed and sweep Z.  Best Z = max DUT
        amplitude.  Only reliable when the beam is positioned over the silicon
        bulk (between strip metallisation).

    mode = "edge_scan"  (recommended)
        Physically correct mode per Particulars / standard TCT practice.
        At each Z step the stage scans a short X range crossing a metal/silicon
        edge.  The spatial gradient |dQ/dx| is computed; best Z is where this
        gradient is maximum, i.e. the beam spot is smallest and the edge
        transition is sharpest.  This method works regardless of whether the
        beam is between strips or not, and is insensitive to absolute signal
        level variations.
    """
    mode:       str   = "amplitude"   # "amplitude" | "edge_scan"

    # Common Z-sweep parameters
    x_mm:       float = 0.0    # fixed X position (amplitude mode) or X scan centre
    y_mm:       float = 0.0    # fixed Y position during full scan
    z_start_mm: float = -2.0
    z_stop_mm:  float =  2.0
    z_step_mm:  float =  0.1
    n_averages: int   =  3
    settle_time_s: float = 0.05

    # Edge-scan mode additional parameters
    # A short X scan is taken at each Z step.  Place x_edge_center_mm at the
    # approximate position of a metal/silicon transition (strip edge or pad edge).
    x_edge_center_mm: float = 0.0   # centre of the X scan (at the edge)
    x_edge_range_mm:  float = 0.1   # half-width of X scan (total = 2× this)
    x_edge_step_mm:   float = 0.005 # X step during edge scan (~5 µm)


@dataclass
class VoltageScanConfig:
    """
    Bias voltage scan at a fixed position.

    Steps the Keithley from v_start to v_stop in v_step increments,
    acquiring waveforms at each voltage.  Ramps back to 0 V when done.
    Aborts immediately if the bias supply hits current compliance.
    """
    v_start_V:    float = 0.0
    v_stop_V:     float = -300.0
    v_step_V:     float = -10.0    # sign sets direction
    ramp_step_V:  float = 5.0      # step size during ramp
    ramp_delay_s: float = 0.1      # delay per ramp step
    hold_delay_s: float = 1.0      # wait after reaching setpoint
    n_averages:   int   = 3
    x_mm: float = 0.0
    y_mm: float = 0.0
    z_mm: float = 0.0


@dataclass
class ScanPoint:
    x_mm: float
    y_mm: float
    z_mm: float
    index: int


@dataclass
class ScanResult:
    point: ScanPoint
    timestamp: float
    ref_amplitude_V: float
    ref_charge_pC: float
    dut_amplitude_V: float
    dut_charge_pC: float
    dut_charge_norm: float
    baseline_rms_V: float
    drift_time_s:  float | None = None   # carrier drift time = trailing - onset
    rise_time_s:   float | None = None   # 10%→90% rise time
    cfd_time_s:    float | None = None   # CFD threshold crossing time
    onset_time_s:  float | None = None   # leading-edge onset time
    camera_frame: np.ndarray | None = None
    ref_waveform: np.ndarray | None = None
    dut_waveform: np.ndarray | None = None
    time_axis: np.ndarray | None = None
    # Measured per-point context (not recomputable offline)
    bias_voltage_V: float | None = None
    bias_current_A: float | None = None
    slow_control: dict | None = None
    # Absolute-charge calibration result (set when a calibration is configured)
    dut_charge_cal: float | None = None
    charge_units: str | None = None


def _build_scan_points(cfg: ScanConfig) -> list[ScanPoint]:
    xs = np.arange(cfg.x_start_mm, cfg.x_stop_mm + cfg.x_step_mm / 2, cfg.x_step_mm)
    ys = np.arange(cfg.y_start_mm, cfg.y_stop_mm + cfg.y_step_mm / 2, cfg.y_step_mm)
    points: list[ScanPoint] = []
    for i, x in enumerate(xs):
        row = ys if i % 2 == 0 else ys[::-1]   # boustrophedon
        for y in row:
            points.append(ScanPoint(x_mm=float(x), y_mm=float(y), z_mm=cfg.z_mm, index=len(points)))
    return points


class ScanController:
    """
    Executes an automated 2-D (X/Y) TCT scan.

    Callbacks
    ---------
    on_point_done(result: ScanResult)   — called after each scan point
    on_progress(done: int, total: int)  — called after each scan point
    on_finished()                       — called when scan completes or aborts
    on_error(msg: str)                  — called on unrecoverable error
    """

    def __init__(
        self,
        devices: DeviceManager,
        state_machine: StateMachine,
        writer: HDF5Writer | None = None,
    ) -> None:
        self._dev = devices
        self._sm = state_machine
        # A fresh per-run writer is allocated by _begin_run; passing one here
        # is only useful for tests.
        self._writer = writer
        self._thread: threading.Thread | None = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._abort_event = threading.Event()

        # Public callbacks
        self.on_point_done: Callable[[ScanResult], None] | None = None
        self.on_progress:   Callable[[int, int], None]   | None = None
        self.on_finished:   Callable[[], None]           | None = None
        self.on_error:      Callable[[str], None]        | None = None
        # Voltage scan callback: (voltage_V, dut_charge_pC, current_A)
        self.on_vscan_point: Callable[[float, float, float], None] | None = None

    # ------------------------------------------------------------------ #
    # Run-directory / writer allocation                                   #
    # ------------------------------------------------------------------ #

    def _next_run_dir(self) -> Path:
        base = self._dev.data_dir
        base.mkdir(parents=True, exist_ok=True)
        existing = sorted(base.glob("run_*"))
        return base / f"run_{len(existing) + 1:05d}"

    def _begin_run(self, scan_type: str, cfg) -> HDF5Writer:
        """Allocate a fresh run directory + writer, attach run metadata, open it."""
        run_info = self._build_run_info(scan_type, cfg)
        self._writer = HDF5Writer(
            self._next_run_dir(),
            save_options=self._dev.save_options,
            run_info=run_info,
        )
        self._writer.open()
        return self._writer

    def _end_run(self) -> None:
        """Close the current writer, swallowing errors so cleanup never raises."""
        try:
            if self._writer is not None:
                self._writer.close()
        except Exception:
            logger.warning("Writer close failed", exc_info=True)

    def _save_z_focus(self, z_mm: float, metric: float) -> None:
        try:
            if self._writer is not None:
                self._writer.save_z_focus_point(z_mm, metric)
        except Exception:
            logger.warning("z-focus save failed", exc_info=True)

    def _save_voltage(self, voltage_V: float, charge_pC: float, current_A: float) -> None:
        try:
            if self._writer is not None:
                self._writer.save_voltage_point(voltage_V, charge_pC, current_A)
        except Exception:
            logger.warning("voltage-scan save failed", exc_info=True)

    def _build_run_info(self, scan_type: str, cfg) -> dict:
        try:
            scan_cfg = asdict(cfg) if is_dataclass(cfg) and not isinstance(cfg, type) else {}
        except Exception:
            scan_cfg = {}
        info: dict = {"scan_type": scan_type, "scan_config": scan_cfg}
        try:
            info["devices_config"] = self._dev.config_snapshot()
        except Exception:
            pass
        try:
            info["charge_calibration"] = self._dev.raw_config.get("charge_calibration", {})
        except Exception:
            pass
        lim = getattr(self._dev.motor, "limits", None)
        if lim is not None:
            info["software_limits"] = {
                "x_min": lim.x_min, "x_max": lim.x_max,
                "y_min": lim.y_min, "y_max": lim.y_max,
                "z_min": lim.z_min, "z_max": lim.z_max,
            }
        return info

    # ------------------------------------------------------------------ #
    # Public control interface                                            #
    # ------------------------------------------------------------------ #

    def start(self, cfg: ScanConfig) -> None:
        if not self._sm.can(AppState.RUNNING):
            raise RuntimeError("Cannot start scan in current state.")
        self._abort_event.clear()
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)
        self._thread = threading.Thread(
            target=self._run, args=(cfg,), daemon=True, name="ScanThread"
        )
        self._thread.start()

    def pause(self) -> None:
        self._pause_event.clear()
        self._sm.transition(AppState.PAUSED)

    def resume(self) -> None:
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)

    def abort(self) -> None:
        self._abort_event.set()
        self._pause_event.set()  # unblock if paused
        self._dev.motor.stop()

    def start_z_focus_scan(
        self,
        cfg: "ZFocusScanConfig",
        on_point: Callable[[float, float], None] | None = None,
        on_done:  Callable[[float], None] | None = None,
    ) -> None:
        """
        Run a Z-axis focal-point scan in a background thread.

        Sweeps Z from cfg.z_start_mm to cfg.z_stop_mm, measuring DUT
        amplitude at each step.  Reports each (z_mm, amplitude_V) via
        on_point, and the optimal Z via on_done when finished.
        """
        if not self._sm.can(AppState.RUNNING):
            raise RuntimeError("Cannot start Z-focus scan in current state.")
        self._abort_event.clear()
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)
        self._thread = threading.Thread(
            target=self._run_z_focus,
            args=(cfg, on_point, on_done),
            daemon=True,
            name="ZFocusThread",
        )
        self._thread.start()

    def start_voltage_scan(
        self,
        cfg: "VoltageScanConfig",
    ) -> None:
        """Run a bias voltage scan (IV curve) in a background thread."""
        if not self._sm.can(AppState.RUNNING):
            raise RuntimeError("Cannot start voltage scan in current state.")
        self._abort_event.clear()
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)
        self._thread = threading.Thread(
            target=self._run_voltage_scan,
            args=(cfg,),
            daemon=True,
            name="VoltageScanThread",
        )
        self._thread.start()

    # ------------------------------------------------------------------ #
    # Scan loop (runs in background thread)                               #
    # ------------------------------------------------------------------ #

    def _run(self, cfg: ScanConfig) -> None:
        points = _build_scan_points(cfg)
        total = len(points)
        logger.info("Scan started: %d points", total)

        bias_read_failures = 0
        try:
            self._begin_run("xy_scan", cfg)
            for point in points:
                # Pause / abort checks
                self._pause_event.wait()
                if self._abort_event.is_set():
                    logger.info("Scan aborted at point %d / %d", point.index, total)
                    break

                result = self._acquire_point(point, cfg)

                if self._abort_event.is_set():
                    break

                # Compliance-trip safety check during scan.  This is the only
                # protection against cooking a sensor mid-scan, so a failing
                # bias read must not be silently ignored: tolerate transient
                # glitches, abort after 3 consecutive failures.
                if self._dev.bias_supply.connected:
                    try:
                        bias_reading = self._dev.bias_supply.read()
                        bias_read_failures = 0
                        if bias_reading.compliant:
                            logger.warning("Compliance hit during scan at point %d — aborting", point.index)
                            self._abort_event.set()
                            if self.on_error:
                                self.on_error(
                                    f"Bias compliance trip at point {point.index} "
                                    f"({bias_reading.voltage_V:.1f} V, "
                                    f"I={bias_reading.current_A*1e6:.2f} µA).\n"
                                    "Scan aborted. Bias ramped to 0 V."
                                )
                            try:
                                self._dev.bias_supply.ramp_to(0.0, step_V=20.0, delay_s=0.05)
                                self._dev.bias_supply.output_off()
                            except Exception:
                                logger.warning("Post-compliance bias ramp-down failed", exc_info=True)
                            break
                    except Exception as exc:
                        bias_read_failures += 1
                        logger.warning(
                            "Bias read failed during scan (%d/3): %s",
                            bias_read_failures, exc,
                        )
                        if bias_read_failures >= 3:
                            raise DeviceError(
                                "Bias supply unreadable for 3 consecutive points — "
                                "compliance protection unavailable, scan aborted."
                            ) from exc

                self._writer.save_point(result)

                if self.on_point_done:
                    self.on_point_done(result)
                if self.on_progress:
                    self.on_progress(point.index + 1, total)

            # Resolve the end state for every exit path.  The loop can break
            # out of an abort/compliance check *without* having transitioned
            # (the old for/else only handled full completion, leaving the
            # state machine stuck in RUNNING after an abort).
            if self._sm.state in (AppState.RUNNING, AppState.PAUSED):
                if self._abort_event.is_set():
                    self._sm.transition(AppState.ABORTED)
                    logger.info("Scan aborted")
                else:
                    self._sm.transition(AppState.FINISHED)
                    logger.info("Scan finished")

        except Exception as exc:
            logger.exception("Scan error")
            self._sm.transition(AppState.ERROR)
            if self.on_error:
                self.on_error(str(exc))
        finally:
            self._end_run()
            # Always turn off laser trigger after scan
            try:
                self._dev.waveform_generator.output_off()
            except Exception:
                logger.warning("Waveform-generator output_off failed", exc_info=True)
            if self.on_finished:
                self.on_finished()

    def _run_z_focus(
        self,
        cfg: "ZFocusScanConfig",
        on_point: Callable[[float, float], None] | None,
        on_done:  Callable[[float], None] | None,
    ) -> None:
        """
        Background thread for Z focal-point scan.

        Two modes (cfg.mode):
          "amplitude"  — legacy: max DUT amplitude at fixed XY.
          "edge_scan"  — correct: max edge sharpness from a short X scan at
                         each Z, per Particulars / standard TCT practice.
        """
        if cfg.mode == "edge_scan":
            self._run_z_focus_edge(cfg, on_point, on_done)
        else:
            self._run_z_focus_amplitude(cfg, on_point, on_done)

    def _run_z_focus_amplitude(
        self,
        cfg: "ZFocusScanConfig",
        on_point: Callable[[float, float], None] | None,
        on_done:  Callable[[float], None] | None,
    ) -> None:
        """
        Legacy amplitude mode: sweep Z at a fixed (x, y) and return the Z
        with the highest DUT amplitude.

        Limitation: only works reliably when the beam is positioned over the
        silicon bulk (between strips).  Use edge_scan mode for robust focus
        finding.
        """
        dev = self._dev
        zs = np.arange(cfg.z_start_mm, cfg.z_stop_mm + cfg.z_step_mm / 2, cfg.z_step_mm)
        results: list[tuple[float, float]] = []

        try:
            self._begin_run("z_focus_amplitude", cfg)
            dev.waveform_generator.output_on()
            time.sleep(0.01)

            for z in zs:
                if self._abort_event.is_set():
                    break
                dev.motor.move_to(cfg.x_mm, cfg.y_mm, float(z))
                dev.motor.wait_until_ready()
                time.sleep(cfg.settle_time_s)

                amps = []
                for _ in range(max(cfg.n_averages, 1)):
                    t2, v2 = dev.scope.read_channel(2)
                    res = analyse_waveform(t2, v2, **self._dev.analysis_kwargs)
                    amps.append(res.amplitude_V)
                amp_mean = float(np.mean(amps))
                results.append((float(z), amp_mean))
                self._save_z_focus(float(z), amp_mean)
                logger.debug("Z-focus (amplitude): z=%.3f mm  amp=%.4f V", z, amp_mean)
                if on_point:
                    on_point(float(z), amp_mean)

            dev.waveform_generator.output_off()

            if results and not self._abort_event.is_set():
                best_z = max(results, key=lambda p: p[1])[0]
                logger.info("Z-focus best z = %.3f mm (amplitude mode)", best_z)
                if on_done:
                    on_done(best_z)

            self._sm.transition(
                AppState.ABORTED if self._abort_event.is_set() else AppState.FINISHED
            )
        except Exception as exc:
            logger.exception("Z-focus amplitude scan error")
            self._sm.transition(AppState.ERROR)
            if self.on_error:
                self.on_error(str(exc))
        finally:
            try:
                dev.waveform_generator.output_off()
            except Exception:
                pass
            self._end_run()
            if self.on_finished:
                self.on_finished()

    def _run_z_focus_edge(
        self,
        cfg: "ZFocusScanConfig",
        on_point: Callable[[float, float], None] | None,
        on_done:  Callable[[float], None] | None,
    ) -> None:
        """
        Edge-scan focus mode (physically correct).

        At each Z step a short X scan crosses a metal/silicon edge.
        Edge sharpness = max |dQ/dx| over the X profile.  The Z with the
        highest sharpness has the smallest beam spot = best focus.

        This is the technique described in the Particulars TCT manual:
        an error-function transition in charge collection becomes steepest
        (smallest FWHM) exactly at the focal plane of the objective.
        """
        dev = self._dev
        zs = np.arange(cfg.z_start_mm, cfg.z_stop_mm + cfg.z_step_mm / 2, cfg.z_step_mm)
        xs = np.arange(
            cfg.x_edge_center_mm - cfg.x_edge_range_mm,
            cfg.x_edge_center_mm + cfg.x_edge_range_mm + cfg.x_edge_step_mm / 2,
            cfg.x_edge_step_mm,
        )
        results: list[tuple[float, float]] = []   # (z_mm, sharpness)

        try:
            self._begin_run("z_focus_edge", cfg)
            dev.waveform_generator.output_on()
            time.sleep(0.01)

            for z in zs:
                if self._abort_event.is_set():
                    break

                charges: list[float] = []
                for x in xs:
                    if self._abort_event.is_set():
                        break
                    dev.motor.move_to(float(x), cfg.y_mm, float(z))
                    dev.motor.wait_until_ready()
                    time.sleep(cfg.settle_time_s)

                    pt_charges = []
                    for _ in range(max(cfg.n_averages, 1)):
                        t2, v2 = dev.scope.read_channel(2)
                        res = analyse_waveform(t2, v2, **self._dev.analysis_kwargs)
                        pt_charges.append(res.charge_pC)
                    charges.append(float(np.mean(pt_charges)))

                if len(charges) < 2 or self._abort_event.is_set():
                    break

                # Edge sharpness = peak absolute spatial gradient
                charge_arr = np.array(charges)
                dx = cfg.x_edge_step_mm
                gradient = np.abs(np.diff(charge_arr) / dx)
                sharpness = float(np.max(gradient))

                results.append((float(z), sharpness))
                self._save_z_focus(float(z), sharpness)
                logger.debug(
                    "Z-focus (edge): z=%.3f mm  sharpness=%.4f pC/mm", z, sharpness
                )
                # Report sharpness as the "amplitude" value so the GUI plot works
                if on_point:
                    on_point(float(z), sharpness)

            dev.waveform_generator.output_off()

            if results and not self._abort_event.is_set():
                best_z = max(results, key=lambda p: p[1])[0]
                logger.info("Z-focus best z = %.3f mm (edge mode)", best_z)
                if on_done:
                    on_done(best_z)

            self._sm.transition(
                AppState.ABORTED if self._abort_event.is_set() else AppState.FINISHED
            )
        except Exception as exc:
            logger.exception("Z-focus edge scan error")
            self._sm.transition(AppState.ERROR)
            if self.on_error:
                self.on_error(str(exc))
        finally:
            try:
                dev.waveform_generator.output_off()
            except Exception:
                pass
            self._end_run()
            if self.on_finished:
                self.on_finished()

    def _run_voltage_scan(self, cfg: "VoltageScanConfig") -> None:
        """Background thread: IV + charge vs. bias sweep."""
        dev = self._dev
        # Compute step sign from start/stop so the user only needs to supply
        # the magnitude of v_step_V (negative values are also accepted).
        raw_step = abs(cfg.v_step_V)
        if raw_step == 0:
            raw_step = 10.0
        direction = 1 if cfg.v_stop_V >= cfg.v_start_V else -1
        signed_step = direction * raw_step
        voltages = list(np.arange(
            cfg.v_start_V,
            cfg.v_stop_V + signed_step / 2,
            signed_step,
        ))
        total = len(voltages)
        logger.info("Voltage scan started: %d steps", total)

        try:
            self._begin_run("voltage_scan", cfg)
            dev.motor.move_to(cfg.x_mm, cfg.y_mm, cfg.z_mm)
            dev.motor.wait_until_ready()
            dev.waveform_generator.output_on()
            time.sleep(0.05)

            for idx, v in enumerate(voltages):
                if self._abort_event.is_set():
                    break

                dev.bias_supply.ramp_to(
                    float(v),
                    step_V=abs(cfg.ramp_step_V),
                    delay_s=cfg.ramp_delay_s,
                )
                time.sleep(cfg.hold_delay_s)

                reading = dev.bias_supply.read()
                # Compliance trip → abort immediately and ramp down
                if reading.compliant:
                    logger.warning(
                        "Compliance hit at %.1f V (I=%.3e A) — aborting voltage scan",
                        reading.voltage_V, reading.current_A,
                    )
                    if self.on_error:
                        self.on_error(
                            f"Compliance trip at {reading.voltage_V:.1f} V — "
                            f"I = {reading.current_A*1e6:.2f} µA.\n"
                            "Bias ramped back to 0 V."
                        )
                    break

                charges = []
                for _ in range(max(cfg.n_averages, 1)):
                    t2, v2 = dev.scope.read_channel(2)
                    res = analyse_waveform(t2, v2, **self._dev.analysis_kwargs)
                    charges.append(res.charge_pC)
                mean_chg = float(np.mean(charges))

                self._save_voltage(reading.voltage_V, mean_chg, reading.current_A)
                if self.on_vscan_point:
                    self.on_vscan_point(reading.voltage_V, mean_chg, reading.current_A)
                if self.on_progress:
                    self.on_progress(idx + 1, total)

            # Ramp back to 0 V
            dev.bias_supply.ramp_to(0.0, step_V=20.0, delay_s=0.05)
            dev.bias_supply.output_off()

            self._sm.transition(
                AppState.ABORTED if self._abort_event.is_set() else AppState.FINISHED
            )
        except Exception as exc:
            logger.exception("Voltage scan error")
            self._sm.transition(AppState.ERROR)
            if self.on_error:
                self.on_error(str(exc))
        finally:
            try:
                dev.waveform_generator.output_off()
                dev.bias_supply.ramp_to(0.0, step_V=20.0, delay_s=0.05)
                dev.bias_supply.output_off()
            except Exception:
                pass
            self._end_run()
            if self.on_finished:
                self.on_finished()

    def _acquire_point(self, point: ScanPoint, cfg: ScanConfig) -> ScanResult:
        dev = self._dev

        # 1. Move
        dev.motor.move_to(point.x_mm, point.y_mm, point.z_mm)
        dev.motor.wait_until_ready()

        # 2. Settle
        time.sleep(cfg.settle_time_s)

        # 3. Camera frame
        try:
            frame = dev.camera.get_frame()
        except Exception:
            frame = None

        # 4. Enable laser trigger, acquire, disable
        dev.waveform_generator.output_on()
        time.sleep(0.01)  # let oscilloscope arm

        ref_readings = []
        dut_results: list[WaveformResult] = []

        for _ in range(max(cfg.n_averages, 1)):
            ref = dev.intensity_monitor.read()
            ref_readings.append(ref)

            time_axis, dut_wfm = dev.scope.read_channel(2)
            dut_res = analyse_waveform(time_axis, dut_wfm, **self._dev.analysis_kwargs)
            dut_results.append(dut_res)

        dev.waveform_generator.output_off()

        # 5. Average
        ref_amp  = float(np.mean([r.amplitude_V for r in ref_readings]))
        ref_chg  = float(np.mean([r.charge_pC   for r in ref_readings]))
        dut_amp  = float(np.mean([r.amplitude_V for r in dut_results]))
        dut_chg  = float(np.mean([r.charge_pC   for r in dut_results]))
        baseline = float(np.mean([r.baseline_rms_V for r in dut_results]))

        dut_chg_norm = normalise(dut_chg, ref_chg)

        # Average drift time (None if no valid measurements)
        drift_vals  = [r.drift_time_s  for r in dut_results if r.drift_time_s  is not None]
        rise_vals   = [r.rise_time_s   for r in dut_results if r.rise_time_s   is not None]
        cfd_vals    = [r.cfd_time_s    for r in dut_results if r.cfd_time_s    is not None]
        onset_vals  = [r.onset_time_s  for r in dut_results if r.onset_time_s  is not None]
        drift_time_s: float | None = float(np.mean(drift_vals))  if drift_vals  else None
        rise_time_s:  float | None = float(np.mean(rise_vals))   if rise_vals   else None
        cfd_time_s:   float | None = float(np.mean(cfd_vals))    if cfd_vals    else None
        onset_time_s: float | None = float(np.mean(onset_vals))  if onset_vals  else None

        last_ref = ref_readings[-1]
        last_dut = dut_results[-1]

        # Measured per-point context (not recomputable offline) — best-effort.
        bias_v = bias_i = None
        try:
            br = dev.bias_supply.read()
            bias_v, bias_i = float(br.voltage_V), float(br.current_A)
        except Exception:
            pass
        sc_snapshot = self._read_slow_control_snapshot()

        # Absolute-charge calibration (no-op until a calibration is configured).
        dut_chg_cal, chg_units = self._apply_charge_calibration(dut_chg)

        return ScanResult(
            point=point,
            timestamp=time.time(),
            ref_amplitude_V=ref_amp,
            ref_charge_pC=ref_chg,
            dut_amplitude_V=dut_amp,
            dut_charge_pC=dut_chg,
            dut_charge_norm=dut_chg_norm,
            baseline_rms_V=baseline,
            drift_time_s=drift_time_s,
            rise_time_s=rise_time_s,
            cfd_time_s=cfd_time_s,
            onset_time_s=onset_time_s,
            camera_frame=frame,
            ref_waveform=last_ref.waveform_V,
            dut_waveform=last_dut.waveform_V,
            time_axis=last_dut.time_s,
            bias_voltage_V=bias_v,
            bias_current_A=bias_i,
            slow_control=sc_snapshot,
            dut_charge_cal=dut_chg_cal,
            charge_units=chg_units,
        )

    def _read_slow_control_snapshot(self) -> dict | None:
        """Return {channel_name: value} from the slow-control manager, or None."""
        try:
            readings = self._dev.slow_control.read_all()
        except Exception:
            return None
        snap: dict[str, float] = {}
        for name, reading in readings.items():
            val = getattr(reading, "value", reading)
            try:
                snap[name] = float(val)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        return snap or None

    def _apply_charge_calibration(self, dut_charge_pC: float):
        """Map raw integrated charge to a calibrated value + units.

        Returns (calibrated_value, units) or (None, None) when no calibration is
        configured.  The calibration object lives on the DeviceManager (set up
        from the ``charge_calibration`` config block); absent until Phase 3 wiring.
        """
        cal = getattr(self._dev, "charge_calibration", None)
        if cal is None:
            return None, None
        try:
            return cal.apply(dut_charge_pC)
        except Exception:
            return None, None
