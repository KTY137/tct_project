"""Channel-scoped view over a bias-supply driver.

A single physical HV supply (e.g. an iseg SHR/NHR) can expose several output
channels over ONE transport.  ``BiasChannel`` binds a driver instance to a
fixed channel index and presents the exact ``BiasSupplyBase``-shaped API the
GUI and scan controller already use, delegating every operation to the
driver's channel-aware ``*_ch`` methods.

Design rules (see docs/ARCHITECTURE.md, hardware safety rules):

  * The proxy performs **no** hardware I/O of its own and keeps **no**
    independent state — the driver owns per-channel state, so a primary-channel
    proxy behaves byte-for-byte like the bare driver did.
  * Every safety gate (compliance-before-output, discharge-before-polarity,
    voltage-range clamp, confirm-after-switch) lives in the driver's
    channel-aware methods, so pure delegation preserves all of them.
  * It never opens a second session: all channels share the driver's single
    VISA/serial link and its ``io_lock``.
"""
from __future__ import annotations

from .bias_supply_base import BiasSupplyBase, BiasReading


class BiasChannel:
    """One HV channel of a (possibly multi-channel) :class:`BiasSupplyBase`."""

    def __init__(self, driver: BiasSupplyBase, channel: int) -> None:
        self._driver = driver
        self.channel = int(channel)

    # ------------------------------------------------------------------ #
    # Passthrough state / identity                                        #
    # ------------------------------------------------------------------ #

    @property
    def driver(self) -> BiasSupplyBase:
        """The underlying shared driver (for callers that must reach it)."""
        return self._driver

    @property
    def connected(self) -> bool:
        return self._driver.connected

    @property
    def simulation(self) -> bool:
        return self._driver.simulation

    @property
    def voltage_range_V(self) -> float | None:
        return self._driver.voltage_range_V

    @property
    def setpoint_V(self) -> float:
        return self._driver.setpoint_V_ch(self.channel)

    @property
    def compliance_A(self) -> float:
        return self._driver.compliance_A_ch(self.channel)

    @property
    def is_output_on(self) -> bool:
        """This channel's *believed* output state (read-only).

        The honest state-query counterpart to the switch-ON action
        :meth:`enable_output`; delegates to the driver's per-channel local
        belief ``output_is_on_ch``.  It is never the dangerous method that
        switches HV on, so reading it cannot energize anything.
        """
        return self._driver.output_is_on_ch(self.channel)

    def channel_count(self) -> int:
        """A single channel view always reports 1."""
        return 1

    def is_alive(self) -> bool:
        return self._driver.is_alive()

    def check_voltage_in_range(self, voltage_V: float) -> None:
        self._driver.check_voltage_in_range(voltage_V)

    # ------------------------------------------------------------------ #
    # Connection — delegate to the shared driver                          #
    #                                                                      #
    # Only the PRIMARY channel proxy is registered in DeviceManager's      #
    # named_devices()/connect_all(), so the driver connects/disconnects    #
    # exactly once even though several proxies share it.                   #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        self._driver.connect()

    def disconnect(self) -> None:
        self._driver.disconnect()

    # ------------------------------------------------------------------ #
    # Bias operations — bound to this channel                             #
    # ------------------------------------------------------------------ #

    def set_voltage(self, voltage_V: float) -> None:
        self._driver.set_voltage_ch(self.channel, voltage_V)

    def set_compliance(self, current_A: float) -> None:
        self._driver.set_compliance_ch(self.channel, current_A)

    def enable_output(self) -> None:
        self._driver.output_on_ch(self.channel)

    def output_off(self) -> None:
        self._driver.output_off_ch(self.channel)

    def read(self) -> BiasReading:
        return self._driver.read_ch(self.channel)

    def ramp_to(
        self,
        target_V: float,
        step_V: float = 5.0,
        delay_s: float = 0.1,
    ) -> None:
        self._driver.ramp_to_ch(
            self.channel, target_V, step_V=step_V, delay_s=delay_s
        )

    # ------------------------------------------------------------------ #
    # Polarity (DANGEROUS — gated inside the driver)                      #
    # ------------------------------------------------------------------ #

    def get_polarity(self) -> str | None:
        return self._driver.get_polarity_ch(self.channel)

    def set_polarity(self, polarity: str) -> None:
        self._driver.set_polarity_ch(self.channel, polarity)

    def supports_polarity_switch(self) -> bool:
        return self._driver.supports_polarity_switch_ch(self.channel)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (f"BiasChannel(ch={self.channel}, "
                f"driver={type(self._driver).__name__})")
