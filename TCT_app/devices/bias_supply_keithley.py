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

    # Fail-safe teardown: 1 initial ramp-down attempt + 1 retry before giving up
    # and surfacing the failure loudly (see disconnect / _shutdown_output).
    _SHUTDOWN_ATTEMPTS = 2

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
        """Ramp the output to 0 V and switch it off, THEN close the link.

        Fail-safe — and never fail-*silent*.  The old path wrapped the ramp-down
        in ``except: pass``, closed the session regardless, and then declared
        ``_setpoint_V = 0`` / ``_output_on = False`` unconditionally: a supply
        that refused to come down was abandoned ENERGIZED while the driver
        claimed a 0 V / off state it never achieved.  Now (mirroring
        :meth:`IsegBiasSupply.disconnect`):

          * the ramp-down is retried once (:meth:`_shutdown_output`),
          * an output that still will not come down is logged at ERROR and its
            local state is left TRUTHFUL,
          * the VISA session is released only AFTER that best-effort teardown,
          * a ``DeviceError`` is raised so the failure reaches the operator.

        Raising is safe here: ``DeviceManager.disconnect_all()`` logs and moves
        on to the next device, and ``disconnect_device()`` returns the message to
        the UI — loud, without taking the app down.

        TODO(bench): on the lab's Keithley (2410 / 6517), confirm the teardown
        end-to-end — bias into a dummy load, pull the GPIB/USB link mid-teardown,
        and check that disconnect() reports the failure loudly instead of exiting
        quietly.
        """
        failure: Exception | None = None
        if not self.simulation and self._inst is not None:
            try:
                self._shutdown_output()
            except Exception as exc:
                failure = exc
                self.logger.error(
                    "Keithley: fail-safe ramp-down FAILED on disconnect after %d "
                    "attempts — THE OUTPUT MAY STILL BE ENERGIZED. Verify the "
                    "supply physically. Last error: %s",
                    self._SHUTDOWN_ATTEMPTS, exc,
                )
            # Release the link only AFTER the best-effort ramp-down above.
            try:
                self._inst.close()
            except Exception as exc:
                self.logger.warning("Keithley: closing the VISA session failed: %s", exc)
            self._inst = None
        self._connected = False
        if failure is not None:
            raise DeviceError(
                f"Keithley disconnect: fail-safe ramp-down FAILED ({failure}) — "
                "the output may still be energized. The link has been closed; "
                "verify the supply physically before leaving the setup."
            )
        self._setpoint_V = 0.0
        self._output_on = False
        self.logger.info(
            "KeithleyBiasSupply disconnected (output ramped to 0 V and off)"
        )

    def _shutdown_output(self) -> None:
        """Ramp to 0 V and switch the output off — **raises** on failure.

        The fail-safe teardown primitive behind :meth:`disconnect`.  Deliberately
        does NOT go through :meth:`output_off`, which swallows write errors so it
        stays usable from a ``finally`` block: here a failure MUST be visible,
        because the whole point is to prove the HV actually came down before the
        link is dropped.

        Retried once.  Both commands are idempotent and drive the supply toward
        the SAME safe state (source level 0 V, then output off); neither can
        raise the voltage, so re-issuing them after a dropped frame is safe.

        The ramp is skipped when the output is already off — walking an idle
        output to zero must never enable it (safety rule 1).

        The ramp-down and the 0 V source-level write are both a COURTESY (a
        smooth descent); the ``output_off`` disable is the SAFETY GUARANTEE.
        Each lives in its OWN try, so a transport that rejects value writes but
        would accept the disable still gets it issued — the load-bearing step
        never lives behind the ramp.  Local state is updated only after the
        hardware has acknowledged; a failed disable leaves the state UNKNOWN
        (believed-ON), never a false OFF.
        """
        last: Exception | None = None
        for attempt in range(self._SHUTDOWN_ATTEMPTS):
            # Courtesy 1: walk the HV down gently while the output is still on.
            try:
                if self._output_on:
                    self.ramp_to(0.0)
            except Exception as exc:
                self.logger.warning(
                    "Keithley: gentle ramp-down attempt %d/%d failed (%s) — "
                    "attempting the output-disable regardless.",
                    attempt + 1, self._SHUTDOWN_ATTEMPTS, exc,
                )
            # Courtesy 2: drive the source level to 0 V (also a value write).
            zeroed = True
            try:
                self._write(self._cmds["src_volt"].format(v=0.0))
            except Exception as exc:
                zeroed = False
                self.logger.warning(
                    "Keithley: 0 V source write attempt %d/%d failed (%s) — "
                    "attempting the output-disable regardless.",
                    attempt + 1, self._SHUTDOWN_ATTEMPTS, exc,
                )
            # SAFETY GUARANTEE: disable the output, isolated from every value
            # write above so it is attempted even when the ramp/park could not.
            try:
                self._write(self._cmds["output_off"])
            except Exception as exc:
                last = exc
                self.logger.warning(
                    "Keithley: output-disable attempt %d/%d failed: %s",
                    attempt + 1, self._SHUTDOWN_ATTEMPTS, exc,
                )
                continue
            self._output_on = False
            if zeroed:
                self._setpoint_V = 0.0
            self.logger.info("Keithley switched OFF (disconnect)")
            return
        raise DeviceError(
            f"output-disable failed after {self._SHUTDOWN_ATTEMPTS} attempts: {last}"
        )

    # ------------------------------------------------------------------ #
    # BiasSupplyBase interface                                             #
    # ------------------------------------------------------------------ #

    def set_voltage(self, voltage_V: float) -> None:
        """Command a new setpoint (no ramp).  Hardware FIRST, local state after.

        The real path also RECORDS the setpoint now: it previously wrote the
        level and never updated ``_setpoint_V``, so a direct set_voltage() left
        the driver (and the UI) reporting a voltage the supply was no longer at.
        """
        self._require_connected()
        self.check_voltage_in_range(voltage_V)
        if not self.simulation:
            self._write(self._cmds["src_volt"].format(v=voltage_V))
        self._setpoint_V = voltage_V

    def set_compliance(self, current_A: float) -> None:
        """Set the HV CURRENT LIMIT.  Hardware FIRST, local state after.

        Recording first meant a failed write left the driver believing a limit
        the supply never took — and the scan's compliance/trip detection then
        compares readings against a limit that does not exist on the hardware.
        On failure the OLD value stays in place and the exception reaches the
        caller.
        """
        if not self.simulation:
            self._write(self._cmds["compliance"].format(a=current_A))
            self.logger.debug("Compliance set to %.3e A", current_A)
        self._compliance_A = current_A

    def output_on(self) -> None:
        self._require_connected()
        if not self.simulation:
            self._write(self._cmds["output_on"])
        self._output_on = True
        self.logger.info("Keithley output ON")

    def output_off(self) -> None:
        """Switch the output off.  Fail-safe: never raises.

        Abort / ``finally`` paths depend on this not raising, so the non-raising
        contract is kept — but a FAILED write no longer clears the local
        ``_output_on`` flag: claiming an OFF that was never achieved is exactly
        the stale-flag bug this driver is being hardened against.  The failure is
        logged at ERROR and the local state is left as-is.

        The 0 V source-level write is a COURTESY (a disabled output holds no HV
        anyway); the ``output_off`` disable is the SAFETY GUARANTEE.  Each gets
        its OWN try so a dropped 0 V frame can NEVER suppress the disable.
        """
        zeroed = True
        if not self.simulation and self._inst is not None:
            try:
                self._write(self._cmds["src_volt"].format(v=0.0))   # cosmetic
            except Exception as exc:
                zeroed = False
                self.logger.warning(
                    "Keithley: cosmetic 0 V write failed (%s) — proceeding to "
                    "the safety-critical output-disable regardless.", exc,
                )
            try:
                self._write(self._cmds["output_off"])               # the guarantee
            except Exception as exc:
                self.logger.error(
                    "Keithley: OUTPUT-OFF WRITE FAILED (%s) — the output may "
                    "still be ENERGIZED; leaving local state ON rather than "
                    "claiming an OFF we never achieved.", exc,
                )
                return
        self._output_on = False
        if zeroed:
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
