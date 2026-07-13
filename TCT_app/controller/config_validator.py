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

import math
from dataclasses import dataclass
from typing import Any

# Single source of truth for the slow-control channel-name → capability_id
# mapping is capabilities/model.py (§5.1.1); we CALL it, never re-derive it.
# Layer ruling: capabilities/ is a pure stdlib-only leaf and the spec (§2,
# capabilities/__init__.py) states "controller/ may import capabilities/, never
# the reverse" — so this downward import is sanctioned; test_layer_contracts.py
# does not track capabilities/ as a layer, so nothing forbids it either.
from capabilities.model import slow_control_capability_id

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
        # simulated backend only (see _check_bias): how many HV channels the
        # FAKE supply reports.  Real backends report their own count.
        "sim_channel_count",
    },
    "waveform_generator": {
        "visa_address", "vendor", "frequency_hz", "pulse_width_s",
        "amplitude_V", "offset_V", "output_load", "output_channel",
        "timeout_ms", "simulation",
        # Opt-in explicit square rails (unipolar 0→+V trigger).  Absent → the
        # driver keeps the legacy bipolar amplitude+offset path.
        "level_low_V", "level_high_V",
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
    _check_waveform(cfg.get("waveform_generator") or {}, issues)
    _check_analysis(cfg.get("analysis") or {}, issues)
    _check_slow_control(cfg.get("slow_control") or {}, issues)
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
    _check_bias_channels(bias, issues)


# How many channels the *simulated* supply may pretend to have.  Not a hardware
# limit — a sanity ceiling: the largest iseg HV modules the lab could plausibly
# fake are 16-channel, and one GUI tab per channel stops being usable long before
# that.  A bigger number is a typo (e.g. a voltage pasted into the wrong key), and
# a typo that silently spawns 2000 HV channel views is worth failing on.
_MAX_SIM_BIAS_CHANNELS = 16


def _check_bias_channels(bias: dict[str, Any], issues: list[ConfigIssue]) -> None:
    """Validate the primary channel INDEX (``channel``) and the SIMULATION-ONLY
    channel COUNT (``sim_channel_count``), plus their interaction.

    ``channel``            — primary HV channel index (0-based).  Consumed by the
                             iseg backend and by the simulated backend; the real
                             single-channel backends ignore it.
    ``sim_channel_count``  — how many channels the SIMULATED supply reports.
                             **Simulation only** (``backend: simulated``).  On real
                             hardware the count is whatever the module reports
                             (iseg: ``:READ:MODULE:CHANNELNUMBER?``); a config file
                             may not claim it, so the key is WARNED as ignored on
                             any other backend — including ``simulation: true`` on
                             a real backend, whose driver reports 1 by fallback.

    Interaction: for the simulated backend both are known here, so
    ``channel >= sim_channel_count`` is a hard ERROR — the primary channel would
    address a channel the supply does not expose, and DeviceManager would then
    show a phantom extra tab (refresh_bias_channels appends the out-of-range
    primary so ``bias_supply`` never vanishes from the list).  HV channel identity
    must never be a guess.
    """
    sec = "bias_supply"
    # Mirror DeviceManager's default: an absent backend key means "simulated".
    backend = str(bias.get("backend", "simulated")).lower()
    is_sim_backend = backend == "simulated"

    count = bias.get("sim_channel_count")
    count_ok = False
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int):
            issues.append(ConfigIssue(
                ERROR, sec,
                f"sim_channel_count must be an integer >= 1 (got {count!r}) — it "
                "is the number of HV channels the SIMULATED supply reports."))
        elif count < 1:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"sim_channel_count must be >= 1 (got {count!r}) — a supply with "
                "no channels cannot be controlled."))
        elif count > _MAX_SIM_BIAS_CHANNELS:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"sim_channel_count = {count} exceeds the sanity ceiling of "
                f"{_MAX_SIM_BIAS_CHANNELS} — that is a typo, not a supply."))
        else:
            count_ok = True
            if not is_sim_backend:
                issues.append(ConfigIssue(
                    WARNING, sec,
                    f"sim_channel_count = {count} is IGNORED with backend: "
                    f"{backend} — it is a simulation-only knob. On a real "
                    "backend (even with simulation: true) the channel count "
                    "comes from the hardware, not from this file."))

    ch = bias.get("channel")
    ch_ok = False
    if ch is not None:
        if isinstance(ch, bool) or not isinstance(ch, int) or ch < 0:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"channel must be an integer >= 0 (got {ch!r}) — it is the "
                "PRIMARY channel INDEX, not a channel count."))
        else:
            ch_ok = True

    # Both individually valid → check the pair (simulated backend only: it is the
    # only case where the channel count is knowable from the config).
    if is_sim_backend and ch_ok:
        n = count if count_ok else 1
        if int(ch) >= n:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"channel = {ch} (the primary channel INDEX) is outside the "
                f"{n} channel(s) the simulated supply exposes (valid: "
                f"0..{n - 1}). Set sim_channel_count >= {int(ch) + 1}, or pick a "
                "primary channel that exists."))


