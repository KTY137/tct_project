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
from .bias_supply_base import BiasSupplyBase, BiasReading, normalize_polarity

logger = logging.getLogger(__name__)
io_logger = logging.getLogger("tct.device_io")

_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _parse_num(reply: str) -> float:
    """iseg replies carry a unit suffix, e.g. '5.000000E2V' -> 500.0."""
    m = _NUM_RE.search(reply or "")
    return float(m.group()) if m else float("nan")


class IsegBiasSupply(BiasSupplyBase):
    """iseg SHR/NHR/SR HV supply over iseg SCPI (LAN socket)."""

    # Polarity-switch safety constants (docs/research/iseg_polarity_scpi.md §3).
    _DISCHARGE_FRACTION = 0.002       # |V| must be < 0.002·Vnom to switch (iseg spec)
    _POL_CONFIRM_BUDGET_S = 0.5       # relay settle is undocumented: poll readback ~0.5 s
    _POL_POLL_INTERVAL_S = 0.05
    _STATUS_IS_ON = 0x8               # channel status word bit 3 = "Is On"

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
        # Per-channel state store.  One IsegBiasSupply owns ONE VISA session but
        # may address several HV channels (SHR/NHR are multi-channel).  Each
        # channel keeps its own setpoint / output flag / compliance here.  The
        # "primary" channel is ``self._ch`` (from config); the base-class scalar
        # state (_setpoint_V / _output_on / _compliance_A) is exposed as a
        # property view of that primary entry so every existing single-channel
        # caller, the base ramp_to, and disconnect keep working byte-for-byte.
        self._ch = int(channel)
        self._default_compliance_A = compliance_A
        self._ch_state: dict[int, dict[str, Any]] = {}
        super().__init__(simulation=simulation)
        # Priority: explicit visa_address, then legacy host:port, then empty.
        if visa_address:
            self._address = visa_address
        elif host:
            self._address = f"TCPIP0::{host}::{int(port)}::SOCKET"
        else:
            self._address = ""
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
    # Per-channel state                                                    #
    # ------------------------------------------------------------------ #

    def _chs(self, channel: int) -> dict[str, Any]:
        """Return (creating on first use) the state dict for a channel."""
        st = self._ch_state.get(channel)
        if st is None:
            st = {
                "setpoint_V": 0.0,
                "output_on": False,
                "compliance_A": self._default_compliance_A,
            }
            self._ch_state[channel] = st
        return st

    # The base-class scalar state is a live view of the PRIMARY channel, so
    # base ramp_to / disconnect / setpoint_V etc. operate on the primary
    # exactly as before while other channels get their own entries.
    @property
    def _setpoint_V(self) -> float:
        return self._chs(self._ch)["setpoint_V"]

    @_setpoint_V.setter
    def _setpoint_V(self, value: float) -> None:
        self._chs(self._ch)["setpoint_V"] = value

    @property
    def _output_on(self) -> bool:
        return self._chs(self._ch)["output_on"]

    @_output_on.setter
    def _output_on(self, value: bool) -> None:
        self._chs(self._ch)["output_on"] = bool(value)

    @property
    def _compliance_A(self) -> float:
        return self._chs(self._ch)["compliance_A"]

    @_compliance_A.setter
    def _compliance_A(self, value: float) -> None:
        self._chs(self._ch)["compliance_A"] = value

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
            # Safety net: any OTHER channel this driver has touched must also be
            # ramped down and switched off, so a multi-channel session never
            # leaves a secondary channel biased on teardown.  Single-channel use
            # has no such entries, so this loop is a no-op there (behaviour is
            # unchanged).
            for ch in [c for c in self._ch_state if c != self._ch]:
                try:
                    self.ramp_to_ch(ch, 0.0)
                    self.output_off_ch(ch)
                except Exception:
                    self.logger.warning("iseg CH%d shutdown on disconnect failed", ch)
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

    # The zero-arg BiasSupplyBase methods are thin wrappers over the
    # channel-aware implementations, bound to the primary channel (self._ch).
    def set_voltage(self, voltage_V: float) -> None:
        self.set_voltage_ch(self._ch, voltage_V)

    def set_compliance(self, current_A: float) -> None:
        self.set_compliance_ch(self._ch, current_A)

    def output_on(self) -> None:
        self.output_on_ch(self._ch)

    def output_off(self) -> None:
        self.output_off_ch(self._ch)

    def read(self) -> BiasReading:
        return self.read_ch(self._ch)

    # ------------------------------------------------------------------ #
    # Channel-aware implementations (one VISA session, explicit channel)   #
    # ------------------------------------------------------------------ #

    def set_voltage_ch(self, channel: int, voltage_V: float) -> None:
        self._require_connected()
        self.check_voltage_in_range(voltage_V)
        self._chs(channel)["setpoint_V"] = voltage_V
        if not self.simulation:
            self._write(f":VOLT {voltage_V:.4f},(@{channel})")

    def set_compliance_ch(self, channel: int, current_A: float) -> None:
        self._chs(channel)["compliance_A"] = current_A
        if not self.simulation:
            self._write(f":CURR {current_A:.4e},(@{channel})")
            self.logger.debug("iseg CH%d current limit %.3e A", channel, current_A)

    def output_on_ch(self, channel: int) -> None:
        self._require_connected()
        if not self.simulation:
            self._write(f":VOLT ON,(@{channel})")
        self._chs(channel)["output_on"] = True
        self.logger.info("iseg CH%d output ON", channel)

    def output_off_ch(self, channel: int) -> None:
        if not self.simulation and self._inst is not None:
            try:
                self._write(f":VOLT 0,(@{channel})")
                self._write(f":VOLT OFF,(@{channel})")
            except Exception:
                pass
        st = self._chs(channel)
        st["output_on"] = False
        st["setpoint_V"] = 0.0
        self.logger.info("iseg CH%d output OFF", channel)

    def read_ch(self, channel: int) -> BiasReading:
        st = self._chs(channel)
        if self.simulation:
            import random
            return BiasReading(
                voltage_V=st["setpoint_V"],
                current_A=st["setpoint_V"] * 1e-9 + random.gauss(0, 1e-11),
                compliant=False,
            )
        try:
            v = _parse_num(self._query(f":MEAS:VOLT? (@{channel})"))
            i = _parse_num(self._query(f":MEAS:CURR? (@{channel})"))
            compliant = (not (i != i)) and abs(i) >= st["compliance_A"] * 0.99
            return BiasReading(voltage_V=v, current_A=i, compliant=compliant)
        except Exception as exc:
            self.logger.warning("iseg read error: %s", exc)
            return BiasReading(voltage_V=st["setpoint_V"], current_A=float("nan"),
                               compliant=False)

    def ramp_to_ch(
        self,
        channel: int,
        target_V: float,
        step_V: float = 5.0,
        delay_s: float = 0.1,
    ) -> None:
        """Per-channel ramp (base-class generic, routed through the *_ch
        primitives so any channel — not only the primary — ramps safely)."""
        self._ramp_channel(channel, target_V, step_V=step_V, delay_s=delay_s)

    def setpoint_V_ch(self, channel: int) -> float:
        return self._chs(channel)["setpoint_V"]

    def compliance_A_ch(self, channel: int) -> float:
        return self._chs(channel)["compliance_A"]

    def output_is_on_ch(self, channel: int) -> bool:
        return self._chs(channel)["output_on"]

    # ------------------------------------------------------------------ #
    # Polarity / multi-channel                                             #
    # (SCPI per docs/research/iseg_polarity_scpi.md — invent nothing)      #
    # ------------------------------------------------------------------ #

    def channel_count(self) -> int:
        """Number of channels on the module via ``:READ:MODULE:CHANNELNUMBER?``.

        Falls back to 1 on any error or in simulation (never touches hardware
        without a live session).
        """
        if self.simulation or self._inst is None:
            return 1
        try:
            n = int(_parse_num(self._query(":READ:MODULE:CHANNELNUMBER?")))
            return n if n >= 1 else 1
        except Exception as exc:
            self.logger.debug("iseg channel_count query failed: %s", exc)
            return 1

    def supports_polarity_switch(self) -> bool:
        return self.supports_polarity_switch_ch(self._ch)

    def get_polarity(self) -> str | None:
        return self.get_polarity_ch(self._ch)

    def set_polarity(self, polarity: str) -> None:
        self.set_polarity_ch(self._ch, polarity)

    def supports_polarity_switch_ch(self, channel: int) -> bool:
        """True iff ``:CONF:OUTP:POL:LIST? (@ch)`` reports both 'p' and 'n'.

        Read-only capability probe (no HV action).  Any error, timeout, or a
        single-value reply is treated as fixed polarity (fail safe: reversal
        is not offered).
        """
        if self.simulation or self._inst is None:
            return False
        try:
            reply = self._query(f":CONF:OUTP:POL:LIST? (@{channel})")
        except Exception as exc:
            self.logger.debug("iseg POL:LIST query failed: %s", exc)
            return False
        tokens = {t.strip().lower() for t in reply.split(",")}
        return "p" in tokens and "n" in tokens

    def get_polarity_ch(self, channel: int) -> str | None:
        """Current channel polarity via ``:CONF:OUTP:POL? (@ch)`` -> 'p'/'n'.

        Returns None if unknown, in simulation, or on any error.
        """
        if self.simulation or self._inst is None:
            return None
        try:
            reply = self._query(f":CONF:OUTP:POL? (@{channel})").strip().lower()
        except Exception as exc:
            self.logger.debug("iseg POL? query failed: %s", exc)
            return None
        if reply.startswith("p"):
            return "p"
        if reply.startswith("n"):
            return "n"
        return None

    def set_polarity_ch(self, channel: int, polarity: str) -> None:
        """Reverse channel output polarity — **DANGEROUS** (throws an HV relay).

        SAFETY GATING (docs/research/iseg_polarity_scpi.md §3) — proceeds only if
          (a) the module reports the channel reversible (``:CONF:OUTP:POL:LIST?``),
          (b) the output is OFF (local flag AND status-word bit 3 "Is On"), and
          (c) ``|V_meas| < 0.002·voltage_range_V`` (discharged, via ``:MEAS:VOLT?``).
        Otherwise it raises DeviceError — the switch is **never forced**.

        The relay settle time is undocumented, so after writing
        ``:CONF:OUTP:POL <p|n>,(@ch)`` the readback (``:CONF:OUTP:POL?``) is
        polled for up to ~0.5 s to CONFIRM the relay actually moved before
        returning; failure to confirm raises (do NOT ramp).

        The caller / GUI must additionally gate this behind an explicit user
        confirmation, exactly like HV enable / ramp.
        """
        target = normalize_polarity(polarity)
        self._require_connected()
        if self.simulation or self._inst is None:
            raise DeviceError("iseg simulation: polarity switching not supported")
        # (a) capability — read-only, no HV action.
        if not self.supports_polarity_switch_ch(channel):
            raise DeviceError(
                f"iseg CH{channel}: polarity is fixed on this channel/module "
                "(:CONF:OUTP:POL:LIST? did not report both 'p' and 'n')."
            )
        if self._voltage_range_V is None:
            raise DeviceError(
                "iseg: voltage_range_V unknown — cannot verify the discharge "
                "precondition; refusing to switch polarity."
            )
        # Hold the link for the whole gated switch so no other thread can turn
        # the output on or command a ramp between the checks and the confirm.
        with self.io_lock:
            # (b) output must be CONFIRMED OFF.  Fail CLOSED on unknown state:
            # if the status word can't be read (None — e.g. a USB-VCP query
            # timeout), we must NOT fall back to the local flag alone (it can be
            # stale-OFF while the channel is energized) and throw the relay.
            status = self._channel_status(channel)
            if status is None:
                raise DeviceError(
                    f"iseg CH{channel}: refuse polarity switch — could not "
                    "confirm the output is OFF (channel status query failed). "
                    "Retry once the link is stable."
                )
            if self._chs(channel)["output_on"] or (status & self._STATUS_IS_ON):
                raise DeviceError(
                    f"iseg CH{channel}: refuse polarity switch — output is ON. "
                    "Turn the channel OFF first."
                )
            # (c) discharged below 0.002·Vnom (verify measured V, not setpoint).
            v_meas = _parse_num(self._query(f":MEAS:VOLT? (@{channel})"))
            threshold = self._DISCHARGE_FRACTION * abs(self._voltage_range_V)
            if not (abs(v_meas) < threshold):
                raise DeviceError(
                    f"iseg CH{channel}: refuse polarity switch — "
                    f"|V|={abs(v_meas):.2f} V is not below the discharge threshold "
                    f"{threshold:.2f} V (0.002·Vnom). Ramp to 0 V and let it "
                    "discharge first."
                )
            # Perform the switch, then CONFIRM the relay actually moved.
            self._write(f":CONF:OUTP:POL {target},(@{channel})")
            deadline = time.monotonic() + self._POL_CONFIRM_BUDGET_S
            while time.monotonic() < deadline:
                time.sleep(self._POL_POLL_INTERVAL_S)
                if self.get_polarity_ch(channel) == target:
                    self.logger.info(
                        "iseg CH%d polarity switched to %r", channel, target
                    )
                    return
            raise DeviceError(
                f"iseg CH{channel}: polarity switch to {target!r} was not "
                f"confirmed within {self._POL_CONFIRM_BUDGET_S:.1f} s — do NOT "
                "ramp; check the module."
            )

    def _channel_status(self, channel: int | None = None) -> int | None:
        """Channel status word via ``:READ:CHAN:STAT? (@ch)`` (bit 3 = Is On,
        bit 0 = Is Positive).  Returns None on error.  ``channel=None`` uses
        the primary channel."""
        if channel is None:
            channel = self._ch
        try:
            return int(_parse_num(self._query(f":READ:CHAN:STAT? (@{channel})")))
        except Exception as exc:
            self.logger.debug("iseg CHAN:STAT query failed: %s", exc)
            return None

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
