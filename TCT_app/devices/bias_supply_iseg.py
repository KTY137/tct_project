"""iseg high-voltage supply driver (SHR / NHR / SR desktop modules).

Supports LAN (TCPIP::SOCKET) and USB via pyvisa.

IMPORTANT — iseg USB appears as a **virtual COM port (CDC/VCP)**, NOT as a
USB-TMC instrument.  Use the ASRL VISA resource string (serial), not USB0::

    LAN  : "TCPIP0::192.168.1.30::10001::SOCKET"
    USB  : "ASRL5::INSTR"          (Windows COM5)
           "ASRL/dev/ttyUSB0::INSTR" (Linux)

Both connections use CRLF termination and 115200 baud (serial).

Config keys in devices.yaml (under bias_supply):
    backend:       iseg
    visa_address:  "ASRL5::INSTR"  # or TCPIP0::...::SOCKET
    host:          "192.168.1.30"  # legacy: auto-converted to TCPIP::SOCKET
    port:          10001           # legacy: used with host
    channel:       0               # HV-OUT CH0 / CH1
    compliance_A:  10e-6
    ramp_speed_V_s: 50.0
    timeout_ms:    5000
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from .base import DeviceError
from .bias_supply_base import BiasSupplyBase, BiasReading

logger = logging.getLogger(__name__)
io_logger = logging.getLogger("tct.device_io")

_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _parse_num(reply: str) -> float:
    """iseg replies carry a unit suffix, e.g. '5.000000E2V' -> 500.0."""
    m = _NUM_RE.search(reply or "")
    return float(m.group()) if m else float("nan")


class IsegBiasSupply(BiasSupplyBase):
    """iseg SHR/NHR/SR HV supply over iseg SCPI (LAN socket)."""

    def __init__(
        self,
        host: str = "",
        port: int = 10001,
        channel: int = 0,
        visa_address: str = "",
        compliance_A: float = 10e-6,
        voltage_range_V: float = 2000.0,
        ramp_speed_V_s: float = 50.0,
        timeout_ms: int = 5000,
        simulation: bool = False,
        **_kwargs: Any,
    ) -> None:
        super().__init__(simulation=simulation)
        # Priority: explicit visa_address, then legacy host:port, then empty.
        if visa_address:
            self._address = visa_address
        elif host:
            self._address = f"TCPIP0::{host}::{int(port)}::SOCKET"
        else:
            self._address = ""
        self._ch = int(channel)
        self._compliance_A = compliance_A
        self._voltage_range_V = voltage_range_V
        self._ramp_speed = ramp_speed_V_s
        self._timeout_ms = timeout_ms
        self._rm = None
        self._inst = None
        addr_upper = self._address.upper()
        self._is_socket = "::SOCKET" in addr_upper
        self._is_serial = addr_upper.startswith("ASRL")

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            self.logger.info("IsegBiasSupply: simulation mode")
            return
        if not self._address:
            raise DeviceError("iseg: no host/visa_address configured.")
        try:
            import pyvisa
        except ImportError as exc:
            raise DeviceError("pyvisa not installed: pip install pyvisa") from exc
        try:
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self._address)
            self._inst.timeout = self._timeout_ms
            # iseg always uses CR-LF framing regardless of transport.
            self._inst.read_termination = "\r\n"
            self._inst.write_termination = "\r\n"
            # Serial (ASRL/COM) resources need explicit baud + 8N1 settings.
            if self._is_serial:
                import pyvisa.constants as _vc
                self._inst.baud_rate = 115200
                self._inst.data_bits = 8
                self._inst.stop_bits = _vc.StopBits.one
                self._inst.parity    = _vc.Parity.none
                self._inst.flow_control = _vc.VI_ASRL_FLOW_NONE
            idn = self._query("*IDN?")
            self.logger.info("iseg IDN: %s", idn.strip())
            # Ramp speed + compliance, then park at 0 V.
            try:
                self._write(f":CONF:RAMP:VOLT {self._ramp_speed:.3f}")
            except Exception as exc:
                self.logger.debug("iseg ramp-speed set skipped: %s", exc)
            self.set_compliance(self._compliance_A)
            self._write(f":VOLT 0,(@{self._ch})")   # park at 0 V (pre-connected)
            self._setpoint_V = 0.0
            self._connected = True
            self.logger.info("IsegBiasSupply connected at %s (CH%d)",
                             self._address, self._ch)
        except Exception as exc:
            raise DeviceError(f"iseg connect failed: {exc}") from exc

    def disconnect(self) -> None:
        if not self.simulation and self._inst is not None:
            try:
                self.ramp_to(0.0)
                self.output_off()
            except Exception:
                pass
            try:
                self._inst.close()
            except Exception:
                pass
            self._inst = None
        self._connected = False
        self._setpoint_V = 0.0
        self._output_on = False
        self.logger.info("IsegBiasSupply disconnected")

    # ------------------------------------------------------------------ #
    # BiasSupplyBase interface                                             #
    # ------------------------------------------------------------------ #

    def set_voltage(self, voltage_V: float) -> None:
        self._require_connected()
        self.check_voltage_in_range(voltage_V)
        self._setpoint_V = voltage_V
        if not self.simulation:
            self._write(f":VOLT {voltage_V:.4f},(@{self._ch})")

    def set_compliance(self, current_A: float) -> None:
        self._compliance_A = current_A
        if not self.simulation:
            self._write(f":CURR {current_A:.4e},(@{self._ch})")
            self.logger.debug("iseg CH%d current limit %.3e A", self._ch, current_A)

    def output_on(self) -> None:
        self._require_connected()
        if not self.simulation:
            self._write(f":VOLT ON,(@{self._ch})")
        self._output_on = True
        self.logger.info("iseg CH%d output ON", self._ch)

    def output_off(self) -> None:
        if not self.simulation and self._inst is not None:
            try:
                self._write(f":VOLT 0,(@{self._ch})")
                self._write(f":VOLT OFF,(@{self._ch})")
            except Exception:
                pass
        self._output_on = False
        self._setpoint_V = 0.0
        self.logger.info("iseg CH%d output OFF", self._ch)

    def read(self) -> BiasReading:
        if self.simulation:
            import random
            return BiasReading(
                voltage_V=self._setpoint_V,
                current_A=self._setpoint_V * 1e-9 + random.gauss(0, 1e-11),
                compliant=False,
            )
        try:
            v = _parse_num(self._query(f":MEAS:VOLT? (@{self._ch})"))
            i = _parse_num(self._query(f":MEAS:CURR? (@{self._ch})"))
            compliant = (not (i != i)) and abs(i) >= self._compliance_A * 0.99
            return BiasReading(voltage_V=v, current_A=i, compliant=compliant)
        except Exception as exc:
            self.logger.warning("iseg read error: %s", exc)
            return BiasReading(voltage_V=self._setpoint_V, current_A=float("nan"),
                               compliant=False)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _write(self, cmd: str) -> None:
        assert self._inst is not None
        with self.io_lock:      # GUI bias poller + scan thread share the socket
            self._log_io("TX", cmd)
            if self._is_serial:
                self._drain_serial_input_locked()
            self._inst.write(cmd)
            if self._is_serial:
                self._discard_serial_echo_locked(cmd)

    def _query(self, cmd: str) -> str:
        assert self._inst is not None
        with self.io_lock:
            if not self._is_serial:
                self._log_io("TX", cmd)
                reply = self._inst.query(cmd)
                self._log_io("RX", f"{cmd} -> {reply.strip()}")
                return reply

            self._drain_serial_input_locked()
            self._log_io("TX", cmd)
            self._inst.write(cmd)
            echoed = cmd.strip()
            seen: list[str] = []
            deadline = time.monotonic() + max(self._timeout_ms, 250) / 1000.0
            while time.monotonic() < deadline:
                line = self._read_serial_line_locked(
                    timeout_ms=max(50, min(250, self._timeout_ms))
                )
                if line is None:
                    continue
                text = line.strip()
                if not text:
                    continue
                seen.append(text)
                if text.upper() == echoed.upper():
                    self._log_io("ECHO", text)
                    continue
                self._log_io("RX", f"{cmd} -> {text}")
                return text
            raise DeviceError(
                f"iseg serial query '{cmd}' returned no non-echo reply; "
                f"seen={seen!r}"
            )

    def _log_io(self, direction: str, payload: str) -> None:
        io_logger.debug("iseg  %-4s %s", direction, payload)

    def _read_serial_line_locked(self, timeout_ms: int) -> str | None:
        assert self._inst is not None
        old_timeout = self._inst.timeout
        try:
            self._inst.timeout = timeout_ms
            return self._inst.read()
        except Exception:
            return None
        finally:
            self._inst.timeout = old_timeout

    def _drain_serial_input_locked(self) -> None:
        # Serial backends echo commands; if we leave those lines queued, the
        # next query reads stale text instead of the actual reply.
        while True:
            line = self._read_serial_line_locked(timeout_ms=50)
            if line is None:
                break
            text = line.strip()
            if text:
                self._log_io("DROP", text)
                self.logger.debug("iseg serial drain dropped: %r", text)

    def _discard_serial_echo_locked(self, cmd: str) -> None:
        echoed = cmd.strip().upper()
        for _ in range(3):
            line = self._read_serial_line_locked(timeout_ms=100)
            if line is None:
                return
            text = line.strip()
            if not text:
                continue
            if text.upper() == echoed:
                self._log_io("ECHO", text)
                return
            self._log_io("DROP", text)
            self.logger.debug("iseg serial post-write dropped non-echo line: %r", text)
