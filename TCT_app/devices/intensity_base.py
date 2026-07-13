"""
Abstract interface for intensity monitors (photodiode, SiPM, or any other
reference-beam detector).

To swap the intensity detector:
  1. Subclass IntensityMonitorBase.
  2. Implement every abstractmethod.
  3. Register the class in devices/__init__.py and configs/devices.yaml.

The scan controller and GUI panels reference only IntensityMonitorBase,
so the detector hardware can be changed without touching any other module.
"""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass

import numpy as np

from .base import BaseDevice, DeviceError


class IntensityMonitorError(DeviceError):
    """Raised when an intensity-monitor measurement fails."""


def correct_baseline(
    voltage_V: np.ndarray,
    baseline_samples: int = 20,
) -> tuple[np.ndarray, float, float]:
    """Subtract the pre-trigger DC baseline from a waveform (devices layer).

    Byte-for-byte *mirror* of ``analysis.waveform_analysis.correct_baseline``.
    It is duplicated here — not imported — because ``devices/`` may not import
    ``analysis/`` under the three-layer law
    (``tests/test_layer_contracts.py::test_devices_import_nothing_above``).
    ``tests/test_intensity_panel.py::test_device_baseline_mirror_matches_analysis``
    pins the two implementations equal so they cannot silently drift.

    Returns ``(corrected_V, baseline_V, baseline_rms_V)``; the baseline is the
    mean of the first ``baseline_samples`` (pre-trigger) samples, clamped to
    ``[1, len(voltage_V)]``.  Used by every IntensityMonitor backend so a DC
    offset on the reference channel cannot bias the reported amplitude/charge.
    """
    v = np.asarray(voltage_V, dtype=float)
    if v.size == 0:
        return v, 0.0, 0.0
    n = min(max(int(baseline_samples), 1), v.size)
    baseline = float(np.mean(v[:n]))
    baseline_rms = float(np.std(v[:n]))
    return v - baseline, baseline, baseline_rms


@dataclass
class IntensityReading:
    """Single intensity-monitor readout snapshot."""
    amplitude_V: float          # Peak amplitude of the reference pulse [V]
    charge_pC: float            # Integrated charge [pC]
    time_s: np.ndarray | None   # Waveform time axis  (None if not available)
    waveform_V: np.ndarray | None  # Waveform voltage values (None if not available)
    saturated: bool = False     # True if the detector is clipping


class IntensityMonitorBase(BaseDevice):
    """
    Backend-agnostic interface for a laser-intensity reference monitor.

    Concrete implementations:
        ScopeChannelMonitor     — reads a dedicated oscilloscope channel (CH1)
        SimulatedIntensityMonitor — software simulation for testing

    A new implementation (e.g. NI-DAQ digitiser, stand-alone TIA board,
    photodiode amplifier with ADC) only needs to subclass this class and
    implement the four abstract methods below.
    """

    # ------------------------------------------------------------------ #
    # Core abstract interface                                             #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def read(self) -> IntensityReading:
        """
        Trigger a single readout and return an IntensityReading.
        This is the primary method called by the scan controller.
        """

    @abstractmethod
    def set_scale(self, volts_per_div: float) -> None:
        """
        Adjust the input range/scale so the signal is not clipping.
        Ignored by implementations that cannot change their range.
        """

    @abstractmethod
    def get_amplitude(self) -> float:
        """Return peak amplitude [V] without storing a full waveform."""

    @abstractmethod
    def get_charge(self) -> float:
        """Return integrated charge [pC]."""

    # ------------------------------------------------------------------ #
    # Stability helpers (concrete, may be overridden)                    #
    # ------------------------------------------------------------------ #

    SATURATION_FRACTION = 0.95   # fraction of full-scale that counts as saturated

    def check_stability(
        self,
        n_samples: int = 10,
        threshold_rel: float = 0.05,
    ) -> tuple[bool, float]:
        """
        Acquire *n_samples* readings and return (is_stable, rms_rel).

        Returns True when the relative RMS of the amplitudes is below
        *threshold_rel* (default 5 %).
        """
        amplitudes = [self.read().amplitude_V for _ in range(n_samples)]
        mean = sum(amplitudes) / len(amplitudes)
        if mean == 0:
            return False, float("inf")
        variance = sum((a - mean) ** 2 for a in amplitudes) / len(amplitudes)
        rms_rel = variance ** 0.5 / abs(mean)
        return rms_rel <= threshold_rel, rms_rel
