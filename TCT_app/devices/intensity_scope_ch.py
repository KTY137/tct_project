"""
Oscilloscope-channel-based intensity monitor.

Reads the reference photodiode / SiPM from a dedicated oscilloscope
channel (typically CH1) via the shared Oscilloscope device.

This is the default intensity monitor for a TCT setup where the
reference detector is connected to the scope.  To use a stand-alone
digitiser, NI-DAQ, or any other readout instead, implement a new
subclass of IntensityMonitorBase — nothing else needs to change.

Config keys (devices.yaml → intensity_monitor section):
    channel:        1        (scope channel, 1-indexed)
    termination_ohm: 50
    input_range_V:  0.5      (full-scale; passed to set_scale)
    saturation_frac: 0.95    (fraction of full-scale treated as saturated)
    charge_integration_window_s: [20e-9, 150e-9]   (start, end relative to trigger)
    baseline_samples: 20     (leading pre-trigger samples used for baseline
                              subtraction; mirrors the analysis: block's
                              baseline_samples convention)
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from .base import DeviceError
from .intensity_base import (
    IntensityMonitorBase,
    IntensityMonitorError,
    IntensityReading,
    correct_baseline,
)


@runtime_checkable
class _ScopeProtocol(Protocol):
    """Minimal interface required from any oscilloscope passed to ScopeChannelMonitor."""
    connected: bool
    def read_channel(self, channel: int) -> tuple[np.ndarray, np.ndarray]: ...


class ScopeChannelMonitor(IntensityMonitorBase):
    """
    Intensity monitor that reads a single oscilloscope channel.

    Parameters
    ----------
    scope:
        Shared Oscilloscope instance (already connected).
    channel:
        1-indexed channel number on the scope (e.g. 1 = CH1).
    termination_ohm:
        Input termination resistance used to convert voltage to charge.
    saturation_frac:
        Fraction of current scale considered saturated.
    integration_window_s:
        (t_start, t_end) relative to trigger for charge integration.
    baseline_samples:
        Number of leading pre-trigger samples used to estimate and subtract the
        DC baseline before amplitude/charge extraction.  Mirrors the DUT
        waveform-analysis convention (``analysis:`` block's ``baseline_samples``,
        default 20) so both channels are corrected the same way.
    """

    def __init__(
        self,
        scope: "_ScopeProtocol",
        channel: int = 1,
        termination_ohm: float = 50.0,
        saturation_frac: float = 0.95,
        integration_window_s: tuple[float, float] = (20e-9, 150e-9),
        baseline_samples: int = 20,
        simulation: bool = False,
    ) -> None:
        super().__init__(simulation=simulation)
        self._scope = scope
        self._channel = channel
        self._R = termination_ohm
        self._sat_frac = saturation_frac
        self._t_start, self._t_end = integration_window_s
        self._baseline_samples = baseline_samples
        self._scale_V: float | None = None   # last set scale

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        # Connectivity is delegated to the shared scope instance.
        if not self._scope.connected:
            raise DeviceError(
                "ScopeChannelMonitor: oscilloscope must be connected first."
            )
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    # ------------------------------------------------------------------ #
    # IntensityMonitorBase interface                                      #
    # ------------------------------------------------------------------ #

    def read(self) -> IntensityReading:
        """Acquire one waveform from the scope channel and return a reading.

        Amplitude and charge are computed on the *baseline-corrected* waveform
        (the shared named formula) so a DC offset on the reference channel does
        not bias them — and therefore cannot bias ``dut_charge_norm``
        downstream.  Saturation is judged on the *raw* trace, because clipping
        happens at the physical ADC full-scale before any correction, and the
        returned ``waveform_V`` is the raw trace (what the scope actually saw).
        """
        time_s, waveform_V = self._scope.read_channel(self._channel)
        # TODO(bench): confirm on the real reference channel that the first
        # baseline_samples (pre-trigger region) are genuinely pulse-free at the
        # configured scope timebase/trigger-delay; otherwise raise
        # baseline_samples or adjust the delay so baseline estimation is clean.
        corrected, _, _ = correct_baseline(waveform_V, self._baseline_samples)
        amplitude = float(np.max(np.abs(corrected)))
        charge_pC = self._integrate_charge(time_s, corrected)
        saturated = self._check_saturation(waveform_V)
        if saturated:
            self.logger.warning(
                "CH%d: intensity monitor may be saturated (peak %.3f V)", self._channel, amplitude
            )
        return IntensityReading(
            amplitude_V=amplitude,
            charge_pC=charge_pC,
            time_s=time_s,
            waveform_V=waveform_V,
            saturated=saturated,
        )

    def set_scale(self, volts_per_div: float) -> None:
        fn = getattr(self._scope, "set_channel_scale", None)
        if fn is not None:
            fn(self._channel, volts_per_div)
        self._scale_V = volts_per_div

    def get_amplitude(self) -> float:
        _, waveform_V = self._scope.read_channel(self._channel)
        corrected, _, _ = correct_baseline(waveform_V, self._baseline_samples)
        return float(np.max(np.abs(corrected)))

    def get_charge(self) -> float:
        time_s, waveform_V = self._scope.read_channel(self._channel)
        corrected, _, _ = correct_baseline(waveform_V, self._baseline_samples)
        return self._integrate_charge(time_s, corrected)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _integrate_charge(self, time_s: np.ndarray, voltage_V: np.ndarray) -> float:
        """Integrate V(t)/R over the defined window and return charge in pC.

        Callers pass the *baseline-corrected* voltage (see ``read``); this
        method deliberately does no baseline subtraction of its own so the
        correction happens exactly once, through the shared named formula.
        """
        mask = (time_s >= self._t_start) & (time_s <= self._t_end)
        if not np.any(mask):
            return 0.0
        charge_C = np.trapz(voltage_V[mask], time_s[mask]) / self._R
        return float(charge_C * 1e12)  # → pC

    def _check_saturation(self, waveform_V: np.ndarray) -> bool:
        if self._scale_V is None:
            return False
        full_scale = self._scale_V * 8  # typical scope: 8 divisions
        return float(np.max(np.abs(waveform_V))) >= self._sat_frac * full_scale
