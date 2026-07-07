"""
Waveform generator driver (VISA / SCPI).

Controls the function/arbitrary waveform generator that supplies the
external trigger / repetition signal to the PDL 800 laser driver.

Config keys (devices.yaml → waveform_generator section):
    visa_address:  "USB0::..."
    frequency_hz:  1000
    pulse_width_s: 100e-9
    amplitude_V:   3.3
    output_channel: 1
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
    "rigol": {   # Rigol DG4000 series (DG4162) programming guide
        "function":    ":SOURce{ch}:FUNCtion PULSe",
        "frequency":   ":SOURce{ch}:FREQuency {val:.6f}",
        "pulse_width": ":SOURce{ch}:FUNCtion:PULSe:WIDTh {val:.3e}",
        "duty":        ":SOURce{ch}:FUNCtion:PULSe:DCYCle {val:.3f}",
        "amplitude":   ":SOURce{ch}:VOLTage {val:.4f}",
        "offset":      ":SOURce{ch}:VOLTage:OFFSet {val:.4f}",
        # Output load the generator assumes it is driving.  Rigol pre-halves
        # the amplitude for a 50Ω load; into a High-Z scope input that reads
        # 2× high, so this must match the real load.  "INFinity" = High-Z.
        "load":        ":OUTPut{ch}:IMPedance {val}",
        "output_on":   ":OUTPut{ch}:STATe ON",
        "output_off":  ":OUTPut{ch}:STATe OFF",
        "burst_ncyc":  ":SOURce{ch}:BURSt:NCYCles {val}",
        "burst_on":    ":SOURce{ch}:BURSt:STATe ON",
        "burst_mode":  ":SOURce{ch}:BURSt:MODE TRIGgered",
        "trigger":     "*TRG",
    },
    "generic": {  # Siglent / Keysight 33xxx / Tektronix AFG style
        "function":    "SOURce{ch}:FUNCtion PULSe",
        "frequency":   "SOURce{ch}:FREQuency {val:.6f}",
        "pulse_width": "SOURce{ch}:PULSe:WIDTh {val:.3e}",
        "duty":        "SOURce{ch}:FUNCtion:PULSe:DCYCle {val:.3f}",
        "amplitude":   "SOURce{ch}:VOLTage:AMPLitude {val:.4f}",
        "offset":      "SOURce{ch}:VOLTage:OFFSet {val:.4f}",
        "load":        "OUTPut{ch}:LOAD {val}",
        "output_on":   "OUTPut{ch}:STATe ON",
        "output_off":  "OUTPut{ch}:STATe OFF",
        "burst_ncyc":  "SOURce{ch}:BURSt:NCYCles {val}",
        "burst_on":    "SOURce{ch}:BURSt:STATe ON",
        "burst_mode":  "SOURce{ch}:BURSt:MODE TRIGgered",
        "trigger":     "*TRG",
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
        vendor: str = "rigol",
        timeout_ms: int = 5000,
        simulation: bool = False,
    ) -> None:
        super().__init__(simulation=simulation)
        self._address = visa_address
        self._frequency = frequency_hz
        self._pulse_width = pulse_width_s
        self._amplitude = amplitude_V
        self._offset = offset_V
        # Output load the generator is told it drives.  Default High-Z matches
        # a scope's 1 MΩ input; set to 50 for a 50Ω load. Getting this wrong is
        # a silent 2× amplitude error.
        self._output_load = output_load
        self._ch = output_channel
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
        # TODO(manual needed): read it back with the DG4000 output-state query
        # (":OUTPut{ch}:STATe?" is the SCPI-99 counterpart of the set command in
        # _WFG_CMDS but is unverified against the DG4162 manual) to resolve the
        # unknown into a real True/False on connect.

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
        self._pulse_width = width_s
        self._send("pulse_width", val=width_s)

    def set_duty_cycle(self, percent: float) -> None:
        """Set the pulse duty cycle in percent (0–100)."""
        self._duty_cycle = percent
        self._send("duty", val=percent)

    def set_amplitude(self, amplitude_V: float) -> None:
        self._amplitude = amplitude_V
        self._send("amplitude", val=amplitude_V)

    def set_offset(self, offset_V: float) -> None:
        self._offset = offset_V
        self._send("offset", val=offset_V)

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
        # Load first: it changes how the generator interprets the amplitude
        # that follows, so it must be set before set_amplitude.
        self.set_output_load(self._output_load)
        self._send("function")
        self.set_frequency(self._frequency)
        self.set_pulse_width(self._pulse_width)
        self.set_amplitude(self._amplitude)
        self.set_offset(self._offset)

    def _send(self, key: str, **kw: Any) -> None:
        """Format a vendor SCPI template and write it."""
        cmds = _WFG_CMDS.get(self._vendor, _WFG_CMDS["generic"])
        tmpl = cmds.get(key)
        if tmpl is not None:
            self._write(tmpl.format(ch=self._ch, **kw))

    def _write(self, cmd: str) -> None:
        if self.simulation:
            logger.debug("SIM WFGEN: %s", cmd)
            return
        if self._instr is not None:
            with self.io_lock:  # laser panel + scan thread share the session
                self._instr.write(cmd)
