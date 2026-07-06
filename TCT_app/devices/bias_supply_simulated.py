"""Simulated bias supply — no hardware required."""
from __future__ import annotations

import random
from typing import Any

from .base import DeviceError
from .bias_supply_base import BiasSupplyBase, BiasReading, normalize_polarity


class SimulatedBiasSupply(BiasSupplyBase):
    """
    Drop-in simulation for BiasSupplyBase consumers.

    Models:
      - Linear leakage current: I ≈ V × 1 nA/V + Gaussian noise 10 pA
      - Compliance trip if |I| exceeds _compliance_A
      - Optional electronically-reversible polarity, gated with the SAME
        precondition as the real iseg driver (output OFF + discharged below
        0.002·Vnom).  This lets the GUI and tests exercise the real polarity
        code paths headlessly instead of a stub.
      - Multiple independent channels (channel_count > 1), each with its own
        setpoint / output / compliance / measured-voltage / polarity state, so
        the multi-channel BiasChannel proxy can be exercised headlessly.

    Constructor knobs (all optional, safe defaults keep the no-arg call working):
      channel_count       — number of channels the module reports (default 1)
      polarity_reversible — whether the polarity relay can be switched (default True)
      polarity            — initial polarity 'p'/'n' (default 'n')
      voltage_range_V     — nominal voltage; sets the discharge threshold
    """

    _LEAKAGE_A_PER_V = 1e-9    # 1 nA/V leakage
    _NOISE_A         = 10e-12  # 10 pA RMS noise
    _DISCHARGE_FRACTION = 0.002  # matches the iseg 0.002·Vnom switching gate

    def __init__(
        self,
        simulation: bool = True,
        channel_count: int = 1,
        polarity_reversible: bool = True,
        polarity: str = "n",
        voltage_range_V: float | None = None,
    ) -> None:
        # Per-channel state store must exist before super().__init__() assigns
        # the base scalar state (which is a view of the primary channel below).
        self._primary_ch = 0
        self._channel_count = max(1, int(channel_count))
        self._polarity_reversible = bool(polarity_reversible)
        self._init_polarity = normalize_polarity(polarity)
        self._sim_state: dict[int, dict[str, Any]] = {}
        super().__init__(simulation=simulation)
        self._voltage_range_V = voltage_range_V

    # ------------------------------------------------------------------ #
    # Per-channel state                                                    #
    # ------------------------------------------------------------------ #

    def _scs(self, channel: int) -> dict[str, Any]:
        st = self._sim_state.get(channel)
        if st is None:
            st = {
                "setpoint_V": 0.0,
                "output_on": False,
                "compliance_A": 100e-6,
                # Physical output voltage.  Unlike the setpoint it is NOT reset
                # to 0 by output_off() — it models charge held on the DUT /
                # cable until it is ramped down, exactly what the discharge
                # precondition guards.
                "measured_V": 0.0,
                "polarity": self._init_polarity,
            }
            self._sim_state[channel] = st
        return st

    # The base scalar state is a live view of the PRIMARY channel.
    @property
    def _setpoint_V(self) -> float:
        return self._scs(self._primary_ch)["setpoint_V"]

    @_setpoint_V.setter
    def _setpoint_V(self, value: float) -> None:
        self._scs(self._primary_ch)["setpoint_V"] = value

    @property
    def _output_on(self) -> bool:
        return self._scs(self._primary_ch)["output_on"]

    @_output_on.setter
    def _output_on(self, value: bool) -> None:
        self._scs(self._primary_ch)["output_on"] = bool(value)

    @property
    def _compliance_A(self) -> float:
        return self._scs(self._primary_ch)["compliance_A"]

    @_compliance_A.setter
    def _compliance_A(self, value: float) -> None:
        self._scs(self._primary_ch)["compliance_A"] = value

    @property
    def _measured_V(self) -> float:
        return self._scs(self._primary_ch)["measured_V"]

    @_measured_V.setter
    def _measured_V(self, value: float) -> None:
        self._scs(self._primary_ch)["measured_V"] = value

    # ------------------------------------------------------------------ #
    # BaseDevice / BiasSupplyBase interface (primary-channel wrappers)     #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        self._connected = True
        self.logger.info("SimulatedBiasSupply connected")

    def disconnect(self) -> None:
        self._connected = False
        for st in self._sim_state.values():
            st["setpoint_V"] = 0.0
            st["measured_V"] = 0.0
            st["output_on"] = False
        self.logger.info("SimulatedBiasSupply disconnected")

    def set_voltage(self, voltage_V: float) -> None:
        self.set_voltage_ch(self._primary_ch, voltage_V)

    def set_compliance(self, current_A: float) -> None:
        self.set_compliance_ch(self._primary_ch, current_A)

    def output_on(self) -> None:
        self.output_on_ch(self._primary_ch)

    def output_off(self) -> None:
        self.output_off_ch(self._primary_ch)

    def read(self) -> BiasReading:
        return self.read_ch(self._primary_ch)

    # ------------------------------------------------------------------ #
    # Channel-aware implementations                                        #
    # ------------------------------------------------------------------ #

    def channel_count(self) -> int:
        return self._channel_count

    def set_voltage_ch(self, channel: int, voltage_V: float) -> None:
        self._require_connected()
        st = self._scs(channel)
        st["setpoint_V"] = voltage_V
        if st["output_on"]:
            st["measured_V"] = voltage_V

    def set_compliance_ch(self, channel: int, current_A: float) -> None:
        self._scs(channel)["compliance_A"] = current_A

    def output_on_ch(self, channel: int) -> None:
        self._require_connected()
        st = self._scs(channel)
        st["output_on"] = True
        st["measured_V"] = st["setpoint_V"]

    def output_off_ch(self, channel: int) -> None:
        st = self._scs(channel)
        st["output_on"] = False
        st["setpoint_V"] = 0.0
        # measured_V intentionally retained: opening the relay does not instantly
        # discharge the DUT (see _scs).

    def read_ch(self, channel: int) -> BiasReading:
        st = self._scs(channel)
        v = st["measured_V"]
        i = v * self._LEAKAGE_A_PER_V + random.gauss(0, self._NOISE_A)
        compliant = abs(i) >= st["compliance_A"] * 0.99
        return BiasReading(voltage_V=v, current_A=i, compliant=compliant)

    def ramp_to_ch(
        self,
        channel: int,
        target_V: float,
        step_V: float = 5.0,
        delay_s: float = 0.1,
    ) -> None:
        self._ramp_channel(channel, target_V, step_V=step_V, delay_s=delay_s)

    def setpoint_V_ch(self, channel: int) -> float:
        return self._scs(channel)["setpoint_V"]

    def compliance_A_ch(self, channel: int) -> float:
        return self._scs(channel)["compliance_A"]

    def output_is_on_ch(self, channel: int) -> bool:
        return self._scs(channel)["output_on"]

    # ------------------------------------------------------------------ #
    # Polarity                                                            #
    # ------------------------------------------------------------------ #

    def supports_polarity_switch(self) -> bool:
        return self.supports_polarity_switch_ch(self._primary_ch)

    def get_polarity(self) -> str | None:
        return self.get_polarity_ch(self._primary_ch)

    def set_polarity(self, polarity: str) -> None:
        self.set_polarity_ch(self._primary_ch, polarity)

    def supports_polarity_switch_ch(self, channel: int) -> bool:
        return self._polarity_reversible

    def get_polarity_ch(self, channel: int) -> str | None:
        return self._scs(channel)["polarity"]

    def set_polarity_ch(self, channel: int, polarity: str) -> None:
        """Simulated polarity reversal, gated exactly like the real supply.

        DANGEROUS action (see BiasSupplyBase.set_polarity): refuses unless the
        channel output is OFF and discharged below 0.002·Vnom; never forces it.
        """
        target = normalize_polarity(polarity)
        self._require_connected()
        if not self._polarity_reversible:
            raise DeviceError("polarity switching not supported by this supply")
        st = self._scs(channel)
        if st["output_on"]:
            raise DeviceError(
                "refuse polarity switch — output is ON; turn it OFF first."
            )
        threshold = self._discharge_threshold()
        if not (abs(st["measured_V"]) < threshold):
            raise DeviceError(
                f"refuse polarity switch — |V|={abs(st['measured_V']):.2f} V is not "
                f"below the discharge threshold {threshold:.2f} V (0.002·Vnom)."
            )
        st["polarity"] = target
        self.logger.info("SimulatedBiasSupply CH%d polarity -> %r", channel, target)

    def _discharge_threshold(self) -> float:
        vnom = abs(self._voltage_range_V) if self._voltage_range_V else 1000.0
        return self._DISCHARGE_FRACTION * vnom