def _check_waveform(wfg: dict[str, Any], issues: list[ConfigIssue]) -> None:
    """Validate the opt-in unipolar square rails (level_low_V / level_high_V).

    These map to the driver's ``set_levels()`` path (SCPI ``:VOLTage:HIGH`` /
    ``:VOLTage:LOW``) for a clean 0→+V trigger.  Absent → the driver keeps the
    legacy bipolar amplitude+offset path (the safe, manual-confirmed default),
    so there is nothing to check.  When used they must be:
      * both present (a lone key silently reverts to the bipolar path — a
        surprise), and
      * numeric with ``low < high`` (the driver's set_levels() raises otherwise,
        which would abort at connect-time — catch it here, before hardware).
    """
    if not wfg:
        return
    sec = "waveform_generator"
    low = wfg.get("level_low_V")
    high = wfg.get("level_high_V")
    if low is None and high is None:
        return  # legacy bipolar default — nothing to validate.
    if (low is None) != (high is None):
        present, missing = (("level_low_V", "level_high_V") if high is None
                            else ("level_high_V", "level_low_V"))
        issues.append(ConfigIssue(
            ERROR, sec,
            f"{present} is set but {missing} is not — the unipolar rail path "
            f"needs BOTH (a lone key silently reverts to the bipolar "
            f"amplitude+offset path). Set {missing} too, or remove {present}."))
        return
    if not (_is_num(low) and _is_num(high)):
        issues.append(ConfigIssue(
            ERROR, sec,
            f"level_low_V / level_high_V must be numeric "
            f"(got {low!r} / {high!r})."))
        return
    if not (math.isfinite(float(low)) and math.isfinite(float(high))):
        # YAML `.nan`/`.inf` pass the numeric check but every comparison with
        # NaN is False — it would silently bypass the low < high guard below
        # AND the driver's own set_levels() rejection. Refuse it here.
        issues.append(ConfigIssue(
            ERROR, sec,
            f"level_low_V / level_high_V must be finite numbers "
            f"(got {low!r} / {high!r})."))
        return
    if float(low) >= float(high):
        issues.append(ConfigIssue(
            ERROR, sec,
            f"level_low_V ({low}) must be < level_high_V ({high}) — the square "
            "rail low must sit below the high (the driver's set_levels() rejects "
            "high <= low)."))


# Per-channel keys under slow_control.channels.  The threshold keys (all
# optional) feed the runtime WARN/ALARM excursion policy in scan_controller; the
# tuning keys feed the simulated backend.  Unknown keys are WARNED (typo
# detection), matching the section idiom.
_SLOW_CONTROL_CHANNEL_KEYS = {
    "name", "unit", "backend",
    "warn_low", "warn_high", "alarm_low", "alarm_high",
    # simulated backend tuning
    "nominal", "noise", "drift_amplitude", "drift_period_s",
}
_SLOW_CONTROL_THRESHOLD_KEYS = ("warn_low", "warn_high", "alarm_low", "alarm_high")


