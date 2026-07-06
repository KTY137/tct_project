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
  - Switching channel polarity is a DANGEROUS action (throws an HV relay); it
    is gated exactly like an HV ramp — see set_polarity below.
"""
from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass

from .base import BaseDevice, DeviceError


def normalize_polarity(polarity: str) -> str:
    """Normalise a polarity argument to iseg's canonical 'p' / 'n'.

    Accepts 'p'/'pos'/'positive'/'+' and 'n'/'neg'/'negative'/'-'
    (case-insensitive).  Raises DeviceError on anything else so a typo can
    never be silently forwarded to an HV supply.
    """
    if isinstance(polarity, str):
        p = polarity.strip().lower()
        if p in ("p", "pos", "positive", "+"):
            return "p"
        if p in ("n", "neg", "negative", "-"):
            return "n"
    raise DeviceError(f"Invalid polarity {polarity!r}; expected 'p' or 'n'.")


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

    # ------------------------------------------------------------------ #
    # Optional polarity / multi-channel API                               #
    #                                                                      #
    # Defaults keep every existing single-polarity, single-channel backend #
    # working unchanged.  Backends that can reverse polarity or expose     #
    # several channels override these.                                     #
    # ------------------------------------------------------------------ #

    def supports_polarity_switch(self) -> bool:
        """Whether this supply can reverse channel output polarity in software.

        Default False, so fixed-polarity supplies (and the abstract base) are
        reported as non-reversible and the UI hides/disables the control.
        """
        return False

    def get_polarity(self) -> str | None:
        """Return current polarity as 'p' (positive) / 'n' (negative).

        Returns None when unknown or unsupported (the default).
        """
        return None

    def set_polarity(self, polarity: str) -> None:
        """Switch channel output polarity — **DANGEROUS ACTION**.

        This physically throws an HV polarity relay.  It is exactly as
        dangerous as an HV ramp, therefore:

          * the caller / GUI MUST gate it behind an explicit user confirmation
            (same treatment as HV enable / ramp / homing), and
          * the supply MUST already be OFF and discharged — implementations
            verify this and refuse (raise) rather than force the relay.

        The default refuses: fixed-polarity backends cannot reverse.
        """
        raise DeviceError("polarity switching not supported by this supply")

    def channel_count(self) -> int:
        """Number of independently addressable HV channels (default 1)."""
        return 1

    # ------------------------------------------------------------------ #
    # Channel-aware API (consumed by devices.bias_channel.BiasChannel)     #
    #                                                                      #
    # A single physical supply may expose several HV channels over ONE     #
    # transport.  These methods address an explicit channel index.         #
    #                                                                      #
    # Single-channel backends inherit the defaults below, which ignore the #
    # channel index and delegate to the zero-arg methods above (so nothing #
    # changes for them).  Genuine multi-channel backends (iseg, simulated) #
    # override these to route to a specific channel on the shared session. #
    #                                                                      #
    # Every safety gate lives in the concrete zero-arg / *_ch method, so a #
    # BiasChannel proxy that merely delegates here inherits that same       #
    # protection — the proxy adds no I/O and no bypass of its own.          #
    # ------------------------------------------------------------------ #

    def set_voltage_ch(self, channel: int, voltage_V: float) -> None:
        self.set_voltage(voltage_V)

    def set_compliance_ch(self, channel: int, current_A: float) -> None:
        self.set_compliance(current_A)

    def output_on_ch(self, channel: int) -> None:
        self.output_on()

    def output_off_ch(self, channel: int) -> None:
        self.output_off()

    def read_ch(self, channel: int) -> BiasReading:
        return self.read()

    def ramp_to_ch(
        self,
        channel: int,
        target_V: float,
        step_V: float = 5.0,
        delay_s: float = 0.1,
    ) -> None:
        self.ramp_to(target_V, step_V=step_V, delay_s=delay_s)

    def get_polarity_ch(self, channel: int) -> str | None:
        return self.get_polarity()

    def set_polarity_ch(self, channel: int, polarity: str) -> None:
        self.set_polarity(polarity)

    def supports_polarity_switch_ch(self, channel: int) -> bool:
        return self.supports_polarity_switch()

    def setpoint_V_ch(self, channel: int) -> float:
        return self._setpoint_V

    def compliance_A_ch(self, channel: int) -> float:
        return self._compliance_A

    def output_is_on_ch(self, channel: int) -> bool:
        return self._output_on

    def _ramp_channel(
        self,
        channel: int,
        target_V: float,
        step_V: float = 5.0,
        delay_s: float = 0.1,
    ) -> None:
        """Generic per-channel ramp for multi-channel backends.

        Mirrors :meth:`ramp_to` step-for-step but routes every voltage step and
        the output-enable through the channel-aware primitives, so a backend
        gets a correct per-channel ramp just by overriding those primitives.
        """
        self._require_connected()
        self.check_voltage_in_range(target_V)
        step_V = abs(step_V)
        current = self.setpoint_V_ch(channel)

        if not self.output_is_on_ch(channel):
            self.output_on_ch(channel)

        sign = 1.0 if target_V >= current else -1.0
        while abs(target_V - current) > step_V / 2:
            current += sign * step_V
            if sign > 0:
                current = min(current, target_V)
            else:
                current = max(current, target_V)
            self.set_voltage_ch(channel, current)
            time.sleep(delay_s)

        self.set_voltage_ch(channel, target_V)
