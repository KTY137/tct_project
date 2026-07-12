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

    # ------------------------------------------------------------------ #
    # Channel status word (``:READ:CHAN:STAT?``) bit map.                 #
    #                                                                      #
    # Every bit below is taken from the CITED table in                     #
    # docs/research/iseg_polarity_scpi.md §6, which reproduces the iseg    #
    # NHS/SHR Programmer's Manual channel-status register.  Do NOT add     #
    # bits that are not in that table (safety rule 4: never invent         #
    # instrument semantics).  Bits 22 and 24-31 are reserved /             #
    # model-specific in the source and are deliberately NOT decoded — they #
    # stay visible to callers through the raw ``status_word``.             #
    # ------------------------------------------------------------------ #
    _STATUS_IS_POSITIVE      = 0x1      # bit  0 — positive output polarity
    _STATUS_IS_ARC           = 0x2      # bit  1 — arc detected (transient)
    _STATUS_IS_INPUT_ERROR   = 0x4      # bit  2 — input / parameter error
    _STATUS_IS_ON            = 0x8      # bit  3 — channel switched on
    _STATUS_IS_VOLTAGE_RAMP  = 0x10     # bit  4 — voltage is ramping
    _STATUS_IS_EMERGENCY_OFF = 0x20     # bit  5 — emergency off asserted
    _STATUS_IS_CONST_CURRENT = 0x40     # bit  6 — current-controlled (compliance)
    _STATUS_IS_CONST_VOLTAGE = 0x80     # bit  7 — voltage-controlled (normal)
    _STATUS_IS_ARC_ERROR     = 0x200    # bit  9 — arc error LATCHED
    _STATUS_IS_EXT_INHIBIT   = 0x1000   # bit 12 — external inhibit asserted
    _STATUS_IS_CURRENT_TRIP  = 0x2000   # bit 13 — current trip triggered

    # TODO(bench): on the lab's iseg module, confirm the channel-status bit map
    # end-to-end — force a real over-current trip into a resistive dummy load and
    # check that ``:READ:CHAN:STAT? (@ch)`` actually sets bit 13 (0x2000) and
    # clears bit 3 ("Is On").  The map below is from the manual (cited), not yet
    # observed on our hardware; if the module reports a trip on a different bit,
    # _STATUS_TRIP_MASK is the single place to correct.

    # A "trip" here = the module latched a PROTECTIVE fault, i.e. the HV is not
    # doing what was asked and the operator must intervene.  Deliberately narrow:
    #   * bit 5  emergency off  — output killed by the emergency-off input
    #   * bit 9  arc error      — arc condition LATCHED (bit 1 "Is Arc" is only a
    #                             transient detection, so it is NOT a trip on its
    #                             own and is left to the raw word)
    #   * bit 12 external inhibit — the INTERLOCK CHAIN is asserted: the module
    #                             holds/kills the output on its own authority, so
    #                             the HV is not doing what was asked and no scan
    #                             may proceed until a human clears the interlock.
    #                             That is the definition of a trip above, so it is
    #                             in the mask; treating it as merely informational
    #                             would let the app keep polling a channel the
    #                             hardware has already forced off.
    #   * bit 13 current trip   — over-current protection fired
    # "Is Input Error" (bit 2) is a rejected-command error, not an HV fault, so it
    # is surfaced via the raw word rather than being escalated to a trip.
    _STATUS_TRIP_MASK = (
        _STATUS_IS_EMERGENCY_OFF | _STATUS_IS_ARC_ERROR
        | _STATUS_IS_EXT_INHIBIT | _STATUS_IS_CURRENT_TRIP
    )

    # TODO(bench): on the lab's iseg module, confirm bit 12 ("Is External
    # Inhibit") is CLEAR when the interlock chain is closed and the inhibit input
    # is idle.  If the module instead reports the bit asserted at rest (e.g. an
    # unconnected, active-low inhibit input), every read would report a trip —
    # in that case wire the interlock or drop the bit from _STATUS_TRIP_MASK.

    # Fail-safe teardown: 1 initial ramp-down attempt + 1 retry before giving up
    # and surfacing the failure loudly (see disconnect / _shutdown_channel).
    _SHUTDOWN_ATTEMPTS = 2

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
        """Ramp every touched channel to 0 V and switch it off, THEN close the link.

        Fail-safe — and it never fails *silently*.  The old path wrapped the
        ramp-down in ``except: pass`` and closed the socket regardless, so a
        supply that refused to come down was abandoned ENERGIZED with no trace
        in the log.  Now:

          * the ramp-down is retried once per channel (``_shutdown_channel``),
          * a channel that still will not come down is logged at ERROR and its
            local state is left truthful (NOT reset to "0 V / off" it never
            reached),
          * the transport is released only AFTER that best-effort teardown, so
            the handle is not leaked, and
          * a ``DeviceError`` naming the offending channels is raised, so the
            failure reaches the operator instead of being swallowed on the way
            out.

        Raising is safe here: ``DeviceManager.disconnect_all()`` logs and moves
        on to the next device (one bad supply cannot block the rest of teardown)
        and ``disconnect_device()`` returns the message to the UI — loud, without
        taking the app down.

        TODO(bench): on the lab's iseg module, confirm the teardown end-to-end —
        ramp a channel up into a dummy load, pull the USB/LAN link mid-teardown,
        and check that disconnect() reports the failure loudly (rather than
        exiting quietly) and that the module's own ramp-down still brings the
        channel to a safe state.
        """
        failures: list[str] = []
        if not self.simulation and self._inst is not None:
            # Primary channel first, then every OTHER channel this driver has
            # touched, so a multi-channel session never abandons a secondary
            # channel biased.  Single-channel use has no extra entries.
            for ch in [self._ch] + [c for c in self._ch_state if c != self._ch]:
                try:
                    self._shutdown_channel(ch)
                except Exception as exc:
                    failures.append(f"CH{ch} ({exc})")
                    self.logger.error(
                        "iseg CH%d: fail-safe ramp-down FAILED on disconnect after "
                        "%d attempts — THE OUTPUT MAY STILL BE ENERGIZED. Verify "
                        "the supply physically. Last error: %s",
                        ch, self._SHUTDOWN_ATTEMPTS, exc,
                    )
            # Release the link only AFTER the best-effort ramp-down above.
            try:
                self._inst.close()
            except Exception as exc:
                self.logger.warning("iseg: closing the VISA session failed: %s", exc)
            self._inst = None
        self._connected = False
        if failures:
            raise DeviceError(
                "iseg disconnect: fail-safe ramp-down FAILED for "
                + ", ".join(failures)
                + " — the output may still be energized. The link has been closed; "
                  "verify the supply physically before leaving the setup."
            )
        self.logger.info(
            "IsegBiasSupply disconnected (every touched channel ramped to 0 V and off)"
        )

    def _shutdown_channel(self, channel: int) -> None:
        """Ramp *channel* to 0 V and switch its output off — **raises** on failure.

        The fail-safe teardown primitive behind :meth:`disconnect`.  Deliberately
        does NOT go through :meth:`output_off_ch`, which swallows write errors so
        it stays usable from a ``finally`` block: here a failure MUST be visible,
        because the entire point is to prove the HV actually came down before the
        link is dropped.

        Retried once by the loop below.  Both commands are idempotent and drive
        the channel toward the SAME safe state (``:VOLT 0`` then ``:VOLT OFF``);
        neither can raise the voltage, so re-issuing them after a dropped frame —
        common on the USB-VCP transport — is safe (safety rule: retry only
        proven-safe operations).

        The ramp is skipped when the channel is already off: the base ``ramp_to``
        turns the output ON when it is off (to ramp *to* the target), which on a
        teardown path would mean ENABLING HV on an idle channel just to walk it
        to zero — an auto-HV-enable we must never do.  An off channel only needs
        the idempotent 0 V + OFF writes.

        Local state is updated only after the hardware has acknowledged.
        """
        last: Exception | None = None
        for attempt in range(self._SHUTDOWN_ATTEMPTS):
            try:
                if self.output_is_on_ch(channel):
                    # Walk the HV down gently while the output is still enabled.
                    self.ramp_to_ch(channel, 0.0)
                self._write(f":VOLT 0,(@{channel})")
                self._write(f":VOLT OFF,(@{channel})")
                st = self._chs(channel)
                st["output_on"] = False
                st["setpoint_V"] = 0.0
                self.logger.info(
                    "iseg CH%d ramped to 0 V and switched OFF (disconnect)", channel
                )
                return
            except Exception as exc:
                last = exc
                self.logger.warning(
                    "iseg CH%d: fail-safe ramp-down attempt %d/%d failed: %s",
                    channel, attempt + 1, self._SHUTDOWN_ATTEMPTS, exc,
                )
        raise DeviceError(
            f"ramp-down failed after {self._SHUTDOWN_ATTEMPTS} attempts: {last}"
        )

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
        """Command a new setpoint on *channel* (no ramp — internal use).

        Order matters: the hardware is written FIRST and the local setpoint is
        recorded only once that write is acknowledged.  Recording first (the old
        order) meant a failed/refused write still advanced the driver's idea of
        the setpoint — mid-ramp, that left it believing -295 V while the supply
        was still sitting at -300 V, and the next ramp then started from a lie.
        The base-class ``ramp_to`` already follows this write-then-record
        discipline; this brings the per-channel path in line with it.
        """
        self._require_connected()
        self.check_voltage_in_range(voltage_V)
        if not self.simulation:
            self._write(f":VOLT {voltage_V:.4f},(@{channel})")
        self._chs(channel)["setpoint_V"] = voltage_V

    def set_compliance_ch(self, channel: int, current_A: float) -> None:
        """Set the HV CURRENT LIMIT on *channel*.  Hardware FIRST, record after.

        Same write-then-record discipline as :meth:`set_voltage_ch`, and for a
        sharper reason: compliance IS the DUT's protection limit.  Recording
        first meant a failed/refused ``:CURR`` write still advanced the driver's
        belief — it would report a 10 µA limit while the module kept its old,
        possibly far higher one, and the scan's compliance/trip detection would
        then compare every reading against a limit the supply never took.  On
        failure the OLD value stays in place and the exception reaches the
        caller.
        """
        if not self.simulation:
            self._write(f":CURR {current_A:.4e},(@{channel})")
            self.logger.debug("iseg CH%d current limit %.3e A", channel, current_A)
        self._chs(channel)["compliance_A"] = current_A

    def output_on_ch(self, channel: int) -> None:
        self._require_connected()
        if not self.simulation:
            self._write(f":VOLT ON,(@{channel})")
        self._chs(channel)["output_on"] = True
        self.logger.info("iseg CH%d output ON", channel)

    def output_off_ch(self, channel: int) -> None:
        """Switch the channel output off.  Fail-safe: never raises.

        Abort / ``finally`` paths (scan_controller, MultiBiasPanel's ALL-OFF)
        depend on this not raising, so the non-raising contract is kept — but it
        must not *lie* either.  A write that FAILED no longer silently clears the
        local ``output_on`` flag (which would claim an OFF that was never
        achieved, exactly the stale-flag class of bug this driver is being
        hardened against): the failure is logged at ERROR and the local state is
        left as-is, so the UI keeps showing the channel as ON — which is the
        truth, because we do not know that it is off.
        """
        st = self._chs(channel)
        if not self.simulation and self._inst is not None:
            try:
                self._write(f":VOLT 0,(@{channel})")
                self._write(f":VOLT OFF,(@{channel})")
            except Exception as exc:
                self.logger.error(
                    "iseg CH%d: OUTPUT-OFF WRITE FAILED (%s) — the channel may "
                    "still be ENERGIZED; leaving local state ON rather than "
                    "claiming an OFF we never achieved.", channel, exc,
                )
                return
        st["output_on"] = False
        st["setpoint_V"] = 0.0
        self.logger.info("iseg CH%d output OFF", channel)

    def read_ch(self, channel: int) -> BiasReading:
        """Measure V/I **and** the channel status word.

        Reading ``:READ:CHAN:STAT?`` here is what makes a latched hardware trip
        visible: the module can switch a channel off on its own (over-current
        trip, arc error, emergency off) while this driver's local ``output_on``
        flag stays stale-True, so a V/I-only read reports a healthy-looking 0 V
        and nobody ever learns the HV tripped.  The decoded trip / hardware-on
        flags and the raw word ride out on the :class:`BiasReading`.

        Reacting to a trip is the controller's job, not the driver's — this only
        surfaces the truth (and logs it loudly).
        """
        st = self._chs(channel)
        if self.simulation:
            import random
            # Simulation has no module status word: leave the status fields at
            # their "unknown" default (None) rather than fabricating a healthy one.
            return BiasReading(
                voltage_V=st["setpoint_V"],
                current_A=st["setpoint_V"] * 1e-9 + random.gauss(0, 1e-11),
                compliant=False,
            )
        try:
            v = _parse_num(self._query(f":MEAS:VOLT? (@{channel})"))
            i = _parse_num(self._query(f":MEAS:CURR? (@{channel})"))
            # _channel_status never raises (returns None on error), so a status
            # hiccup can never break the V/I read that callers depend on.
            status = self._channel_status(channel)
            tripped, output_on_hw = self._decode_status(status)
            compliant = self._decode_compliant(status, i, st["compliance_A"])
            if tripped:
                self.logger.error(
                    "iseg CH%d: module reports a LATCHED FAULT (status=0x%X, "
                    "hardware output_on=%s, driver believed on=%s) — the HV is NOT "
                    "doing what was asked.  Check the supply.",
                    channel, status, output_on_hw, st["output_on"],
                )
            elif output_on_hw is False and st["output_on"]:
                self.logger.error(
                    "iseg CH%d: hardware reports the output OFF (status=0x%X) but "
                    "the driver believed it was ON — the channel switched off "
                    "behind our back (trip / inhibit / front panel).",
                    channel, status,
                )
            return BiasReading(
                voltage_V=v, current_A=i, compliant=compliant,
                status_word=status, tripped=tripped, output_on_hw=output_on_hw,
            )
        except Exception as exc:
            self.logger.warning("iseg read error: %s", exc)
            # Status stays None = UNKNOWN.  Never report a clean bill of health
            # for a channel we could not actually read.
            return BiasReading(voltage_V=st["setpoint_V"], current_A=float("nan"),
                               compliant=False)

    def _decode_status(self, status: int | None) -> tuple[bool | None, bool | None]:
        """Decode ``(tripped, output_on_hw)`` from a channel status word.

        Only bits whose meaning is grounded in the CITED bit map
        (docs/research/iseg_polarity_scpi.md §6, reproducing the iseg NHS/SHR
        Programmer's Manual channel-status register) are decoded — never invent
        bits.  Undecoded bits remain available to callers via the raw
        ``status_word`` on the reading.

        ``(None, None)`` means the status word could not be read: UNKNOWN, which
        callers must not treat as "known healthy".
        """
        if status is None:
            return None, None
        return (bool(status & self._STATUS_TRIP_MASK),
                bool(status & self._STATUS_IS_ON))

    def _decode_compliant(
        self, status: int | None, current_A: float, limit_A: float
    ) -> bool:
        """Is the channel in current compliance?

        The module publishes its own authoritative answer — bit 6 "Is Constant
        Current" (cited §6 table): the channel is current-controlled, i.e. it has
        given up holding the voltage in order to hold the current limit.  That is
        the ground truth and it is used whenever the status word is readable; the
        old current-vs-``compliance_A`` comparison could only ever be a guess
        against the driver's LOCAL idea of the limit.

        The measured-current comparison is kept as an OR, not replaced, and that
        is deliberate: ``compliance_A`` is the operator's DUT-protection limit
        from devices.yaml.  If the measured current reaches it while the module
        still considers itself voltage-controlled (its own hardware limit is
        higher — a front-panel change, or a limit write that never landed), the
        run must still trip.  Dropping the comparison would trade a false alarm
        for a MISSED one, and only one of those two burns a sensor.

        With no status word (None) the comparison is all there is.  NaN current
        (a failed measurement) is never "compliant".
        """
        over_limit = (current_A == current_A) and abs(current_A) >= limit_A * 0.99
        if status is None:
            return bool(over_limit)
        return bool(status & self._STATUS_IS_CONST_CURRENT) or bool(over_limit)

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
