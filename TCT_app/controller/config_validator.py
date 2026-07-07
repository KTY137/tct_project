"""
Sanity checks for configs/devices.yaml.

Run by DeviceManager at load time; errors block connect_all(), warnings go to
the log.  The goal is to catch configuration contradictions *before* they
reach hardware — wrong firmware dialect vs. limit sign convention, ignored
keys, typos — instead of failing silently mid-scan.

The checks are deliberately settings-agnostic: they validate internal
consistency (signs, ranges, key spelling), never specific machines, so any
motor/config revamp keeps working as long as it stays self-consistent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class ConfigIssue:
    severity: str    # ERROR | WARNING
    section: str     # devices.yaml top-level key
    message: str

    def __str__(self) -> str:
        return f"[{self.section}] {self.message}"


# Known keys per section — unknown keys are warned about (typo detection).
# Keep in sync with the constructor kwargs in controller/device_manager.py and
# the ``from_config()`` factories the manager delegates to (InfluxWriter,
# SaveOptions, ChargeCalibration, SlowControlManager).
#
# Only each section's TOP-LEVEL keys are listed/checked; nested mappings (e.g.
# motor_stage.software_limits, output.save, charge_calibration.reference,
# slow_control.channels) are validated by their own consumers, not typo-checked
# here — matching the existing motor_stage idiom.
_KNOWN_KEYS: dict[str, set[str]] = {
    "oscilloscope": {
        "backend", "simulation", "n_averages",
        # visa backend
        "visa_address", "vendor", "timeout_ms", "n_channels",
        "trigger_source", "trigger_level_V", "trigger_slope",
        # drs4 backend
        "frequency_ghz", "voltage_range", "trigger_edge", "trigger_delay_ns",
        "time_correction", "t0_ns", "t0_threshold_V", "timeout_s",
        # tek_fastframe backend (vendored Dustin MSO5204B toolkit)
        "model", "trigger_channel", "trigger_type", "trigger_mode",
        "timescale_s", "vertical_scale_V", "waveform_position",
        "waveform_channel", "acquisition_mode", "sample_rate_hz",
        "record_length", "num_frames", "num_waveforms",
        "average_number", "avg_timeout_s",
    },
    "motor_stage": {
        "backend", "model", "simulation", "serial_port", "baudrate",
        "feed_rate_mm_min", "marlin", "poll_interval_s", "home_to_center",
        "steps_per_mm", "microsteps", "snap_mode", "push_steps_to_grbl",
        "software_limits",
        # pi backend
        "controller", "axes", "velocity",
    },
    "intensity_monitor": {
        "backend", "channel", "termination_ohm", "saturation_frac",
        "charge_integration_window_s",
    },
    "bias_supply": {
        "backend", "simulation", "compliance_A", "voltage_range_V",
        "timeout_ms", "visa_address",
        # iseg
        "host", "port", "channel", "ramp_speed_V_s",
        # e4control
        "e4c_device", "connection_type", "ramp_step_V", "ramp_delay_s",
    },
    "waveform_generator": {
        "visa_address", "vendor", "frequency_hz", "pulse_width_s",
        "amplitude_V", "offset_V", "output_load", "output_channel",
        "timeout_ms", "simulation",
    },
    "analysis": {
        "termination_ohm", "integration_window_s", "baseline_samples",
        "cfd_fraction", "onset_threshold_fraction",
    },
    # BlackflyCamera kwargs (device_manager.py).
    "camera": {
        "serial_number", "exposure_us", "gain_db", "pixel_format",
        "gamma_enabled", "gamma_value", "binning", "fps", "simulation",
    },
    # LaserManualMetadata kwargs (device_manager.py).
    "laser": {
        "wavelength_nm", "repetition_mode", "repetition_frequency_hz",
    },
    # Top-level slow-control keys; the per-channel dicts under 'channels' are
    # built by SlowControlManager.from_config (controller/slow_control_manager.py)
    # and are not typo-checked here.
    "slow_control": {
        "poll_interval_s", "channels",
    },
    # InfluxWriter.from_config (data/influx_writer.py). 'measurement' is read by
    # the code but is not present in the shipped devices.yaml.
    "influx": {
        "enabled", "url", "token", "org", "bucket", "measurement",
    },
    # Output/data-saving; the nested 'save' dict is consumed by
    # SaveOptions.from_config (data/save_options.py).
    "output": {
        "data_dir", "save",
    },
    # ChargeCalibration.from_config (analysis/charge_calibration.py); the nested
    # 'reference' dict is validated there, not typo-checked here.
    "charge_calibration": {
        "method", "termination_ohm", "amp_gain", "transimpedance_ohm",
        "output_units", "reference",
    },
}

_VISA_ONLY_SCOPE_KEYS = {"visa_address", "vendor", "timeout_ms", "trigger_slope"}
_DRS4_ONLY_SCOPE_KEYS = {"frequency_ghz", "trigger_edge", "trigger_delay_ns",
                         "time_correction", "t0_ns", "t0_threshold_V", "timeout_s"}


def validate_config(cfg: dict[str, Any]) -> list[ConfigIssue]:
    """Validate a parsed devices.yaml dict; returns issues (may be empty)."""
    issues: list[ConfigIssue] = []
    if not isinstance(cfg, dict):
        return [ConfigIssue(ERROR, "root", "devices.yaml did not parse to a mapping")]

    _check_unknown_keys(cfg, issues)
    _check_motor(cfg.get("motor_stage") or {}, issues)
    _check_scope(cfg.get("oscilloscope") or {}, issues)
    _check_bias(cfg.get("bias_supply") or {}, issues)
    _check_analysis(cfg.get("analysis") or {}, issues)
    return issues


def errors(issues: list[ConfigIssue]) -> list[str]:
    return [str(i) for i in issues if i.severity == ERROR]


def warnings(issues: list[ConfigIssue]) -> list[str]:
    return [str(i) for i in issues if i.severity == WARNING]


# ---------------------------------------------------------------------- #
# Section checks                                                          #
# ---------------------------------------------------------------------- #

def _check_unknown_keys(cfg: dict[str, Any], issues: list[ConfigIssue]) -> None:
    for section, known in _KNOWN_KEYS.items():
        block = cfg.get(section)
        if not isinstance(block, dict):
            continue
        for key in block:
            if key not in known:
                issues.append(ConfigIssue(
                    WARNING, section,
                    f"unknown key '{key}' — typo? It is ignored by the code."))


def _check_motor(motor: dict[str, Any], issues: list[ConfigIssue]) -> None:
    if not motor:
        return
    sec = "motor_stage"

    feed = motor.get("feed_rate_mm_min")
    if feed is not None and (not _is_num(feed) or float(feed) <= 0):
        issues.append(ConfigIssue(ERROR, sec,
                                  f"feed_rate_mm_min must be > 0 (got {feed!r})"))

    lim = motor.get("software_limits") or {}
    axes_ok = True
    for ax in ("x", "y", "z"):
        lo, hi = lim.get(f"{ax}_min_mm"), lim.get(f"{ax}_max_mm")
        if lo is None or hi is None:
            continue
        if not (_is_num(lo) and _is_num(hi)):
            issues.append(ConfigIssue(ERROR, sec,
                                      f"software_limits {ax}: non-numeric bound"))
            axes_ok = False
        elif float(lo) > float(hi):
            # The exact class of bug that shipped: min=300, max=0 makes
            # 'min <= pos <= max' false for EVERY position, so all moves are
            # silently refused.  Name the axis and both values, and say why.
            issues.append(ConfigIssue(
                ERROR, sec,
                f"software_limits {ax}: min ({lo}) > max ({hi}) — bounds are "
                f"SWAPPED, so '{ax}_min_mm <= pos <= {ax}_max_mm' is false for "
                "EVERY position and all moves are refused. Swap the two values."))
            axes_ok = False
        elif float(lo) == float(hi):
            issues.append(ConfigIssue(
                ERROR, sec,
                f"software_limits {ax}: min == max == {lo} — a ZERO-WIDTH "
                f"envelope leaves only one reachable point on {ax.upper()}; "
                f"widen {ax}_min_mm / {ax}_max_mm."))
            axes_ok = False

    # Firmware dialect vs. limit sign convention.  GRBL homes to machine 0 with
    # a NEGATIVE work envelope; Marlin homes to 0 with a POSITIVE one.  A
    # mismatch sends out-of-range G-code to the controller (moves rejected or,
    # worse, the display desyncs from the hardware).
    marlin = motor.get("marlin")
    if marlin is not None and axes_ok and lim:
        maxima = [lim.get(f"{ax}_max_mm") for ax in ("x", "y", "z")]
        minima = [lim.get(f"{ax}_min_mm") for ax in ("x", "y", "z")]
        maxima = [float(v) for v in maxima if _is_num(v)]
        minima = [float(v) for v in minima if _is_num(v)]
        if bool(marlin) and maxima and all(v <= 0 for v in maxima):
            issues.append(ConfigIssue(
                ERROR, sec,
                "marlin: true but software_limits describe a NEGATIVE envelope "
                "(all *_max_mm <= 0) — that is GRBL's post-homing convention. "
                "Marlin machines use positive coordinates (e.g. 0…300). "
                "Fix either 'marlin' or 'software_limits'."))
        if not bool(marlin) and minima and all(v >= 0 for v in minima) \
                and motor.get("backend", "").lower() == "grbl":
            issues.append(ConfigIssue(
                WARNING, sec,
                "marlin: false with an all-positive limits envelope — standard "
                "GRBL homes into a negative machine envelope (0 → -travel). "
                "Only correct if your GRBL is configured for positive space."))

    if bool(marlin) and motor.get("push_steps_to_grbl"):
        issues.append(ConfigIssue(
            WARNING, sec,
            "push_steps_to_grbl: true is IGNORED under marlin: true — $100-$102 "
            "are GRBL settings and Marlin stores steps/mm via M92. To silence "
            "this, set push_steps_to_grbl: false; only set marlin: false if the "
            "controller really runs GRBL (auto-detect at connect confirms which)."))
    if bool(marlin) and str(motor.get("snap_mode", "off")).lower() == "off" \
            and "steps_per_mm" in motor and not motor.get("push_steps_to_grbl"):
        issues.append(ConfigIssue(
            WARNING, sec,
            "steps_per_mm has no effect (marlin: true, snap_mode: off)."))


def _check_scope(scope: dict[str, Any], issues: list[ConfigIssue]) -> None:
    if not scope:
        return
    sec = "oscilloscope"
    # Channel count: a whole number in 1–8 (no real bench scope has more).  A
    # bad value isn't fatal — the driver falls back to *IDN? detection / its
    # default 4 — so this is a WARNING, matching the section's value-check idiom.
    n_ch = scope.get("n_channels")
    if n_ch is not None and (not _is_num(n_ch) or float(n_ch) != int(n_ch)
                             or not 1 <= int(n_ch) <= 8):
        issues.append(ConfigIssue(
            WARNING, sec,
            f"n_channels should be an integer 1–8 (got {n_ch!r}); the driver "
            "will use its *IDN?-detected or default channel count instead."))
    backend = str(scope.get("backend", "visa")).lower()
    if backend == "visa":
        stray = _DRS4_ONLY_SCOPE_KEYS & set(scope)
        if stray:
            issues.append(ConfigIssue(
                WARNING, sec,
                f"keys {sorted(stray)} apply to the drs4 backend and are "
                "ignored with backend: visa (the visa key is 'trigger_slope')."))
        if not scope.get("simulation") and not scope.get("visa_address"):
            issues.append(ConfigIssue(ERROR, sec,
                                      "backend: visa without visa_address "
                                      "(set simulation: true or an address)"))
    elif backend == "drs4":
        if "trigger_slope" in scope:
            issues.append(ConfigIssue(
                WARNING, sec,
                "'trigger_slope' is the visa-backend key; the drs4 backend "
                "reads 'trigger_edge' — your setting is ignored."))
    elif backend == "tek_fastframe":
        if not scope.get("simulation") and not scope.get("visa_address"):
            issues.append(ConfigIssue(ERROR, sec,
                                      "backend: tek_fastframe without visa_address "
                                      "(set simulation: true or an address)"))
        stray = _DRS4_ONLY_SCOPE_KEYS & set(scope)
        if stray:
            issues.append(ConfigIssue(
                WARNING, sec,
                f"keys {sorted(stray)} apply to the drs4 backend and are "
                "ignored with backend: tek_fastframe."))


def _check_bias(bias: dict[str, Any], issues: list[ConfigIssue]) -> None:
    if not bias:
        return
    sec = "bias_supply"
    comp = bias.get("compliance_A")
    if comp is not None and (not _is_num(comp) or float(comp) <= 0):
        issues.append(ConfigIssue(ERROR, sec,
                                  f"compliance_A must be > 0 (got {comp!r})"))
    rng = bias.get("voltage_range_V")
    if rng is not None and (not _is_num(rng) or float(rng) < 0):
        issues.append(ConfigIssue(ERROR, sec,
                                  f"voltage_range_V must be >= 0 (got {rng!r})"))
    ramp = bias.get("ramp_speed_V_s")
    if ramp is not None and _is_num(ramp) and float(ramp) > 200:
        issues.append(ConfigIssue(WARNING, sec,
                                  f"ramp_speed_V_s = {ramp} V/s is very fast for "
                                  "a silicon sensor — intentional?"))


def _check_analysis(analysis: dict[str, Any], issues: list[ConfigIssue]) -> None:
    if not analysis:
        return
    sec = "analysis"
    win = analysis.get("integration_window_s")
    if win is not None:
        ok = (isinstance(win, (list, tuple)) and len(win) == 2
              and all(_is_num(v) for v in win) and float(win[0]) < float(win[1]))
        if not ok:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"integration_window_s must be [t_start, t_end] with "
                f"t_start < t_end (got {win!r})"))
    term = analysis.get("termination_ohm")
    if term is not None and (not _is_num(term) or float(term) <= 0):
        issues.append(ConfigIssue(ERROR, sec,
                                  f"termination_ohm must be > 0 (got {term!r})"))
    frac = analysis.get("cfd_fraction")
    if frac is not None and (not _is_num(frac) or not 0.0 < float(frac) < 1.0):
        issues.append(ConfigIssue(ERROR, sec,
                                  f"cfd_fraction must be in (0, 1) (got {frac!r})"))
    nbase = analysis.get("baseline_samples")
    if nbase is not None and (not _is_num(nbase) or int(nbase) < 2):
        issues.append(ConfigIssue(ERROR, sec,
                                  f"baseline_samples must be >= 2 (got {nbase!r})"))


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)
