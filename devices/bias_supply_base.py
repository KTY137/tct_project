"""
Abstract interface for a bias voltage supply (SMU / HV source).

Concrete implementations:
    KeithleyBiasSupply    — Keithley 2400 / 2410 / 237 / 6517 via VISA
    SimulatedBiasSupply   — software simulation

The rest of the application references only BiasSupplyBase so swapping
the hardware requires only a YAML change.

Safety rules enforced here:
  - Current compliance MUST be set before enabling output.
  - Voltage is always ramped in steps (ramp_to) — never jumped instantly.
  - Polarity is not assumed; positive or negative bias both work.
"""
from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass

from .base import BaseDevice, DeviceError


@dataclass
class BiasReading:
    voltage_V: float
    current_A: float
    compliant: bool        # True if compliance limit was hit


class BiasSupplyBase(BaseDevice):
    """
    Backend-agnostic interface for a single-channel bias supply.

    Typical workflow:
        supply.connect()
        supply.set_compliance(100e-6)   # 100 µA — always set before apply!
        supply.ramp_to(-300.0)          # ramp to −300 V
        reading = supply.read()
        supply.ramp_to(0.0)
        supply.output_off()
        supply.disconnect()
    """

    def __init__(self, simulation: bool = False) -> None:
        super().__init__(simulation=simulation)
        self._setpoint_V: float = 0.0
        self._compliance_A: float = 100e-6   # safe default 100 µA
        self._output_on: bool = False
        # Hard setpoint ceiling (|V|), from devices.yaml voltage_range_V.
        # None = no clamp.  Subclasses that accept the config key assign it.
        self._voltage_range_V: float | None = None

    # ------------------------------------------------------------------ #
    # Abstract interface                                                   #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def set_voltage(self, voltage_V: float) -> None:
        """Immediately set output voltage (no ramp).  Internal use."""

    @abstractmethod
    def set_compliance(self, current_A: float) -> None:
        """Set the current compliance limit (A)."""

    @abstractmethod
    def output_on(self) -> None:
        """Enable the output."""

    @abstractmethod
    def output_off(self) -> None:
        """Disable the output and return to 0 V."""

    @abstractmethod
    def read(self) -> BiasReading:
        """Return current voltage and current measurement."""

    # ------------------------------------------------------------------ #
    # Concrete helpers                                                     #
    # ------------------------------------------------------------------ #

    @property
    def setpoint_V(self) -> float:
        return self._setpoint_V

    @property
    def compliance_A(self) -> float:
        return self._compliance_A

    @property
    def voltage_range_V(self) -> float | None:
        return self._voltage_range_V

    def check_voltage_in_range(self, voltage_V: float) -> None:
        """Raise DeviceError if |voltage_V| exceeds the configured range.

        Every setpoint path (ramp_to and the concrete set_voltage
        implementations) must go through this — it is the last software guard
        between a buggy scan config and the HV output.
        """
        if self._voltage_range_V is None:
            return
        limit = abs(self._voltage_range_V)
        if limit > 0 and abs(voltage_V) > limit:
            raise DeviceError(
                f"Requested bias {voltage_V:.1f} V exceeds the configured "
                f"voltage_range_V = ±{limit:.0f} V — refusing to set it."
            )

    def ramp_to(
        self,
        target_V: float,
        step_V: float = 5.0,
        delay_s: float = 0.1,
    ) -> None:
        """
        Ramp voltage from current setpoint to target_V in steps.

        Parameters
        ----------
        target_V : float
            Final voltage setpoint (V).
        step_V : float
            Magnitude of each voltage step (default 5 V).
            Sign is determined automatically.
        delay_s : float
            Pause between steps (s).
        """
        self._require_connected()
        self.check_voltage_in_range(target_V)
        step_V = abs(step_V)
        current = self._setpoint_V

        if not self._output_on:
            self.output_on()

        sign = 1.0 if target_V >= current else -1.0
        while abs(target_V - current) > step_V / 2:
            current += sign * step_V
            # Don't overshoot
            if sign > 0:
                current = min(current, target_V)
            else:
                current = max(current, target_V)
            self.set_voltage(current)
            self._setpoint_V = current
            time.sleep(delay_s)

        self.set_voltage(target_V)
        self._setpoint_V = target_V

    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError(f"{type(self).__name__} is not connected.")
