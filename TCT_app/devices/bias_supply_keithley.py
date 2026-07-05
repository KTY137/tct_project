"""
Keithley bias supply driver.

Supports (via pyvisa SCPI):
    Model 2400 / 2410 / 2450  — Source-Measure Units (SMU)
    Model 237 / 487 / 617     — older HV sources (subset of SCPI)
    Model 6487 / 6517         — picoammeters with built-in HV

The driver auto-detects the model family from *IDN? and adjusts
the command syntax accordingly.  All models share the same
BiasSupplyBase interface.

Connection: GPIB (classic), VISA-GPIB, VISA-USB, or VISA-Ethernet.
VISA address examples:
    "GPIB0::15::INSTR"
    "USB0::0x05e6::0x2410::XXXXXXX::INSTR"
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .base import DeviceError
from .bias_supply_base import BiasSupplyBase, BiasReading

logger = logging.getLogger(__name__)

# Command tables keyed by model family
# (voltage source, compliance, output on/off, measure IV)
_CMDS: dict[str, dict[str, str]] = {
    # Keithley 2400/2410/2450 SMU — full SCPI
    "24xx": {
        "src_mode":    ":SOUR:FUNC VOLT",
        "src_range":   ":SOUR:VOLT:RANG {range:.0f}",
        "src_volt":    ":SOUR:VOLT:LEV {v:.4f}",
        "compliance":  ":SENS:CURR:PROT {a:.3e}",
        "sense_mode":  ":SENS:FUNC 'CURR'",
        "output_on":   ":OUTP ON",
        "output_off":  ":OUTP OFF",
        "measure":     ":MEAS:CURR?",           # returns V,I,R,time,status
        "read_vi":     ":READ?",
    },
    # Keithley 6487 / 6517 picoammeter + HV
    "6xx7": {
        "src_mode":    ":SOUR:VOLT:STAT ON",
        "src_range":   "",                       # auto-range only
        "src_volt":    ":SOUR:VOLT {v:.4f}",
        "compliance":  ":SOUR:VOLT:ILIM {a:.3e}",
        "sense_mode":  "",
        "output_on":   ":SOUR:VOLT:STAT ON",
        "output_off":  ":SOUR:VOLT:STAT OFF",
        "measure":     ":READ?",
        "read_vi":     ":READ?",
    },
}


def _select_cmds(idn: str) -> tuple[str, dict[str, str]]:
    """Return (family_name, command_dict) based on *IDN? string."""
    idn_upper = idn.upper()
    for model_prefix in ("2400", "2410", "2450", "2401", "2440"):
        if model_prefix in idn_upper:
            return "24xx", _CMDS["24xx"]
    for model_prefix in ("6487", "6517"):
        if model_prefix in idn_upper:
            return "6xx7", _CMDS["6xx7"]
    # Fall back to 24xx syntax for unknown Keithley models
    logger.warning("Unknown Keithley model in IDN '%s' — using 24xx commands", idn)
    return "24xx", _CMDS["24xx"]


class KeithleyBiasSupply(BiasSupplyBase):
    """
    Keithley SMU / HV source driver over pyvisa.

    Config keys in devices.yaml (under bias_supply):
        visa_address    : e.g. "GPIB0::15::INSTR"
        compliance_A    : 100e-6   (initial compliance — ALWAYS set this!)
        voltage_range_V : 1100     (source range in V; 0 = auto)
        timeout_ms      : 10000
    """

    def __init__(
        self,
        visa_address: str = "",
        compliance_A: float = 100e-6,
        voltage_range_V: float = 1100.0,
        timeout_ms: int = 10000,
        simulation: bool = False,
        **_kwargs: Any,
    ) -> None:
        super().__init__(simulation=simulation)
        self._visa_address = visa_address
        self._compliance_A = compliance_A
        self._voltage_range_V = voltage_range_V
        self._timeout_ms = timeout_ms
        self._rm = None
        self._inst = None
        self._cmds: dict[str, str] = _CMDS["24xx"]   # default until connected

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            self.logger.info("KeithleyBiasSupply: simulation mode")
            return
        try:
            import pyvisa
        except ImportError as exc:
            raise DeviceError("pyvisa not installed: pip install pyvisa pyvisa-py") from exc

        try:
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(
                self._visa_address,
                timeout=self._timeout_ms,
            )
            idn = self._query("*IDN?")
            self.logger.info("Keithley IDN: %s", idn.strip())
            _family, self._cmds = _select_cmds(idn)

            # Configure as voltage source
            self._write("*RST")
            time.sleep(0.5)
            self._write(self._cmds["src_mode"])
            if self._cmds["src_range"]:
                self._write(self._cmds["src_range"].format(range=self._voltage_range_V))
            if self._cmds["sense_mode"]:
                self._write(self._cmds["sense_mode"])

            # Apply initial compliance
            self.set_compliance(self._compliance_A)
            self._write(self._cmds["src_volt"].format(v=0.0))
            self._connected = True
            self.logger.info("KeithleyBiasSupply connected at %s", self._visa_address)
        except Exception as exc:
            raise DeviceError(f"Keithley connect failed: {exc}") from exc

    def disconnect(self) -> None:
        if not self.simulation and self._inst is not None:
            try:
                self.ramp_to(0.0)
                self.output_off()
            except Exception:
                pass
            self._inst.close()
            self._inst = None
        self._connected = False
        self._setpoint_V = 0.0
        self._output_on = False
        self.logger.info("KeithleyBiasSupply disconnected")

    # ------------------------------------------------------------------ #
    # BiasSupplyBase interface                                             #
    # ------------------------------------------------------------------ #

    def set_voltage(self, voltage_V: float) -> None:
        self._require_connected()
        self.check_voltage_in_range(voltage_V)
        if self.simulation:
            self._setpoint_V = voltage_V
            return
        self._write(self._cmds["src_volt"].format(v=voltage_V))

    def set_compliance(self, current_A: float) -> None:
        self._compliance_A = current_A
        if self.simulation:
            return
        self._write(self._cmds["compliance"].format(a=current_A))
        self.logger.debug("Compliance set to %.3e A", current_A)

    def output_on(self) -> None:
        self._require_connected()
        if not self.simulation:
            self._write(self._cmds["output_on"])
        self._output_on = True
        self.logger.info("Keithley output ON")

    def output_off(self) -> None:
        if not self.simulation and self._inst is not None:
            try:
                self._write(self._cmds["src_volt"].format(v=0.0))
                self._write(self._cmds["output_off"])
            except Exception:
                pass
        self._output_on = False
        self._setpoint_V = 0.0
        self.logger.info("Keithley output OFF")

    def read(self) -> BiasReading:
        if self.simulation:
            import random
            return BiasReading(
                voltage_V=self._setpoint_V,
                current_A=self._setpoint_V * 1e-9 + random.gauss(0, 1e-11),
                compliant=False,
            )
        try:
            raw = self._query(self._cmds["read_vi"])
            parts = [float(x) for x in raw.strip().split(",")]
            # 24xx: returns V, I, R, time, status  (5 values)
            # 6xx7: returns I only or I,V
            if len(parts) >= 2:
                v, i = parts[0], parts[1]
            elif len(parts) == 1:
                # picoammeter — measure current, setpoint is voltage
                i = parts[0]
                v = self._setpoint_V
            else:
                v, i = self._setpoint_V, 0.0
            compliant = abs(i) >= self._compliance_A * 0.99
            return BiasReading(voltage_V=v, current_A=i, compliant=compliant)
        except Exception as exc:
            self.logger.warning("Keithley read error: %s", exc)
            return BiasReading(voltage_V=self._setpoint_V, current_A=float("nan"), compliant=False)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _write(self, cmd: str) -> None:
        assert self._inst is not None
        with self.io_lock:      # GUI bias poller + scan thread share the session
            self._inst.write(cmd)

    def _query(self, cmd: str) -> str:
        assert self._inst is not None
        with self.io_lock:
            return self._inst.query(cmd)
