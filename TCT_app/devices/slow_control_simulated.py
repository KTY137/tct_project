"""
Simulated slow-control channel.

Returns a slowly drifting sinusoidal value with Gaussian noise so the
monitor panel and InfluxDB writer can be exercised without hardware.
"""
from __future__ import annotations

import math
import random
import time

from .slow_control_base import AlarmThresholds, SlowControlChannel


class SimulatedSlowChannel(SlowControlChannel):
    """
    Drop-in simulation for any SlowControlChannel consumer.

    Parameters
    ----------
    nominal:
        Centre value of the simulated reading.
    noise:
        Gaussian noise sigma (same units as the channel).
    drift_amplitude:
        Peak-to-peak drift amplitude (sinusoidal).
    drift_period_s:
        Period of the slow drift in seconds.
    """

    def __init__(
        self,
        name: str,
        unit: str,
        nominal: float = 25.0,
        noise: float = 0.5,
        drift_amplitude: float = 2.0,
        drift_period_s: float = 60.0,
        thresholds: AlarmThresholds | None = None,
    ) -> None:
        super().__init__(name=name, unit=unit, thresholds=thresholds, simulation=True)
        self._nominal       = nominal
        self._noise         = noise
        self._drift_amp     = drift_amplitude
        self._drift_period  = drift_period_s
        self._start         = time.monotonic()

    def connect(self) -> None:
        self._connected = True
        self.logger.info("SimulatedSlowChannel '%s' connected", self.name)

    def disconnect(self) -> None:
        self._connected = False

    def read(self) -> float:
        t     = time.monotonic() - self._start
        drift = self._drift_amp * math.sin(2 * math.pi * t / max(self._drift_period, 1e-3))
        noise = random.gauss(0.0, self._noise)
        return self._nominal + drift + noise
