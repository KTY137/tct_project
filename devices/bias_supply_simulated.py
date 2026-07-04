"""Simulated bias supply — no hardware required."""
from __future__ import annotations

import random

from .bias_supply_base import BiasSupplyBase, BiasReading


class SimulatedBiasSupply(BiasSupplyBase):
    """
    Drop-in simulation for BiasSupplyBase consumers.

    Models:
      - Linear leakage current: I ≈ V × 1 nA/V + Gaussian noise 10 pA
      - Compliance trip if |I| exceeds _compliance_A
    """

    _LEAKAGE_A_PER_V = 1e-9    # 1 nA/V leakage
    _NOISE_A         = 10e-12  # 10 pA RMS noise

    def __init__(self, simulation: bool = True) -> None:
        super().__init__(simulation=simulation)

    def connect(self) -> None:
        self._connected = True
        self.logger.info("SimulatedBiasSupply connected")

    def disconnect(self) -> None:
        self._connected = False
        self._setpoint_V = 0.0
        self._output_on = False
        self.logger.info("SimulatedBiasSupply disconnected")

    def set_voltage(self, voltage_V: float) -> None:
        self._require_connected()
        self._setpoint_V = voltage_V

    def set_compliance(self, current_A: float) -> None:
        self._compliance_A = current_A

    def output_on(self) -> None:
        self._require_connected()
        self._output_on = True

    def output_off(self) -> None:
        self._output_on = False
        self._setpoint_V = 0.0

    def read(self) -> BiasReading:
        v = self._setpoint_V if self._output_on else 0.0
        i = v * self._LEAKAGE_A_PER_V + random.gauss(0, self._NOISE_A)
        compliant = abs(i) >= self._compliance_A * 0.99
        return BiasReading(voltage_V=v, current_A=i, compliant=compliant)
