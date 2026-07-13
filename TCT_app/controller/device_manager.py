"""
Device manager — owns all device instances and provides a single
connect/disconnect/status interface for the GUI.

Reads hardware selection from configs/devices.yaml so the GUI never
imports a concrete device driver directly.  Swap motor or intensity
monitor by changing devices.yaml — no code changes needed.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from devices.motor_base import MotorStageBase, SoftwareLimits
from devices.motor_grbl import GRBLMotorStage
from devices.motor_pi import PIMotorStage
from devices.motor_simulated import SimulatedMotorStage
from devices.printer_presets import get_preset
from devices.intensity_base import IntensityMonitorBase
from devices.intensity_scope_ch import ScopeChannelMonitor
from devices.intensity_simulated import SimulatedIntensityMonitor
from devices.oscilloscope import Oscilloscope
from devices.oscilloscope_drs4 import DRS4Oscilloscope
from devices.oscilloscope_tek_fastframe import TekFastFrameOscilloscope
from devices.waveform_generator import WaveformGenerator
from devices.camera_blackfly import BlackflyCamera
from devices.laser_manual import LaserManualMetadata
from devices.bias_supply_base import BiasSupplyBase
from devices.bias_channel import BiasChannel
from devices.bias_supply_keithley import KeithleyBiasSupply
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.bias_supply_e4control import E4ControlBiasSupply
from devices.bias_supply_iseg import IsegBiasSupply
from controller.slow_control_manager import SlowControlManager
from controller import config_validator
from data.influx_writer import InfluxWriter
from data.save_options import SaveOptions
from analysis.charge_calibration import ChargeCalibration

logger = logging.getLogger(__name__)

# App root = the TCT_app directory (this file lives in TCT_app/controller/).
# Used to anchor relative output paths so the data location does not depend on
# the current working directory the app was launched from.
_APP_ROOT = Path(__file__).parent.parent

# Registry for motor stage backends.
# Add new entries here when a new motor driver is created.
MOTOR_BACKENDS: dict[str, type[MotorStageBase]] = {
    "pi":        PIMotorStage,
    "grbl":      GRBLMotorStage,
    "simulated": SimulatedMotorStage,
}

# Registry for intensity monitor backends.
# Add new entries here when a new intensity-monitor driver is created.
INTENSITY_BACKENDS: dict[str, type[IntensityMonitorBase]] = {
    "scope_channel": ScopeChannelMonitor,
    "simulated":     SimulatedIntensityMonitor,
}

BIAS_BACKENDS: dict[str, type[BiasSupplyBase]] = {
    "keithley":   KeithleyBiasSupply,
    "e4control":  E4ControlBiasSupply,
    "iseg":       IsegBiasSupply,
    "simulated":  SimulatedBiasSupply,
}


def _load_cfg(path: str = "") -> dict[str, Any]:
    if not path:
        path = str(Path(__file__).parent.parent / "configs" / "devices.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.warning("devices.yaml not found — using simulation defaults")
        return {}


class DeviceManager:
    """
    Central registry for all hardware instances.

    Concrete driver selection is driven entirely by configs/devices.yaml:

        motor_stage:
          backend: "pi"          # or "simulated"
          ...

        intensity_monitor:
          backend: "scope_channel"  # or "simulated"
          ...

    The rest of the application only holds references to the abstract
    base classes (MotorStageBase, IntensityMonitorBase) so swapping
    the backend requires no code changes outside this class and the
    YAML config.
    """

    def __init__(self, config_path: str = "configs/devices.yaml") -> None:
        cfg = _load_cfg(config_path)

        # ── Config sanity checks ──────────────────────────────────────
        # Errors are surfaced here and block connect_all(); warnings are
        # logged so misconfigurations never fail silently.
        self.config_issues = config_validator.validate_config(cfg)
        for issue in self.config_issues:
            (logger.error if issue.severity == config_validator.ERROR
             else logger.warning)("Config check: %s", issue)

        # ── Oscilloscope ─────────────────────────────────────────────
        # backend: "visa"          → VISA/PyVISA oscilloscope (default)
        # backend: "drs4"          → PSI DRS4 evaluation board
        # backend: "tek_fastframe" → Tektronix MSO5204B FastFrame burst
        #                            (vendored Dustin toolkit)
        scope_cfg = cfg.get("oscilloscope", {})
        scope_backend = scope_cfg.get("backend", "visa").lower()
        if scope_backend == "tek_fastframe":
            self.scope = TekFastFrameOscilloscope(
                visa_address      = scope_cfg.get("visa_address", ""),
                timeout_ms        = scope_cfg.get("timeout_ms",        10000),
                trigger_channel   = scope_cfg.get("trigger_channel",   "CH4"),
                trigger_level_V   = scope_cfg.get("trigger_level_V",   -0.0116),
                trigger_type      = scope_cfg.get("trigger_type",      "EDGE"),
                trigger_mode      = scope_cfg.get("trigger_mode",      "NORMAL"),
                timescale_s       = scope_cfg.get("timescale_s",       10e-9),
                vertical_scale_V  = scope_cfg.get("vertical_scale_V",  0.008),
                waveform_position = scope_cfg.get("waveform_position", 0.0),
                waveform_channel  = scope_cfg.get("waveform_channel",  "CH4"),
                acquisition_mode  = scope_cfg.get("acquisition_mode",  "SAMPLE"),
                sample_rate_hz    = scope_cfg.get("sample_rate_hz",    10e9),
                record_length     = scope_cfg.get("record_length",     1000),
                num_frames        = scope_cfg.get("num_frames",        20000),
                average_number    = scope_cfg.get("average_number",    512),
                avg_timeout_s     = scope_cfg.get("avg_timeout_s",     30.0),
                simulation        = scope_cfg.get("simulation",        True),
            )
        elif scope_backend == "drs4":
            self.scope = DRS4Oscilloscope(
                frequency_ghz    = scope_cfg.get("frequency_ghz",   5.0),
                voltage_range    = scope_cfg.get("voltage_range",    0),
                trigger_source   = scope_cfg.get("trigger_source",   "EXT"),
                trigger_level_V  = scope_cfg.get("trigger_level_V",  -0.05),
                trigger_edge     = scope_cfg.get("trigger_edge",     "FALL"),
                trigger_delay_ns = scope_cfg.get("trigger_delay_ns", 150.0),
                n_averages       = scope_cfg.get("n_averages",       1),
                time_correction  = scope_cfg.get("time_correction",  True),
                t0_ns            = scope_cfg.get("t0_ns",            20.0),
                t0_threshold_V   = scope_cfg.get("t0_threshold_V",   -0.45),
                timeout_s        = scope_cfg.get("timeout_s",        2.0),
                simulation       = scope_cfg.get("simulation",       True),
            )
        else:
            self.scope = Oscilloscope(
                visa_address    = scope_cfg.get("visa_address", ""),
                vendor          = scope_cfg.get("vendor",       "tektronix"),
                n_averages      = scope_cfg.get("n_averages",   1),
                timeout_ms      = scope_cfg.get("timeout_ms",   10000),
                trigger_source  = scope_cfg.get("trigger_source",  "EXT"),
                trigger_level_V = scope_cfg.get("trigger_level_V", -0.41),
                trigger_slope   = scope_cfg.get("trigger_slope",   "FALL"),
                n_channels      = scope_cfg.get("n_channels"),
                simulation      = scope_cfg.get("simulation",   True),
            )

        # ── Motor stage (swappable via backend key) ────────────────────
        motor_cfg = cfg.get("motor_stage", {})
        motor_backend = motor_cfg.get("backend", "simulated").lower()
        motor_cls = MOTOR_BACKENDS.get(motor_backend)
        if motor_cls is None:
            raise ValueError(
                f"Unknown motor_stage backend '{motor_backend}'. "
                f"Available: {list(MOTOR_BACKENDS)}"
            )
        if motor_backend == "pi":
            self.motor: MotorStageBase = PIMotorStage(
                controller=motor_cfg.get("controller", "C-863"),
                serial_port=motor_cfg.get("serial_port", "COM3"),
                baudrate=motor_cfg.get("baudrate", 115200),
                axes=motor_cfg.get("axes", [1, 2, 3]),
                velocity_mm_s=motor_cfg.get("velocity", 5.0),
            )
        elif motor_backend == "grbl":
            # Printer preset (cr10s / ender3 / pi_stage / custom) supplies the
            # firmware dialect, feed rate, and software-limit defaults for the
            # selected machine.  Explicit YAML keys always win over the preset.
            preset = get_preset(motor_cfg.get("model"))
            self.motor = GRBLMotorStage(
                serial_port=motor_cfg.get("serial_port", "COM3"),
                baudrate=motor_cfg.get("baudrate", 115200),
                feed_rate_mm_min=motor_cfg.get("feed_rate_mm_min", preset.feed_rate_mm_min),
                marlin=motor_cfg.get("marlin", preset.marlin),
                home_to_center=motor_cfg.get("home_to_center", True),
                steps_per_mm=motor_cfg.get("steps_per_mm", 80.0),
                microsteps=motor_cfg.get("microsteps", 16),
                snap_mode=motor_cfg.get("snap_mode", "off"),
                push_steps_to_grbl=motor_cfg.get("push_steps_to_grbl", False),
                simulation=motor_cfg.get("simulation", True),
            )
            # Soft limits: start from the selected printer's build volume, then
            # let any per-axis keys in devices.yaml.software_limits override.
            # Falls back to 0–300 mm when no preset volume is defined (custom).
            base_limits = preset.limits or {
                "x_min_mm": 0.0, "x_max_mm": 300.0,
                "y_min_mm": 0.0, "y_max_mm": 300.0,
                "z_min_mm": 0.0, "z_max_mm": 300.0,
            }
            lim_cfg = {**base_limits, **(motor_cfg.get("software_limits") or {})}
            self.motor.limits = SoftwareLimits.from_config(lim_cfg)
        else:
            self.motor = SimulatedMotorStage()

        # ── Intensity monitor (swappable via backend key) ─────────────
        mon_cfg = cfg.get("intensity_monitor", {})
        mon_backend = mon_cfg.get("backend", "simulated").lower()
        mon_cls = INTENSITY_BACKENDS.get(mon_backend)
        if mon_cls is None:
            raise ValueError(
                f"Unknown intensity_monitor backend '{mon_backend}'. "
                f"Available: {list(INTENSITY_BACKENDS)}"
            )
        if mon_backend == "scope_channel":
            # Reuse the DUT waveform-analysis baseline-sample count
            # (analysis.baseline_samples) for the reference channel so both are
            # baseline-corrected identically.  Absent → the monitor's own default
            # (20), so legacy configs are unchanged.  No new config key — this
            # reuses the existing analysis: block, so config_validator is
            # untouched (Paul D4, option b).
            a_cfg = cfg.get("analysis", {}) or {}
            self.intensity_monitor: IntensityMonitorBase = ScopeChannelMonitor(
                scope=self.scope,
                channel=mon_cfg.get("channel", 1),
                termination_ohm=mon_cfg.get("termination_ohm", 50.0),
                saturation_frac=mon_cfg.get("saturation_frac", 0.95),
                integration_window_s=tuple(
                    mon_cfg.get("charge_integration_window_s", [20e-9, 150e-9])
                ),
                baseline_samples=int(a_cfg.get("baseline_samples", 20)),
            )
        else:
            self.intensity_monitor = SimulatedIntensityMonitor()

        # ── Remaining devices ─────────────────────────────────────────
        cam_cfg = cfg.get("camera", {})
        self.camera = BlackflyCamera(
            serial_number = cam_cfg.get("serial_number", ""),
            exposure_us   = cam_cfg.get("exposure_us",   5000.0),
            gain_db       = cam_cfg.get("gain_db",       0.0),
            pixel_format  = cam_cfg.get("pixel_format",  "Mono8"),
            gamma_enabled = cam_cfg.get("gamma_enabled", True),
            gamma_value   = cam_cfg.get("gamma_value",   1.0),
            binning       = cam_cfg.get("binning",       1),
            fps           = cam_cfg.get("fps",           10.0),
            simulation    = cam_cfg.get("simulation",    True),
        )

        wfg_cfg = cfg.get("waveform_generator", {})
        self.waveform_generator = WaveformGenerator(
            visa_address=wfg_cfg.get("visa_address", ""),
            frequency_hz=wfg_cfg.get("frequency_hz", 1000.0),
            pulse_width_s=wfg_cfg.get("pulse_width_s", 100e-9),
            amplitude_V=wfg_cfg.get("amplitude_V", 3.3),
            offset_V=wfg_cfg.get("offset_V", 0.0),
            output_load=wfg_cfg.get("output_load", "INFinity"),
            output_channel=wfg_cfg.get("output_channel", 1),
            # Optional explicit square rails (opt-in unipolar 0→+V trigger).
            # Absent → None → the driver keeps the legacy amplitude+offset
            # bipolar path unchanged (the safe, manual-confirmed default).
            level_low_V=wfg_cfg.get("level_low_V"),
            level_high_V=wfg_cfg.get("level_high_V"),
            vendor=wfg_cfg.get("vendor", "rigol"),
            timeout_ms=wfg_cfg.get("timeout_ms", 5000),
            simulation=wfg_cfg.get("simulation", True),
        )

        laser_cfg = cfg.get("laser", {})
        self.laser = LaserManualMetadata(
            wavelength_nm=laser_cfg.get("wavelength_nm", 660.0),
            repetition_mode=laser_cfg.get("repetition_mode", "external"),
            repetition_frequency_hz=laser_cfg.get("repetition_frequency_hz", 1000.0),
        )

        # ── Bias supply (swappable via backend key) ───────────────────
        bias_cfg = cfg.get("bias_supply", {})
        bias_backend = bias_cfg.get("backend", "simulated").lower()
        bias_cls = BIAS_BACKENDS.get(bias_backend)
        if bias_cls is None:
            raise ValueError(
                f"Unknown bias_supply backend '{bias_backend}'. "
                f"Available: {list(BIAS_BACKENDS)}"
            )
        if bias_backend == "keithley":
            bias_driver: BiasSupplyBase = KeithleyBiasSupply(
                visa_address=bias_cfg.get("visa_address", ""),
                compliance_A=bias_cfg.get("compliance_A", 100e-6),
                voltage_range_V=bias_cfg.get("voltage_range_V", 1100.0),
                timeout_ms=bias_cfg.get("timeout_ms", 10000),
                simulation=bias_cfg.get("simulation", False),
            )
        elif bias_backend == "iseg":
            bias_driver = IsegBiasSupply(
                host            = bias_cfg.get("host",            ""),
                port            = bias_cfg.get("port",            10001),
                channel         = bias_cfg.get("channel",         0),
                visa_address    = bias_cfg.get("visa_address",    ""),
                compliance_A    = bias_cfg.get("compliance_A",    10e-6),
                voltage_range_V = bias_cfg.get("voltage_range_V", 2000.0),
                ramp_speed_V_s  = bias_cfg.get("ramp_speed_V_s",  50.0),
                timeout_ms      = bias_cfg.get("timeout_ms",      5000),
                simulation      = bias_cfg.get("simulation",      False),
            )
        elif bias_backend == "e4control":
            bias_driver = E4ControlBiasSupply(
                e4c_device      = bias_cfg.get("e4c_device",       "K2410"),
                connection_type = bias_cfg.get("connection_type",  "gpib"),
                host            = bias_cfg.get("host",             "192.168.1.100"),
                port            = bias_cfg.get("port",             22),
                compliance_A    = bias_cfg.get("compliance_A",     100e-6),
                ramp_step_V     = bias_cfg.get("ramp_step_V",      10.0),
                ramp_delay_s    = bias_cfg.get("ramp_delay_s",     1.0),
                simulation      = bias_cfg.get("simulation",       False),
            )
        else:
            # SIMULATION-ONLY channel count.  ``sim_channel_count`` exists purely
            # so the multi-channel path (BiasChannel views, per-channel panels,
            # plan safety['bias_channel'], ALL-OFF) is reachable with no hardware
            # attached — the normal dev mode.  It is deliberately NOT read for the
            # iseg/keithley/e4control backends: on a real module the count is
            # whatever the hardware reports (iseg: :READ:MODULE:CHANNELNUMBER?),
            # never something a config file may claim.  Absent → 1 (byte-identical
            # to the historic bare SimulatedBiasSupply()).
            #
            # ``channel`` is the PRIMARY channel INDEX (same key, same meaning as
            # for the iseg backend), not a count; the validator rejects
            # channel >= sim_channel_count.
            bias_driver = SimulatedBiasSupply(
                channel       = bias_cfg.get("channel",           0),
                channel_count = bias_cfg.get("sim_channel_count", 1),
            )

        # One driver owns the transport; each HV channel is a BiasChannel view.
        # ``channel_count()`` needs a live link, so we start with a single
        # primary-channel list here (no hardware I/O in __init__) and rebuild it
        # after the driver connects via refresh_bias_channels().  The primary
        # channel proxy IS ``self.bias_supply`` so the existing single-channel
        # panel, scan controller, named_devices(), and liveness are unchanged.
        self._bias_driver: BiasSupplyBase = bias_driver
        self._bias_primary_ch: int = int(getattr(bias_driver, "_ch", 0))
        self.bias_supply = BiasChannel(bias_driver, self._bias_primary_ch)
        self.bias_channels: list[BiasChannel] = [self.bias_supply]

        # ── Slow-control channels (modular — add via devices.yaml) ────
        sc_cfg = cfg.get("slow_control", {})
        self.slow_control = SlowControlManager.from_config(sc_cfg)
        self._poll_interval_s: float = sc_cfg.get("poll_interval_s", 5.0)

        # ── Optional InfluxDB sink ─────────────────────────────────────
        self.influx = InfluxWriter.from_config(cfg.get("influx", {}))

        # ── Output / data-saving config ───────────────────────────────
        # Drives the run-directory location and which dataset groups the
        # HDF5 writer persists (see data/save_options.py).
        self.output_cfg: dict[str, Any] = cfg.get("output", {})
        self.save_options = SaveOptions.from_config(self.output_cfg.get("save", {}))

        # Keep the parsed config so a snapshot can be embedded in run metadata.
        self.raw_config: dict[str, Any] = cfg

        # ── Connection endpoints (for human-readable status / error text) ──
        # Maps the short device key used by connect_all() to the port / address
        # the device talks over, so error messages can name *where* a device is
        # rather than just "Disconnect error".  Pulled from the YAML so it stays
        # in sync with whatever the user configured.
        self._endpoints: dict[str, str] = {
            "scope":              scope_cfg.get("visa_address", "") or f"{scope_backend} backend",
            "motor":              str(motor_cfg.get("serial_port", "")) or f"{motor_backend} backend",
            "camera":             str(cam_cfg.get("serial_number", "")),
            "waveform_generator": wfg_cfg.get("visa_address", ""),
            "bias_supply":        bias_cfg.get("visa_address") or bias_cfg.get("host", "") or f"{bias_backend} backend",
            "intensity_monitor":  f"{mon_backend} backend",
        }

        # ── Charge calibration ────────────────────────────────────────
        # Maps the raw integrated charge to absolute pC / MIP-equivalent units
        # (see analysis/charge_calibration.py).  The scan controller calls
        # ``charge_calibration.apply()`` per point.
        #
        # The devices.yaml block holds the defaults; the calibration routine
        # writes results to a sidecar (configs/charge_calibration.yaml) so the
        # documented devices.yaml comments are never overwritten.  The sidecar,
        # when present, takes precedence.
        cal_cfg = dict(cfg.get("charge_calibration", {}) or {})
        if self.cal_sidecar_path.exists():
            try:
                cal_cfg = yaml.safe_load(
                    self.cal_sidecar_path.read_text(encoding="utf-8")
                ) or cal_cfg
            except Exception as exc:
                logger.warning("Could not read calibration sidecar: %s", exc)
        self.charge_calibration = ChargeCalibration.from_config(cal_cfg)

    def config_errors(self) -> list[str]:
        """Blocking config-validation errors (empty when the config is sane)."""
        return config_validator.errors(self.config_issues)

    def config_warnings(self) -> list[str]:
        return config_validator.warnings(self.config_issues)

    @property
    def analysis_kwargs(self) -> dict[str, Any]:
        """Waveform-analysis parameters from devices.yaml (``analysis:`` block).

        Passed by every ``analyse_waveform`` call site so the integration
        window / termination / thresholds are adjustable in config instead of
        hardcoded.  ``charge_calibration.termination_ohm`` is the fallback for
        the termination so older configs keep working.
        """
        a_cfg = dict(self.raw_config.get("analysis", {}) or {})
        cal_cfg = self.raw_config.get("charge_calibration", {}) or {}
        kwargs: dict[str, Any] = {}
        term = a_cfg.get("termination_ohm", cal_cfg.get("termination_ohm"))
        if term:
            kwargs["termination_ohm"] = float(term)
        win = a_cfg.get("integration_window_s")
        if isinstance(win, (list, tuple)) and len(win) == 2:
            kwargs["integration_window_s"] = (float(win[0]), float(win[1]))
        for key in ("baseline_samples", "cfd_fraction", "onset_threshold_fraction"):
            if key in a_cfg:
                kwargs[key] = (int(a_cfg[key]) if key == "baseline_samples"
                               else float(a_cfg[key]))
        return kwargs

    @property
    def cal_sidecar_path(self) -> Path:
        """Path of the calibration sidecar written by the Calibration panel."""
        return _APP_ROOT / "configs" / "charge_calibration.yaml"

    def config_snapshot(self) -> dict[str, Any]:
        """Return a copy of the loaded config for run metadata, with secrets redacted."""
        import copy
        snap = copy.deepcopy(self.raw_config)
        influx = snap.get("influx")
        if isinstance(influx, dict) and influx.get("token"):
            influx["token"] = "***redacted***"
        return snap

    @property
    def data_dir(self) -> Path:
        """Absolute directory that holds run_* folders.

        Resolved from ``output.data_dir`` in devices.yaml; relative paths are
        anchored to the app root so the location is independent of the current
        working directory the app was launched from.
        """
        raw = self.output_cfg.get("data_dir", "runs")
        p = Path(raw)
        if not p.is_absolute():
            p = _APP_ROOT / p
        return p

    # ------------------------------------------------------------------ #
    # Endpoint helpers (human-readable device location)                   #
    # ------------------------------------------------------------------ #

    # Display name (named_devices) → short key (connect_all / _endpoints).
    _DISPLAY_TO_SHORT = {
        "Motor Stage":        "motor",
        "Oscilloscope":       "scope",
        "Bias Supply":        "bias_supply",
        "Intensity Monitor":  "intensity_monitor",
        "Camera":             "camera",
        "Waveform Generator": "waveform_generator",
    }

    def endpoint(self, key: str) -> str:
        """Return the configured port/address for a device (short key or display name)."""
        key = self._DISPLAY_TO_SHORT.get(key, key)
        return self._endpoints.get(key, "")

    def _at(self, key: str) -> str:
        """' [COM3]'-style suffix for messages, or '' when no endpoint is known."""
        ep = self.endpoint(key)
        return f" [{ep}]" if ep else ""

    # ------------------------------------------------------------------ #
    # Bulk connect / disconnect                                           #
    # ------------------------------------------------------------------ #

    def connect_all(self) -> dict[str, str]:
        """
        Attempt to connect every device.  Returns a dict of
        device_name → "ok" | error message for status reporting.
        """
        errs = self.config_errors()
        if errs:
            raise ValueError(
                "devices.yaml has configuration errors — fix them before "
                "connecting:\n" + "\n".join(f"  • {e}" for e in errs)
            )
        results: dict[str, str] = {}
        devices = {
            "scope":             self.scope,
            "motor":             self.motor,
            "camera":            self.camera,
            "waveform_generator":self.waveform_generator,
            "bias_supply":       self.bias_supply,
        }
        for name, dev in devices.items():
            try:
                dev.connect()
                results[name] = "ok"
            except Exception as exc:
                results[name] = f"{exc}{self._at(name)}"
                logger.error("Connect failed for %s%s: %s", name, self._at(name), exc)

        # Now that the bias driver has a live link, enumerate its HV channels.
        # (channel_count() needs the connection; it is safe/1 in simulation.)
        self.refresh_bias_channels()

        # intensity monitor connects after scope
        try:
            self.intensity_monitor.connect()
            results["intensity_monitor"] = "ok"
        except Exception as exc:
            results["intensity_monitor"] = f"{exc}{self._at('intensity_monitor')}"
            logger.error("Connect failed for intensity_monitor%s: %s",
                         self._at("intensity_monitor"), exc)

        # slow-control channels
        sc_results = self.slow_control.connect_all()
        for name, status in sc_results.items():
            results[f"slow_control/{name}"] = status

        return results

    def refresh_bias_channels(self) -> list[BiasChannel]:
        """Rebuild ``self.bias_channels`` from the driver's channel count.

        Queries ``channel_count()`` on the shared bias driver (which needs a
        live link and returns 1 in simulation / on error) and builds one
        :class:`BiasChannel` per channel ``0 .. N-1``.  The primary-channel
        proxy object (``self.bias_supply``) is reused unchanged so any GUI
        panel already bound to it keeps working.  Never raises.

        Returns the new channel list.  Safe to call repeatedly.
        """
        drv = self._bias_driver
        try:
            n = int(drv.channel_count())
        except Exception as exc:
            logger.warning("bias channel_count() failed (%s) — assuming 1", exc)
            n = 1
        n = max(1, n)
        primary = self._bias_primary_ch

        channels: list[BiasChannel] = []
        for idx in range(n):
            if idx == primary:
                channels.append(self.bias_supply)      # reuse the primary proxy
            else:
                channels.append(BiasChannel(drv, idx))
        # If the configured primary index is outside 0..N-1 (unusual), keep it
        # so self.bias_supply always appears in the list.
        if primary not in range(n):
            channels.append(self.bias_supply)

        self.bias_channels = channels
        logger.info("Bias supply exposes %d channel(s); primary=CH%d",
                    len(channels), primary)
        return channels

    def disconnect_all(self) -> None:
        self.slow_control.disconnect_all()
        ordered = (
            ("intensity_monitor",  self.intensity_monitor),
            ("waveform_generator", self.waveform_generator),
            ("bias_supply",        self.bias_supply),
            ("camera",             self.camera),
            ("scope",              self.scope),
            ("motor",              self.motor),
        )
        for name, dev in ordered:
            try:
                dev.disconnect()
            except Exception as exc:
                logger.warning("Disconnect error on %s%s: %s", name, self._at(name), exc)
        self.influx.close()

    # ------------------------------------------------------------------ #
    # Per-device access (used by DeviceManagerWindow)                     #
    # ------------------------------------------------------------------ #

    def named_devices(self) -> dict[str, object]:
        """Return {name: device} for all individually controllable devices."""
        return {
            "Motor Stage":        self.motor,
            "Oscilloscope":       self.scope,
            "Bias Supply":        self.bias_supply,
            "Intensity Monitor":  self.intensity_monitor,
            "Camera":             self.camera,
            "Waveform Generator": self.waveform_generator,
        }

    def poll_liveness(self) -> dict[str, bool]:
        """Ask every device to verify its link (``BaseDevice.is_alive``).

        Returns {name: alive}; never raises.  Drivers without a cheap probe
        just report their connected flag, so this is safe to call on a timer
        (the gui.liveness.LivenessMonitor does, from a background thread).
        """
        out: dict[str, bool] = {}
        for name, dev in self.named_devices().items():
            try:
                out[name] = bool(dev.is_alive())
            except Exception as exc:
                logger.warning("Liveness check failed for %s: %s", name, exc)
                out[name] = False
        return out

    def connect_device(self, name: str) -> str:
        """Connect a single device by name. Returns 'ok' or error string."""
        devs = self.named_devices()
        if name not in devs:
            return f"Unknown device: {name}"
        try:
            devs[name].connect()
            return "ok"
        except Exception as exc:
            logger.error("Connect failed for %s%s: %s", name, self._at(name), exc)
            return f"{exc}{self._at(name)}"

    def disconnect_device(self, name: str) -> str:
        """Disconnect a single device by name. Returns 'ok' or error string."""
        devs = self.named_devices()
        if name not in devs:
            return f"Unknown device: {name}"
        try:
            devs[name].disconnect()
            return "ok"
        except Exception as exc:
            logger.error("Disconnect failed for %s%s: %s", name, self._at(name), exc)
            return f"{exc}{self._at(name)}"
