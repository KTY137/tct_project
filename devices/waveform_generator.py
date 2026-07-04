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

    zc = Zeroconf()
    listener = _Listener()
    services = ["_lxi._tcp.local.", "_vxi-11._tcp.local.",
                "_scpi-raw._tcp.local.", "_hislip._tcp.local."]
    try:
        for svc in services:
            ServiceBrowser(zc, svc, listener)
        time.sleep(timeout)
    finally:
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
        self._ch = output_channel
        self._vendor = vendor.lower() if vendor else "rigol"
        self._timeout_ms = int(timeout_ms)
        self._instr: Any = None
        self._rm: Any = None
        self._output_on = False

    # ------------------------------------------------------------------ #
    # BaseDevice                                                          #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
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

    def output_on(self) -> None:
        self._send("output_on")
        self._output_on = True
        logger.debug("WaveformGenerator CH%d output ON", self._ch)

    def output_off(self) -> None:
        self._send("output_off")
        self._output_on = False
        logger.debug("WaveformGenerator CH%d output OFF", self._ch)

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
        self._send("function")
        self.set_frequency(self._frequency)
        self.set_pulse_width(self._pulse_width)
        self.set_amplitude(self._amplitude)

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
