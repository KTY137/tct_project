"""
Waveform generator driver (VISA / SCPI).

Controls the function/arbitrary waveform generator that supplies the
external trigger / repetition signal to the PDL 800 laser driver.

Config keys (devices.yaml → waveform_generator section):
    visa_address:  "USB0::..."
    frequency_hz:  1000
    pulse_width_s: 100e-9
    amplitude_V:   3.3
    offset_V:      0.0
    output_load:   50            # Ohm the generator assumes it drives (or INFinity/High-Z)
    output_channel: 1

Optional clean-square trigger (opt-in; both must be set):
    level_low_V:   0.0           # square "low" rail  (VOLT:LOW)
    level_high_V:  2.5           # square "high" rail (VOLT:HIGH) → 0..+2.5 V
When both are provided, connect() drives a defined ``low → high`` square via the
sourced VOLT:HIGH/VOLT:LOW path instead of amplitude+offset.  See
docs/research/pdl800_trigger_wavegen_lan.md.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .base import BaseDevice, DeviceError

logger = logging.getLogger(__name__)


# Vendor-specific SCPI command templates.  ``{ch}`` is the output channel and
# ``{val}`` the value.  The Rigol DG4000 dialect differs from the generic one
# for pulse width and amplitude — sending the generic forms to a DG4162 errors.
_WFG_CMDS: dict[str, dict[str, str]] = {
    # Rigol DG4000 series (DG4162).  Every command below is sourced from
    # docs/research/pdl800_trigger_wavegen_lan.md; page refs are to the RIGOL
    # DG4000 Series Programming Manual (ManualsLib 2521186).
    "rigol": {
        "function":        ":SOURce{ch}:FUNCtion PULSe",
        "function_square": ":SOURce{ch}:FUNCtion SQUare",       # square trigger (note Q2)
        "frequency":       ":SOURce{ch}:FREQuency {val:.6f}",
        "pulse_width":     ":SOURce{ch}:FUNCtion:PULSe:WIDTh {val:.3e}",
        # Duty cycle is stored PER-FUNCTION on the DG4000: the ACTIVE function's
        # node must be addressed.  Writing SQUare:DCYCle while the function is
        # PULSe touches the wrong register AND garbles the pulse width — verified
        # live on the real DG4162 (fw 00.01.14).  set_duty_cycle() queries the
        # active function and picks the matching node.  On PULSe, PULSe:DCYCle
        # 20/30/60 read back exactly (verified); the SQUare form stays the
        # manual-sourced one (note p.345) for the square-trigger path.
        "duty_pulse":      ":SOURce{ch}:FUNCtion:PULSe:DCYCle {val:.3f}",
        "duty_square":     ":SOURce{ch}:FUNCtion:SQUare:DCYCle {val:.3f}",
        # Read-back queries — the '?' counterparts of the SET nodes above.  Used
        # to store the value the instrument ACTUALLY applied: it silently clamps
        # duty/width to the frequency-dependent minimum pulse width.
        "function_q":      ":SOURce{ch}:FUNCtion?",
        "duty_pulse_q":    ":SOURce{ch}:FUNCtion:PULSe:DCYCle?",
        "duty_square_q":   ":SOURce{ch}:FUNCtion:SQUare:DCYCle?",
        "pulse_width_q":   ":SOURce{ch}:FUNCtion:PULSe:WIDTh?",
        # Amplitude (Vpp): short form of VOLTage[:LEVel][:IMMediate][:AMPLitude]
        # (note p.518).
        "amplitude":       ":SOURce{ch}:VOLTage {val:.4f}",
        # DC offset (note p.524).
        "offset":          ":SOURce{ch}:VOLTage:OFFSet {val:.4f}",
        # Explicit high/low rails — the unambiguous way to make a clean 0→+V
        # square with no half/sign arithmetic (note p.520 / p.523).
        "level_high":      ":SOURce{ch}:VOLTage:HIGH {val:.4f}",
        "level_low":       ":SOURce{ch}:VOLTage:LOW {val:.4f}",
        # Output load the generator assumes it drives (note p.202).  The DG4000
        # command is :OUTPut:LOAD, *not* :OUTPut:IMPedance (explicit in the
        # note).  If LOAD=High-Z (INFinity) but the cable drives the 50 Ω PDL
        # trigger input, the delivered voltage is HALF the displayed value.
        # "INFinity" = High-Z; must match the real cabling.
        "load":            ":OUTPut{ch}:LOAD {val}",
        "output_on":       ":OUTPut{ch}:STATe ON",
        "output_off":      ":OUTPut{ch}:STATe OFF",
        "burst_ncyc":      ":SOURce{ch}:BURSt:NCYCles {val}",
        "burst_on":        ":SOURce{ch}:BURSt:STATe ON",
        "burst_mode":      ":SOURce{ch}:BURSt:MODE TRIGgered",
        "trigger":         "*TRG",
    },
    # Siglent / Keysight 33xxx / Tektronix AFG (SCPI-99 standard forms; the
    # research note sources the Rigol dialect — these mirror the SCPI-99 nodes).
    "generic": {
        "function":        "SOURce{ch}:FUNCtion PULSe",
        "function_square": "SOURce{ch}:FUNCtion SQUare",
        "frequency":       "SOURce{ch}:FREQuency {val:.6f}",
        "pulse_width":     "SOURce{ch}:PULSe:WIDTh {val:.3e}",
        # Function-aware duty (mirrors the Rigol block; SCPI-99 / Keysight nodes).
        "duty_pulse":      "SOURce{ch}:FUNCtion:PULSe:DCYCle {val:.3f}",
        "duty_square":     "SOURce{ch}:FUNCtion:SQUare:DCYCle {val:.3f}",
        "function_q":      "SOURce{ch}:FUNCtion?",
        "duty_pulse_q":    "SOURce{ch}:FUNCtion:PULSe:DCYCle?",
        "duty_square_q":   "SOURce{ch}:FUNCtion:SQUare:DCYCle?",
        "pulse_width_q":   "SOURce{ch}:PULSe:WIDTh?",
        "amplitude":       "SOURce{ch}:VOLTage:AMPLitude {val:.4f}",
        "offset":          "SOURce{ch}:VOLTage:OFFSet {val:.4f}",
        "level_high":      "SOURce{ch}:VOLTage:HIGH {val:.4f}",
        "level_low":       "SOURce{ch}:VOLTage:LOW {val:.4f}",
        "load":            "OUTPut{ch}:LOAD {val}",
        "output_on":       "OUTPut{ch}:STATe ON",
        "output_off":      "OUTPut{ch}:STATe OFF",
        "burst_ncyc":      "SOURce{ch}:BURSt:NCYCles {val}",
        "burst_on":        "SOURce{ch}:BURSt:STATe ON",
        "burst_mode":      "SOURce{ch}:BURSt:MODE TRIGgered",
        "trigger":         "*TRG",
    },
}


def list_visa_resources() -> list[str]:
    """Return the VISA resource strings the active backend can see.

    Used by the GUI to discover e.g. the Rigol's USB address
    (``USB0::0x1AB1::0x0641::DG4xxxxxxxx::INSTR``).  Requires pyvisa **and** a
    VISA implementation (NI-VISA / Rigol UltraSigma / pyvisa-py).
    """
    try:
        import pyvisa  # type: ignore[import]
    except ImportError as exc:
        raise DeviceError("pyvisa is not installed.") from exc
    try:
        return list(pyvisa.ResourceManager().list_resources())
    except Exception as exc:
        raise DeviceError(
            f"No VISA backend found ({exc}). Install NI-VISA (or pyvisa-py)."
        ) from exc


def discover_lan_instruments(timeout: float = 2.5) -> list[str]:
    """Auto-discover LAN/LXI instruments via mDNS; return TCPIP VISA addresses.

    Browses the standard LXI service types (``_lxi``, ``_vxi-11``, ``_scpi-raw``,
    ``_hislip``).  Returns ``TCPIP0::<ip>::INSTR`` strings.  Requires the pure-
    Python ``zeroconf`` package.

    **Blocks for ``timeout`` seconds** (the browse window) — call it OFF the GUI
    thread, or it freezes the dialog.  On a **managed switch** mDNS multicast is
    frequently dropped by IGMP-snooping / multicast filtering, so this legitimately
    returns ``[]`` there; treat an empty result as "none found, enter the address
    manually", not as an error.
    """
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except ImportError as exc:
        raise DeviceError(
            "Auto-discovery needs the 'zeroconf' package (pip install zeroconf)."
        ) from exc

    found: dict[str, str] = {}

    class _Listener:
        def add_service(self, zc, type_, name):
            try:
                info = zc.get_service_info(type_, name, timeout=int(timeout * 1000))
            except Exception:
                return
            if not info:
                return
            for addr in info.parsed_addresses():
                if ":" not in addr:                      # IPv4 only
                    found[addr] = f"TCPIP0::{addr}::INSTR"

        def update_service(self, *_):  # required by the API
            pass

        def remove_service(self, *_):
            pass

    try:
        zc = Zeroconf()
    except Exception as exc:
        # No usable multicast interface (VPN/firewall/permission) — surface a
        # clean, actionable error instead of a raw OSError bubbling to the GUI.
        raise DeviceError(
            f"Could not start mDNS discovery ({exc}). Enter the instrument's "
            "IP / VISA address manually."
        ) from exc
    listener = _Listener()
    services = ["_lxi._tcp.local.", "_vxi-11._tcp.local.",
                "_scpi-raw._tcp.local.", "_hislip._tcp.local."]
    # Hold a reference to every ServiceBrowser for the whole browse window:
    # a dropped reference can be garbage-collected mid-scan, silently ending
    # discovery before anything is found.
    browsers: list[Any] = []
    try:
        for svc in services:
            browsers.append(ServiceBrowser(zc, svc, listener))
        time.sleep(timeout)
    finally:
        for b in browsers:
            try:
                b.cancel()
            except Exception:
                pass
        zc.close()
    return sorted(found.values())


class WaveformGenerator(BaseDevice):
    """
    SCPI waveform generator (Rigol DG4000, Siglent, Keysight 33xxx, Tek AFG …).

    *vendor* selects the SCPI dialect (see ``_WFG_CMDS``); default "rigol".
    """

    def __init__(
        self,
        visa_address: str = "",
        frequency_hz: float = 1000.0,
        pulse_width_s: float = 100e-9,
        amplitude_V: float = 3.3,
        offset_V: float = 0.0,
        output_load: str | float = "INFinity",
        output_channel: int = 1,
        level_low_V: float | None = None,
        level_high_V: float | None = None,
        vendor: str = "rigol",
        timeout_ms: int = 5000,
        simulation: bool = False,
    ) -> None:
        super().__init__(simulation=simulation)
        self._address = visa_address
        self._frequency = frequency_hz
        self._pulse_width = pulse_width_s
        # Last applied duty cycle (%).  Set by set_duty_cycle(); None until then
        # (the configured pulse is specified as a width, not a duty).  The laser
        # panel reflects this back into the duty spinbox after an apply so the
        # GUI shows what the instrument really did, not the rejected request.
        self._duty_cycle: float | None = None
        self._amplitude = amplitude_V
        self._offset = offset_V
        # Output load the generator is told it drives.  Default High-Z matches
        # a scope's 1 MΩ input; set to 50 for a 50Ω load. Getting this wrong is
        # a silent 2× amplitude error.
        self._output_load = output_load
        self._ch = output_channel
        # Optional explicit square rails (VOLT:HIGH / VOLT:LOW).  When BOTH are
        # provided, connect() drives a defined ``low → high`` square (e.g.
        # 0 → +2.5 V) for the PDL trigger instead of the amplitude+offset pulse.
        # Default None → unchanged legacy behaviour (amplitude+offset PULSe).
        self._level_low = level_low_V
        self._level_high = level_high_V
        self._vendor = vendor.lower() if vendor else "rigol"
        self._timeout_ms = int(timeout_ms)
        self._instr: Any = None
        self._rm: Any = None
        # Tri-state output record: True = on/armed, False = off, None = unknown.
        # It is the DRIVER's authoritative record of the last *commanded* state
        # (output_on/output_off), not a live query — the laser panel's armed
        # indicator reads it so it tracks real transitions (including
        # scan-thread arming) instead of independent button bookkeeping.
        # Starts None: until we command or read it back, the state is genuinely
        # unknown (real hardware can retain a prior ON state across sessions).
        self._output_on: bool | None = None

    # ------------------------------------------------------------------ #
    # BaseDevice                                                          #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            # Simulated hardware has no retained state — it is off until the
            # user (or a scan) explicitly enables it, so this is a known False.
            self._output_on = False
            logger.info("WaveformGenerator connected (simulation)")
            return
        try:
            import pyvisa  # type: ignore[import]
        except ImportError as exc:
            raise DeviceError("pyvisa is not installed.") from exc

        self._rm = pyvisa.ResourceManager()
        try:
            self._instr = self._rm.open_resource(self._address)
            self._instr.timeout = self._timeout_ms
            # Raw LAN sockets (TCPIP…::SOCKET) need an explicit line terminator;
            # USB / VXI-11 (::INSTR) do not.
            if "SOCKET" in self._address.upper():
                self._instr.read_termination = "\n"
                self._instr.write_termination = "\n"
        except Exception as exc:
            raise DeviceError(f"WaveformGenerator VISA open failed: {exc}") from exc

        idn = self._instr.query("*IDN?").strip()
        logger.info("WaveformGenerator connected (%s): %s", self._vendor, idn)
        self._apply_defaults()
        self._connected = True
        # _apply_defaults() does NOT touch the output on/off state (connecting
        # must never arm the laser trigger — safety rule), so the real output
        # state is whatever the instrument retained: leave it unknown (None) so
        # the panel shows "unknown" rather than a possibly-false "off".
        # TODO(manual needed): resolve the unknown into a real True/False by
        # reading the DG4000 output state on connect.  The research note
        # docs/research/pdl800_trigger_wavegen_lan.md sources the SET commands
        # (LOAD / VOLT / VOLT:HIGH / VOLT:LOW / SQU:DCYCle) but NOT an
        # output-state QUERY, so ":OUTPut{ch}:STATe?" (the SCPI-99 counterpart
        # of output_on/output_off) stays UNVERIFIED for the DG4162 — do not emit
        # it until the manual confirms the exact query form.  Until then the
        # panel shows an honest "unknown".

    def test_connection(self) -> str:
        """Query *IDN? and return the reply — confirms the VISA link."""
        if self.simulation:
            return (f"Simulation mode — waveform generator ({self._vendor}). "
                    "No hardware queried.")
        if not self._connected or self._instr is None:
            return "Not connected."
        try:
            return f"Waveform generator OK:\n{self._instr.query('*IDN?').strip()}"
        except Exception as exc:
            return f"*IDN? query failed: {exc}"

    def disconnect(self) -> None:
        if self._output_on:
            self.output_off()
        if self._instr is not None:
            try:
                self._instr.close()
            except Exception:
                pass
        self._connected = False

    # ------------------------------------------------------------------ #
    # Control interface                                                   #
    # ------------------------------------------------------------------ #

    def set_frequency(self, frequency_hz: float) -> None:
        self._frequency = frequency_hz
        self._send("frequency", val=frequency_hz)

    def set_pulse_width(self, width_s: float) -> None:
        """Set the pulse width (s) and store what the instrument ACTUALLY applied.

        The DG4162 enforces a frequency-dependent MINIMUM pulse width: e.g. at
        1 kHz a 200 ns request is silently applied as 3.125 µs (verified live);
        10 µs / 50 µs apply exactly.  The driver sends the request correctly,
        then reads the width back so ``self._pulse_width`` reflects reality and
        the laser panel can show the applied value instead of the rejected one.
        Warns (does not raise) when the instrument clamped the request.
        """
        requested = float(width_s)
        self._pulse_width = requested
        self._send("pulse_width", val=requested)
        applied = self._query_float(self._cmd("pulse_width_q"))
        if applied is not None:
            self._pulse_width = applied
            if abs(applied - requested) > max(1e-12, 1e-2 * abs(requested)):
                logger.warning(
                    "WFGEN pulse width applied %.6g s differs from requested "
                    "%.6g s — the instrument clamped it; the minimum pulse width "
                    "is frequency-dependent, raise the frequency or the width.",
                    applied, requested)

    @staticmethod
    def _square_duty_limits(freq_hz: float) -> tuple[float, float]:
        """DG4000 square-wave duty limits, frequency-dependent (note p.345):
        ≤10 MHz → 20–80 %; ≤40 MHz → 40–60 %; >40 MHz → locked 50 %."""
        if freq_hz <= 10e6:
            return (20.0, 80.0)
        if freq_hz <= 40e6:
            return (40.0, 60.0)
        return (50.0, 50.0)

    def _active_function(self) -> str:
        """Best-effort read of the active function; ``"SQU"`` or ``"PULSE"``.

        Queries ``:FUNCtion?`` and normalises the reply.  When there is no
        session (simulation / disconnected) or the query fails, falls back to
        ``"PULSE"`` — the driver's configured default (``_apply_defaults`` sends
        ``FUNCtion PULSe``) — so the duty write targets the node the device is
        actually on.  Anything that is not square is treated as pulse (a laser
        trigger is PULSe or SQUare only).
        """
        reply = self._query(self._cmd("function_q"))
        if reply and "SQU" in reply.upper():
            return "SQU"
        return "PULSE"

    def set_duty_cycle(self, percent: float) -> None:
        """Set the duty cycle (%), addressing the ACTIVE function's node.

        The DG4162 stores duty per-function: writing ``SQUare:DCYCle`` while the
        active function is PULSe touches the wrong register and garbles the pulse
        width (verified live, fw 00.01.14).  So we query the active function and
        pick the matching node:

          * SQUare → ``FUNCtion:SQUare:DCYCle`` + the frequency-dependent
            20–80/40–60/50 % clamp (docs/research/pdl800_trigger_wavegen_lan.md,
            manual p.345);
          * PULSe (default, and what a laser wants — LOW duty) →
            ``FUNCtion:PULSe:DCYCle`` with only a broad 0.001–99.999 % sanity
            clamp; the real floor is the frequency-dependent minimum pulse width,
            which the instrument itself enforces.

        After writing, reads the duty back so ``self._duty_cycle`` holds what the
        instrument ACTUALLY applied (the panel reflects it); warns on a clamp.
        """
        requested = float(percent)
        if self._active_function() == "SQU":
            lo, hi = self._square_duty_limits(self._frequency)
            commanded = max(lo, min(hi, requested))
            if commanded != requested:
                logger.warning(
                    "WFGEN square duty %.3f%% out of range for %.4g Hz; clamped "
                    "to %.3f%% (valid %.0f–%.0f%%, DG4000 manual p.345).",
                    requested, self._frequency, commanded, lo, hi)
            write_key, query_key = "duty_square", "duty_square_q"
        else:
            # PULSE: broad sanity clamp only — the instrument enforces the real,
            # frequency-dependent minimum (do NOT apply the SQUare 20–80 clamp;
            # a laser wants LOW duty, e.g. ~0.3 % at 1 kHz).
            commanded = max(0.001, min(99.999, requested))
            if commanded != requested:
                logger.warning(
                    "WFGEN pulse duty %.3f%% outside 0.001–99.999%%; clamped to "
                    "%.3f%%.", requested, commanded)
            write_key, query_key = "duty_pulse", "duty_pulse_q"
        self._duty_cycle = commanded
        self._send(write_key, val=commanded)
        applied = self._query_float(self._cmd(query_key))
        if applied is not None:
            self._duty_cycle = applied
            if abs(applied - commanded) > 0.05:
                logger.warning(
                    "WFGEN duty applied %.3f%% differs from requested %.3f%% — "
                    "the instrument clamped it; the duty floor is the "
                    "frequency-dependent minimum pulse width, raise the "
                    "frequency or the duty.", applied, commanded)

    def set_amplitude(self, amplitude_V: float) -> None:
        self._amplitude = amplitude_V
        self._send("amplitude", val=amplitude_V)

    def set_offset(self, offset_V: float) -> None:
        self._offset = offset_V
        self._send("offset", val=offset_V)

    def set_levels(self, low_V: float, high_V: float) -> None:
        """Define the square-wave rails directly (``VOLT:HIGH`` / ``VOLT:LOW``).

        The sourced, unambiguous way to make a clean ``low_V → high_V`` square —
        e.g. ``set_levels(0.0, 2.5)`` for a 0 → +2.5 V PDL trigger — avoiding the
        amplitude/offset half-arithmetic
        (docs/research/pdl800_trigger_wavegen_lan.md, manual p.520 / p.523).

        Does NOT enable the output (arming stays an explicit caller action).
        """
        low = float(low_V)
        high = float(high_V)
        if high <= low:
            raise DeviceError(
                f"set_levels: high ({high} V) must be greater than low ({low} V).")
        # PDL 800 trigger absolute-max is ±5 V at the connector (note Q1); warn
        # if a rail could exceed it (delivered value also depends on load match).
        if max(abs(low), abs(high)) > 5.0:
            logger.warning(
                "WFGEN level %.3f/%.3f V exceeds the PDL 800 trigger abs-max "
                "(±5 V); verify the load/attenuation before enabling output.",
                low, high)
        # Set HIGH before LOW so raising into a 0→+V window never transiently
        # places LOW above the old HIGH (which the instrument would reject).
        self._send("level_high", val=high)
        self._send("level_low", val=low)
        self._level_low, self._level_high = low, high
        # Keep amplitude/offset bookkeeping consistent for any UI that reads them.
        self._amplitude = high - low
        self._offset = (high + low) / 2.0

    def set_output_load(self, load: str | float) -> None:
        """Set the load impedance the generator assumes it drives.

        ``"INFinity"`` (High-Z, e.g. a scope's 1 MΩ input) or a number of ohms
        (e.g. ``50``). Must match the real load or the amplitude is off by up to
        2× — see the command-table note.
        """
        self._output_load = load
        val = load if isinstance(load, str) else f"{float(load):g}"
        self._send("load", val=val)

    def output_on(self) -> None:
        self._send("output_on")
        self._output_on = True
        logger.debug("WaveformGenerator CH%d output ON", self._ch)

    def output_off(self) -> None:
        self._send("output_off")
        self._output_on = False
        logger.debug("WaveformGenerator CH%d output OFF", self._ch)

    @property
    def output_is_on(self) -> bool | None:
        """Best-known output state: ``True`` on/armed, ``False`` off, ``None``
        unknown.

        The DRIVER's authoritative record of the last commanded state, not a
        live instrument query — so a UI armed indicator can track real
        transitions (button presses AND scan-thread arming) instead of keeping
        its own independent bookkeeping.  ``None`` means genuinely unknown (see
        the connect() note): freshly connected hardware may retain a prior ON
        state that was neither commanded here nor read back.
        """
        return self._output_on

    def burst(self, n_pulses: int) -> None:
        """Output exactly *n_pulses* pulses then stop."""
        self._send("burst_ncyc", val=n_pulses)
        self._send("burst_on")
        self._send("burst_mode")
        self._send("trigger")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _apply_defaults(self) -> None:
        # Load first: it changes how the generator interprets every voltage that
        # follows (High-Z vs 50 Ω is a silent up-to-2× error), so it must be set
        # before any amplitude/level command.  Never touches OUTPut:STATe —
        # connecting must not arm the trigger.
        self.set_output_load(self._output_load)
        if self._level_low is not None and self._level_high is not None:
            # Opt-in clean square trigger via explicit rails (note Q2).
            self._send("function_square")
            self.set_frequency(self._frequency)
            self.set_levels(self._level_low, self._level_high)
        else:
            # Legacy default: amplitude+offset PULSe (emitted output unchanged).
            self._send("function")
            self.set_frequency(self._frequency)
            self.set_pulse_width(self._pulse_width)
            self.set_amplitude(self._amplitude)
            self.set_offset(self._offset)

    def _cmd(self, key: str, **kw: Any) -> str | None:
        """Return the formatted vendor SCPI template for *key*, or None."""
        cmds = _WFG_CMDS.get(self._vendor, _WFG_CMDS["generic"])
        tmpl = cmds.get(key)
        return tmpl.format(ch=self._ch, **kw) if tmpl is not None else None

    def _send(self, key: str, **kw: Any) -> None:
        """Format a vendor SCPI template and write it."""
        cmd = self._cmd(key, **kw)
        if cmd is not None:
            self._write(cmd)

    def _write(self, cmd: str) -> None:
        if self.simulation:
            logger.debug("SIM WFGEN: %s", cmd)
            return
        if self._instr is not None:
            with self.io_lock:  # laser panel + scan thread share the session
                self._instr.write(cmd)

    def _query(self, cmd: str | None) -> str | None:
        """Query the instrument, guarded for sim / no-session / errors.

        Returns the stripped reply, or None when there is nothing to ask
        (simulation, no VISA session, missing template) or the query fails.
        Never raises — a read-back is best-effort and must never break a setter
        or arm anything.  Uses the shared io_lock like _write.
        """
        if cmd is None or self.simulation or self._instr is None:
            return None
        try:
            with self.io_lock:
                return str(self._instr.query(cmd)).strip()
        except Exception as exc:
            logger.debug("WFGEN query failed (%s): %s", cmd, exc)
            return None

    def _query_float(self, cmd: str | None) -> float | None:
        """Query and parse a single float; None if unavailable/non-numeric."""
        reply = self._query(cmd)
        if reply is None:
            return None
        try:
            return float(reply.split(",")[0])
        except (ValueError, IndexError):
            logger.debug("WFGEN non-numeric reply to %s: %r", cmd, reply)
            return None