def _check_slow_control(sc: dict[str, Any], issues: list[ConfigIssue]) -> None:
    """Validate per-channel slow-control alarm thresholds AND channel names.

    Thresholds are all OPTIONAL, but when present they must be numeric and
    correctly ORDERED so the alarm band sits OUTSIDE the warn band — otherwise
    ``AlarmThresholds.evaluate`` (which checks alarm before warn) would fire an
    ALARM before the value ever reads WARN, so the excursion policy would abort
    where it should only safe-hold.  Fail closed on a contradiction (ERROR).

    Channel NAMES (§5.1.1): every ``name`` becomes a PERMANENT capability_id via
    :func:`capabilities.model.slow_control_capability_id` (the shared source of
    truth).  A name that is neither one of the four grandfathered shipped names
    nor charset-conforming (``[a-z][a-z0-9_]*``), or that collides with a
    grandfathered alias target, is refused there (``ValueError``) → ERROR here.
    Two channels that would map to the SAME id (including a literal duplicate
    name) are also an ERROR — one id must never be claimed by two channels.
    """
    if not sc:
        return
    sec = "slow_control"
    channels = sc.get("channels")
    if channels is None:
        return
    if not isinstance(channels, list):
        issues.append(ConfigIssue(
            ERROR, sec, f"channels must be a list (got {type(channels).__name__})"))
        return

    seen_ids: dict[str, str] = {}  # capability_id → the channel name that claimed it
    for i, ch in enumerate(channels):
        if not isinstance(ch, dict):
            issues.append(ConfigIssue(
                ERROR, sec, f"channel[{i}] must be a mapping (got "
                            f"{type(ch).__name__})"))
            continue
        raw_name = ch.get("name")
        name = raw_name if isinstance(raw_name, str) else f"[{i}]"

        # Typo detection on per-channel keys (the top-level section is covered by
        # _check_unknown_keys; the per-channel dict is validated here).
        for key in ch:
            if key not in _SLOW_CONTROL_CHANNEL_KEYS:
                issues.append(ConfigIssue(
                    WARNING, sec,
                    f"channel '{name}': unknown key '{key}' — typo? It is ignored "
                    "by the code."))

        # Channel-name → permanent capability_id (§5.1.1). Only string names are
        # checked here; a missing/non-string name is a separate concern the
        # capability layer/manager surfaces, not a naming-grammar violation.
        if isinstance(raw_name, str):
            try:
                cap_id = slow_control_capability_id(raw_name)
            except ValueError as exc:
                # str(exc) already names the channel, the rule, cites the
                # PERMANENT capability_id and spec §5.1.1 (charset failure) or
                # the alias-target collision — reuse it verbatim (one source).
                issues.append(ConfigIssue(ERROR, sec, str(exc)))
            else:
                prior = seen_ids.get(cap_id)
                if prior is None:
                    seen_ids[cap_id] = raw_name
                elif prior == raw_name:
                    issues.append(ConfigIssue(
                        ERROR, sec,
                        f"channel '{raw_name}' is declared more than once — "
                        "slow-control channel names must be UNIQUE (each becomes "
                        f"the permanent capability_id {cap_id!r}, spec §5.1.1). "
                        "Remove or rename the duplicate."))
                else:
                    issues.append(ConfigIssue(
                        ERROR, sec,
                        f"channel '{raw_name}' maps to capability_id {cap_id!r}, "
                        f"already claimed by channel '{prior}' — two slow-control "
                        "channels must never share one permanent capability_id "
                        "(spec §5.1.1). Rename one of them."))

        thr: dict[str, float] = {}
        for key in _SLOW_CONTROL_THRESHOLD_KEYS:
            v = ch.get(key)
            if v is None:
                continue
            if not _is_num(v) or not math.isfinite(float(v)):
                issues.append(ConfigIssue(
                    ERROR, sec,
                    f"channel '{name}': {key} must be a finite number (got {v!r})"))
            else:
                thr[key] = float(v)

        wl, wh = thr.get("warn_low"), thr.get("warn_high")
        al, ah = thr.get("alarm_low"), thr.get("alarm_high")
        if wl is not None and wh is not None and wl > wh:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"channel '{name}': warn_low ({wl:g}) > warn_high ({wh:g}) — the "
                "WARN band is inverted."))
        if al is not None and ah is not None and al > ah:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"channel '{name}': alarm_low ({al:g}) > alarm_high ({ah:g}) — the "
                "ALARM band is inverted."))
        if ah is not None and wh is not None and ah < wh:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"channel '{name}': alarm_high ({ah:g}) < warn_high ({wh:g}) — the "
                "high alarm would trip before the high warn (alarm is checked "
                "first). Set alarm_high >= warn_high."))
        if al is not None and wl is not None and al > wl:
            issues.append(ConfigIssue(
                ERROR, sec,
                f"channel '{name}': alarm_low ({al:g}) > warn_low ({wl:g}) — the "
                "low alarm would trip before the low warn (alarm is checked "
                "first). Set alarm_low <= warn_low."))


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
