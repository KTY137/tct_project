"""
Software simulation of an intensity monitor.

Returns synthetic Gaussian pulse waveforms with optional noise and
drift, so the rest of the application can be developed and tested
without any hardware.
"""
from __future__ import annotations

import math
import random
import time

import numpy as np

from .intensity_base import IntensityMonitorBase, IntensityReading


class SimulatedIntensityMonitor(IntensityMonitorBase):
    """
    Drop-in simulation for any IntensityMonitorBase consumer.

    Parameters
    ----------
    amplitude_V:
        Nominal pulse amplitude.
    noise_frac:
        Relative amplitude noise (Gaussian sigma / amplitude).
    drift_rate_per_s:
        Slow linear drift of the amplitude per second (fraction).
    saturates_above_V:
        Amplitude above which the reading is flagged as saturated.
    """

    def __init__(
        self,
        amplitude_V: float = 0.2,
        noise_frac: float = 0.02,
        drift_rate_per_s: float = 0.001,
        saturates_above_V: float = 0.9,
        simulation: bool = True,
    ) -> None:
        super().__init__(simulation=simulation)
        self._nominal_amplitude = amplitude_V
        self._noise_frac = noise_frac
        self._drift_rate = drift_rate_per_s
        self._sat_limit = saturates_above_V
        self._start_time = time.monotonic()
        self._scale_V: float | None = None

        # Fixed time axis shared across all waveforms (200 ns window)
        self._time_s = np.linspace(-20e-9, 180e-9, 500)

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        self._connected = True
        self.logger.info("SimulatedIntensityMonitor connected")

    def disconnect(self) -> None:
        self._connected = False

    # ------------------------------------------------------------------ #
    # IntensityMonitorBase interface                                      #
    # ------------------------------------------------------------------ #

    def read(self) -> IntensityReading:
        amp = self._current_amplitude()
        waveform = self._make_waveform(amp)
        charge_pC = self._integrate(waveform)
        saturated = amp >= self._sat_limit
        return IntensityReading(
            amplitude_V=amp,
            charge_pC=charge_pC,
            time_s=self._time_s.copy(),
            waveform_V=waveform,
            saturated=saturated,
        )

    def set_scale(self, volts_per_div: float) -> None:
        self._scale_V = volts_per_div   # stored but not enforced in simulation

    def get_amplitude(self) -> float:
        return self._current_amplitude()

    def get_charge(self) -> float:
        amp = self._current_amplitude()
        waveform = self._make_waveform(amp)
        return self._integrate(waveform)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _current_amplitude(self) -> float:
        elapsed = time.monotonic() - self._start_time
        drift = 1.0 + self._drift_rate * elapsed
        noise = random.gauss(0.0, self._noise_frac)
        return max(0.0, self._nominal_amplitude * drift * (1.0 + noise))

    def _make_waveform(self, amplitude: float) -> np.ndarray:
        """Return a Gaussian pulse waveform at the given amplitude."""
        t0 = 40e-9       # pulse centre
        sigma = 8e-9     # pulse width
        pulse = amplitude * np.exp(-0.5 * ((self._time_s - t0) / sigma) ** 2)
        noise = np.random.normal(0.0, amplitude * 0.01, size=pulse.shape)
        return pulse + noise

    def _integrate(self, waveform: np.ndarray) -> float:
        R = 50.0  # assumed 50-Ω termination
        charge_C = np.trapz(waveform, self._time_s) / R
        return float(charge_C * 1e12)
