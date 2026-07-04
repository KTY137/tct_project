"""Waveform analysis for TCT signals.

Sign conventions
----------------
TCT pulses are usually *negative* going (electron signal into 50 Ω).  All
edge/threshold logic therefore works on the magnitude |v| after baseline
subtraction.  ``charge_pC`` keeps its physical sign (negative pulse →
negative charge); ``polarity`` reports the detected pulse direction so
consumers that need magnitudes (CCE, calibration) can use
``abs(charge_pC)`` explicitly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# numpy 2.x renamed trapz → trapezoid; support both.
_trapezoid = getattr(np, "trapezoid", np.trapz)

# Windows we already warned about (avoid one warning per waveform during scans).
_warned_windows: set[tuple[float, float]] = set()


@dataclass
class WaveformResult:
    amplitude_V:    float
    charge_pC:      float          # signed — see module docstring
    baseline_rms_V: float
    rise_time_s:    float | None
    cfd_time_s:     float | None
    # Pulse-edge timing (all on the scope time axis)
    onset_time_s:   float | None  # leading-edge crossing at onset_threshold_fraction * peak
    trailing_time_s: float | None  # trailing-edge crossing at the same fraction
    drift_time_s:   float | None  # trailing_time_s - onset_time_s  (= carrier drift time)
    time_s:         np.ndarray
    waveform_V:     np.ndarray
    polarity:       int = 0        # +1 positive pulse, -1 negative, 0 no signal


def analyse_waveform(
    time_s: np.ndarray,
    voltage_V: np.ndarray,
    termination_ohm: float = 50.0,
    baseline_samples: int = 20,
    cfd_fraction: float = 0.3,
    integration_window_s: tuple[float, float] = (20e-9, 150e-9),
    onset_threshold_fraction: float = 0.1,
) -> WaveformResult:
    """
    Extract key quantities from a single TCT waveform.

    Parameters
    ----------
    time_s, voltage_V:
        Waveform arrays (same length, at least ``baseline_samples + 2``).
    termination_ohm:
        Input termination used for charge integration.
    baseline_samples:
        Number of leading samples used for baseline estimation.
    cfd_fraction:
        Constant-fraction discriminator threshold (fraction of peak).
    integration_window_s:
        (t_start, t_end) for charge integration.

    Raises
    ------
    ValueError
        On empty / mismatched inputs — a silently-NaN result would otherwise
        propagate into saved data.
    """
    time_s = np.asarray(time_s, dtype=float)
    voltage_V = np.asarray(voltage_V, dtype=float)
    if time_s.ndim != 1 or voltage_V.ndim != 1:
        raise ValueError("analyse_waveform expects 1-D time/voltage arrays")
    if len(time_s) != len(voltage_V):
        raise ValueError(
            f"time ({len(time_s)}) and voltage ({len(voltage_V)}) lengths differ")
    if len(voltage_V) < max(int(baseline_samples), 2) + 2:
        raise ValueError(
            f"waveform too short ({len(voltage_V)} samples) for "
            f"baseline_samples={baseline_samples}")
    if termination_ohm <= 0:
        raise ValueError(f"termination_ohm must be > 0 (got {termination_ohm})")

    # Baseline (assumes the trigger delay puts the pulse after the first
    # baseline_samples — the pre-trigger region)
    baseline = float(np.mean(voltage_V[:baseline_samples]))
    baseline_rms = float(np.std(voltage_V[:baseline_samples]))
    corrected = voltage_V - baseline
    mag = np.abs(corrected)

    # Amplitude & polarity
    peak_idx = int(np.argmax(mag))
    amplitude = float(mag[peak_idx])
    polarity = int(np.sign(corrected[peak_idx])) if amplitude > 0 else 0

    # Charge (signed)
    t0, t1 = integration_window_s
    mask = (time_s >= t0) & (time_s <= t1)
    charge_pC = 0.0
    n_in_window = int(np.count_nonzero(mask))
    if n_in_window >= 2:
        charge_C = float(_trapezoid(corrected[mask], time_s[mask])) / termination_ohm
        charge_pC = charge_C * 1e12
    else:
        _warn_window_once(
            integration_window_s,
            f"integration window ({t0*1e9:.0f}–{t1*1e9:.0f} ns) contains "
            f"{n_in_window} sample(s) of the record "
            f"({time_s[0]*1e9:.0f}–{time_s[-1]*1e9:.0f} ns) — charge_pC is 0. "
            "Adjust analysis.integration_window_s or the scope timebase/delay.")

    # Rise time (10 % → 90 % of peak)
    rise_time_s = _rise_time(time_s, mag, amplitude)

    # CFD time
    cfd_time_s = _cfd_time(time_s, mag, amplitude, cfd_fraction)

    # Pulse edges: onset and trailing at onset_threshold_fraction of peak
    onset_time_s, trailing_time_s = _pulse_edges(
        time_s, mag, amplitude, onset_threshold_fraction
    )
    drift_time_s: float | None = (
        trailing_time_s - onset_time_s
        if onset_time_s is not None and trailing_time_s is not None
        else None
    )

    return WaveformResult(
        amplitude_V=amplitude,
        charge_pC=charge_pC,
        baseline_rms_V=baseline_rms,
        rise_time_s=rise_time_s,
        cfd_time_s=cfd_time_s,
        onset_time_s=onset_time_s,
        trailing_time_s=trailing_time_s,
        drift_time_s=drift_time_s,
        time_s=time_s,
        waveform_V=voltage_V,
        polarity=polarity,
    )


def _warn_window_once(window: tuple[float, float], message: str) -> None:
    key = (float(window[0]), float(window[1]))
    if key not in _warned_windows:
        _warned_windows.add(key)
        logger.warning(message)


def _rise_time(
    t: np.ndarray, mag: np.ndarray, peak: float
) -> float | None:
    """10 % → 90 % rise time on the magnitude waveform."""
    if peak == 0:
        return None
    try:
        idx_10 = int(np.argmax(mag >= 0.10 * peak))
        idx_90 = int(np.argmax(mag >= 0.90 * peak))
        if idx_90 > idx_10:
            return float(t[idx_90] - t[idx_10])
    except Exception:
        pass
    return None


def _cfd_time(
    t: np.ndarray, mag: np.ndarray, peak: float, fraction: float
) -> float | None:
    """First |v| crossing of fraction·peak, linearly interpolated.

    Works entirely in the magnitude domain: the previous implementation mixed
    abs(v) with the *signed* slope, which put the interpolated time outside
    the sample interval for negative (i.e. normal TCT) pulses.
    """
    threshold = fraction * peak
    if peak == 0:
        return None
    try:
        crossings = np.where(np.diff(np.sign(mag - threshold)))[0]
        if len(crossings) > 0:
            i = crossings[0]
            slope = mag[i + 1] - mag[i]
            if slope != 0:
                frac = (threshold - mag[i]) / slope
                return float(t[i] + frac * (t[i + 1] - t[i]))
    except Exception:
        pass
    return None


def _pulse_edges(
    t: np.ndarray, mag: np.ndarray, peak: float, fraction: float
) -> tuple[float | None, float | None]:
    """
    Return (onset_time, trailing_time) via linear interpolation.

    onset    — first sample where |v| crosses fraction*peak upward
    trailing — last  sample where |v| crosses fraction*peak downward

    Both times are on the scope time axis (t=0 = scope trigger).
    drift_time = trailing - onset  is the carrier collection time.
    """
    threshold = fraction * peak
    if peak == 0 or len(t) < 2:
        return None, None
    try:
        above = (mag >= threshold).astype(np.int8)
        changes = np.diff(above)
        rising  = np.where(changes ==  1)[0]  # index just before upward crossing
        falling = np.where(changes == -1)[0]  # index just before downward crossing

        if len(rising) == 0:
            return None, None

        def interp(i: int, going_up: bool) -> float:
            a, b = mag[i], mag[i + 1]
            dt = t[i + 1] - t[i]
            dv = b - a
            if dv == 0:
                return float(t[i])
            return float(t[i] + dt * (threshold - a) / dv) if going_up \
                else float(t[i] + dt * (a - threshold) / (a - b))

        t_onset = interp(rising[0], going_up=True)

        # Trailing: last downward crossing after onset
        valid_fall = falling[falling > rising[0]]
        if len(valid_fall) == 0:
            return t_onset, None
        t_trail = interp(valid_fall[-1], going_up=False)

        return t_onset, t_trail
    except Exception:
        return None, None
