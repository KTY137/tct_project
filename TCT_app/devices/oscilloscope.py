"""
Oscilloscope driver (VISA / PyVISA).

Supports any SCPI-compatible oscilloscope (Tektronix, Keysight, Rigol,
LeCroy / Teledyne, R&S) with a single class, routing vendor-specific
quirks through a thin _backend layer.

Config keys (devices.yaml → oscilloscope section):
    visa_address:     "USB0::0x0699::0x0368::C012345::INSTR"
    vendor:           "tektronix" | "keysight" | "rigol" | "lecroy"
    n_averages:       16
    timeout_ms:       10000
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import numpy as np

from .base import BaseDevice, DeviceError

logger = logging.getLogger(__name__)
io_logger = logging.getLogger("tct.device_io")

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?")

# Tektronix model → channel count heuristic: the last digit of the model
# number is the analog channel count across the modern TBS/DPO/MSO/MDO lines
# (TBS1052C → 2, MSO5204B → 4).  Used ONLY as a fallback when devices.yaml
# doesn't set n_channels; read_channel's SELect? precheck stops a wrong guess
# from wedging the scope, at worst it hides a real channel from the panel.
# NOTE: unreliable on some older TDS models where the last digit isn't the
# channel count (e.g. TDS1001/TDS1002 are both 2-channel), so TDS is
# deliberately excluded — set n_channels explicitly for those.
_TEK_MODEL_RE = re.compile(r"\b(?:TBS|DPO|MSO|MDO)\s*(\d{3,4})", re.I)


def tek_channel_count_from_idn(idn: str) -> int | None:
    """Best-effort analog channel count from a Tektronix *IDN? reply.

    Returns None when the model isn't recognised — the caller then keeps its
    default rather than guessing.  Prefer the explicit ``n_channels`` config
    key; this only spares the common case of forgetting to set it.
    """
    m = _TEK_MODEL_RE.search(idn or "")
    if not m:
        return None
    last = int(m.group(1)[-1])
    return last if 1 <= last <= 4 else None

# Mapping of vendor names to channel-data query format strings.
# Each entry: (waveform_cmd, preamble_cmd)
_VENDOR_CMDS: dict[str, dict[str, str]] = {
    "tektronix": {
        "data_src":  "DATA:SOURCE CH{ch}",
        "data_enc":  "DATA:ENCDG RIBINARY",
        # Force 1 byte/sample so the signed-byte (datatype="b") decode below is
        # always correct.  Without this the scope may still be in 2-byte mode
        # (DATA:WIDTH 2) from a prior session, and CURVE? then returns twice as
        # many bytes that get misread as garbage — a blank/nonsense waveform.
        # Matches the Tektronix reference example (wfmoutpre:byt_n 1).
        "data_width":"DATA:WIDTH 1",
        "data_start":"DATA:START 1",
        "data_stop": "DATA:STOP 1000000",
        "wfm_query": "CURVE?",
        "pre_query": "WFMPRE?",
    },
    "keysight": {
        "data_src":  ":WAVeform:SOURce CHANnel{ch}",
        "data_enc":  ":WAVeform:FORMat WORD",
        "data_width":"",
        "data_start":"",
        "data_stop": "",
        "wfm_query": ":WAVeform:DATA?",
        "pre_query": ":WAVeform:PREamble?",
    },
    "rigol": {
        "data_src":  ":WAVeform:SOURce CHAN{ch}",
        "data_enc":  ":WAVeform:FORMat BYTE",
        "data_width":"",
        "data_start":"",
        "data_stop": "",
        "wfm_query": ":WAVeform:DATA?",
        "pre_query": ":WAVeform:PREamble?",
    },
    # LeCroy / Teledyne-LeCroy WaveRunner, WavePro, HDO series
    # Uses COMM_FORMAT DEF9,WORD,BIN and C{ch}:WF? DAT1
    # Preamble fields are read separately via INSP? queries
    "lecroy": {
        "data_src":  "",           # handled specially in read_channel
        "data_enc":  "COMM_FORMAT DEF9,WORD,BIN;COMM_ORDER LO",
        "data_width":"",
        "data_start":"",
        "data_stop": "",
        "wfm_query": "C{ch}:WF? DAT1",
        "pre_query": "",          # handled specially via _lecroy_preamble()
    },
}


class Oscilloscope(BaseDevice):
    """
    VISA oscilloscope driver with vendor-agnostic waveform acquisition.

    Usage
    -----
    scope = Oscilloscope(visa_address="TCPIP::192.168.1.10::INSTR", vendor="keysight")
    scope.connect()
    time_s, volts = scope.read_channel(1)
    """

    def __init__(
        self,
        visa_address: str = "",
        vendor: str = "tektronix",
        n_averages: int = 1,
        timeout_ms: int = 10000,
        trigger_source: str = "EXT",
        trigger_level_V: float = -0.41,
        trigger_slope: str = "FALL",
        n_channels: int | None = None,
        simulation: bool = False,
    ) -> None:
        """Construct the driver (no hardware I/O — connect() opens the link).

        Channel-count precedence (resolved on connect, see
        :meth:`_apply_channel_count_from_idn`):
            explicit config (clamped down to a detected capability)
            > *IDN? detection
            > default 4.
        An explicit ``n_channels`` is honored as-is when it is at or below the
        instrument's detected capability (asking for FEWER channels than the
        hardware has is a legitimate user choice).  It is clamped DOWN — with a
        warning — only when it EXCEEDS the capability *IDN? proves the scope
        has, because querying a nonexistent channel wedges the VISA session
        (bench 2026-07-06: CH3/CH4 on a 2-channel TBS1052C).  Unknown models
        (detection returns None) leave the explicit config untouched.
        """
        super().__init__(simulation=simulation)
        self._address = visa_address
        self._vendor = vendor.lower()
        self._n_averages = max(int(n_averages), 1)
        self._timeout_ms = timeout_ms
        # Channel count: explicit config wins but is clamped to the detected
        # hardware capability on connect (see _apply_channel_count_from_idn).
        self._n_channels_cfg = int(n_channels) if n_channels else None
        self.n_channels = self._n_channels_cfg if self._n_channels_cfg else 4
        # Trigger configuration (applied on connect; editable via the panel's
        # Trigger Settings window).
        self.trig_source = str(trigger_source)
        self.trig_level_V = float(trigger_level_V)
        self.trig_slope = str(trigger_slope)
        self._instr: Any = None
        self._rm: Any = None
        self._cmds = _VENDOR_CMDS.get(self._vendor, _VENDOR_CMDS["tektronix"])

    # ------------------------------------------------------------------ #
    # BaseDevice                                                          #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            logger.info("Oscilloscope connected (simulation)")
            return
        try:
            import pyvisa  # type: ignore[import]
        except ImportError as exc:
            raise DeviceError("pyvisa is not installed. Run: pip install pyvisa") from exc

        try:
            # RM construction inside the try so a missing/broken VISA backend
            # surfaces as the same DeviceError as an open failure.
            self._rm = pyvisa.ResourceManager()
            # open_timeout caps viOpen — the connection-ESTABLISHMENT wait,
            # distinct from self._instr.timeout (the per-operation I/O timeout
            # set just below, effective only AFTER the link is open).  Without
            # it an offline/unreachable TCPIP…::INSTR target blocks inside
            # viOpen at the OS/VISA level for the full socket window (tens of
            # seconds to minutes) and freezes the connect worker — the same
            # unbounded-open freeze fixed for the wavegen in 7b4ea94.  pyvisa
            # forwards open_timeout (ms) straight to viOpen.
            # TODO(bench): confirm NI-VISA honors open_timeout on the real
            # scope's VXI-11 / raw-SOCKET link when the instrument is powered
            # off — it can only shorten today's unbounded block, never lengthen
            # it.
            self._instr = self._rm.open_resource(
                self._address, open_timeout=self._timeout_ms)
            self._instr.timeout = self._timeout_ms
            # Raw LAN sockets (TCPIP…::SOCKET) have no message framing — queries
            # hang without an explicit terminator.  USB / VXI-11 (::INSTR) don't
            # need this.
            if "SOCKET" in self._address.upper():
                self._instr.read_termination = "\n"
                self._instr.write_termination = "\n"
        except Exception as exc:
            # Fail safe (rule 5): a failed / timed-out open must leave no
            # half-open session or ResourceManager behind and must not keep a
            # stale _connected True over a dead link on a reconnect.  Close under
            # io_lock, exactly as disconnect() does: on a RECONNECT open failure
            # self._instr still points at the OLD session, and is_alive() probes
            # that handle with *STB? under this same lock from the liveness
            # thread — closing it unlocked would race a concurrent probe (the
            # cross-thread use/close-of-one-VISA-session crash 7b4ea94 fixed for
            # the wavegen).  io_lock is re-entrant; connect() does not already
            # hold it, and the liveness probe acquires it non-blocking.
            with self.io_lock:
                if self._instr is not None:
                    try:
                        self._instr.close()
                    except Exception:
                        pass
                    self._instr = None
                if self._rm is not None:
                    try:
                        self._rm.close()
                    except Exception:
                        pass
                    self._rm = None
            self._connected = False
            raise DeviceError(f"Oscilloscope VISA open failed: {exc}") from exc

        # *CLS (IEEE 488.2) clears stale events/status from earlier sessions so
        # our own error checks below only see errors we caused.
        try:
            self._instr.write("*CLS")
        except Exception:
            pass
        # Force bare (non-headed) query replies on Tektronix.  HEADer is a
        # persisted instrument setting; with HEADer ON, "SELect:CH1?" answers
        # ":SELECT:CH1 0" instead of "0", which would silently defeat the
        # channel-active precheck in read_channel and re-wedge the scope.
        # Doing it here makes every query in this driver deterministic.
        if self._vendor == "tektronix":
            try:
                self._instr.write("HEADer OFF")
                self._instr.write("VERBose OFF")
            except Exception as exc:
                logger.warning("Could not set HEADer/VERBose OFF: %s", exc)

        idn = self._query_text("*IDN?").strip()
        logger.info("Oscilloscope connected: %s", idn)
        self._idn = idn
        self._apply_channel_count_from_idn(idn)
        self._connected = True
        # Apply the configured trigger (previously this was never sent).
        try:
            self.configure_tct_trigger(self.trig_source, self.trig_level_V, self.trig_slope)
        except Exception as exc:
            logger.warning("Trigger config on connect failed: %s", exc)
        # Apply the configured acquisition averaging (n_averages was previously
        # read from devices.yaml but never sent to the instrument).
        try:
            self.set_averaging(self._n_averages)
        except Exception as exc:
            logger.warning("Averaging config on connect failed: %s", exc)

    def _apply_channel_count_from_idn(self, idn: str) -> None:
        """Resolve ``self.n_channels`` from the *IDN? reply and the config.

        Precedence (see the constructor docstring): explicit config, clamped
        down to a detected capability, > detection > default 4.

        * No explicit config: a recognised model's channel count refines the
          default; an unknown model keeps the default.
        * Explicit config at/below the detected capability: honored verbatim
          (fewer channels than the hardware has is a valid user choice).
        * Explicit config ABOVE the detected capability: clamped down to the
          capability with a warning — querying a nonexistent channel wedges the
          VISA session (bench 2026-07-06, CH3/CH4 on a 2-channel TBS1052C).

        Reads only the passed string; performs no I/O.
        """
        detected = tek_channel_count_from_idn(idn)
        if not self._n_channels_cfg:
            if detected:
                self.n_channels = detected
                logger.info("Oscilloscope channel count from *IDN?: %d", detected)
            return
        if detected and self._n_channels_cfg > detected:
            logger.warning(
                "Config n_channels=%d exceeds the %d-channel capability "
                "detected from *IDN? (%s) — clamping to %d to avoid wedging "
                "the VISA session on a nonexistent channel.",
                self._n_channels_cfg, detected, idn, detected,
            )
            self.n_channels = detected
        else:
            # Config honored as-is (unknown model, or config <= capability).
            self.n_channels = self._n_channels_cfg

    def test_connection(self) -> str:
        """Query *IDN? and return the reply — confirms the VISA link."""
        if self.simulation:
            return (f"Simulation mode — oscilloscope ({self._vendor}). "
                    "No hardware queried.")
        if not self._connected or self._instr is None:
            return "Not connected."
        try:
            return f"Oscilloscope OK:\n{self._query_text('*IDN?').strip()}"
        except Exception as exc:
            return f"*IDN? query failed: {exc}"

    def disconnect(self) -> None:
        # Hold io_lock so close() can't race a query on a poller/scan thread
        # (cross-thread close vs query on one VISA handle is undefined at the
        # backend level — it can hang or crash, not just raise).
        with self.io_lock:
            if self._instr is not None:
                try:
                    self._instr.close()
                except Exception:
                    pass
            self._instr = None
            self._connected = False

    def is_alive(self) -> bool:
        """Verify the VISA link with an IEEE 488.2 ``*STB?`` heartbeat.

        Called periodically by the liveness monitor so an unplugged/powered-
        off scope flips to DISCONNECTED instead of keeping a stale green
        flag.  Non-contending: if another thread holds the io_lock the scope
        is mid-conversation and is reported alive without probing.
        """
        if self.simulation or not self._connected:
            return self._connected
        if self._instr is None:
            self._connected = False
            return False
        if not self.io_lock.acquire(blocking=False):
            return True
        try:
            old_timeout = self._instr.timeout
            try:
                self._instr.timeout = 1000
                self._instr.query("*STB?")
                return True
            finally:
                try:
                    self._instr.timeout = old_timeout
                except Exception:
                    pass
        except Exception as exc:
            logger.error("Oscilloscope liveness check failed — marking "
                         "disconnected: %s", exc)
            self._connected = False
            return False
        finally:
            self.io_lock.release()

    # ------------------------------------------------------------------ #
    # Acquisition                                                         #
    # ------------------------------------------------------------------ #

    def configure_tct_trigger(
        self,
        source: str = "EXT",
        level_V: float = -0.41,
        slope: str = "FALL",
    ) -> None:
        """
        Configure external trigger for TCT acquisition.

        Defaults match the UZH TCT setup convention:
          - External trigger, negative (falling) edge at -410 mV.
          - PDL 800 SYNC.OUT is negative-polarity; adjust level_V if needed.
        """
        # Remember the applied values so the Trigger window reflects them.
        self.trig_source, self.trig_level_V, self.trig_slope = source, float(level_V), slope
        if self.simulation:
            return
        if self._vendor == "lecroy":
            # LeCroy SCPI trigger
            slope_str = "NEG" if slope in ("FALL", "NEG") else "POS"
            self._write(
                f"TRIG_SELECT EDGE,SR,{source},"
                f"SLOPE,{slope_str},LEVEL,{level_V}V"
            )
            self._write("TRIG_MODE NORM")
        else:
            # Tektronix "A trigger" tree.  The previous bare forms
            # (TRIGger:MODE/SOURce/LEVel/SLOPe) are rejected with
            # "Undefined header" on the TBS1000C family — confirmed live on
            # the lab's TBS1052C, whose TRIGger:A:* tree answers all the
            # matching queries (see docs/research/tbs1000c_scpi.md).
            src = str(source).upper()
            slope_str = "FALL" if str(slope).upper() in ("FALL", "NEG") else "RISe"
            self._write("TRIGger:A:TYPe EDGE")
            self._write("TRIGger:A:MODe NORMal")
            self._write(f"TRIGger:A:EDGE:SOUrce {src}")
            self._write(f"TRIGger:A:EDGE:SLOpe {slope_str}")
            if src.startswith("CH"):
                # Channel sources keep independent levels on this family.
                self._write(f"TRIGger:A:LEVel:{src} {level_V}")
            else:
                self._write(f"TRIGger:A:LEVel {level_V}")
            self._check_scpi_errors("trigger config")

    def _query_preamble(self) -> str:
        """Query the waveform preamble, tolerating Tektronix model differences.

        4000-series scopes use ``WFMOutpre?`` while older ones (e.g. TBS 1000C)
        use ``WFMPre?``; try both so the same ``vendor: tektronix`` works over USB
        and LAN.
        """
        candidates = (["WFMOutpre?", "WFMPRE?"] if self._vendor == "tektronix"
                      else [self._cmds["pre_query"]])
        for q in candidates:
            if not q:
                continue
            try:
                s = self._query_text(q)
                if s and s.strip():
                    return s
            except Exception:
                # Unwedge before trying the next candidate — a failed query
                # otherwise garbles the following reply (observed on TBS1052C).
                self._recover_session()
                continue
        return self._query_text(self._cmds["pre_query"])

    def set_channel_scale(self, channel: int, volts_per_div: float) -> None:
        """Set the vertical scale (Tektronix ``CH<x>:SCAle``).

        Vendor-guarded exactly like the sibling setters (set_coupling /
        set_bandwidth_limit / set_probe_attenuation / set_channel_display): the
        command form is only verified for Tektronix, so any other vendor gets a
        clear refusal instead of a silently-wrong write.  Previously this fired
        Tektronix SCPI at Keysight/Rigol/LeCroy unconditionally, where
        ``CH1:SCAle`` is not the vertical-scale header at all — the write was
        simply rejected and the scope kept its old scale while the app believed
        the new one had been applied.
        """
        if self.simulation:
            # Simulated instrument state: with no hardware, the scope's scale IS
            # whatever was last set.  Recorded ONLY here (never on a real
            # backend), so read_settings can never echo a request as a readback.
            self._last_vdiv = volts_per_div
            return
        if self._vendor != "tektronix":
            raise DeviceError(
                f"set_channel_scale is not implemented for vendor "
                f"'{self._vendor}' — command not verified against a manual."
            )
        with self.io_lock:
            self._write(f"CH{channel}:SCAle {volts_per_div}")
            self._check_scpi_errors("channel scale")

    def set_channel_position(self, channel: int, divisions: float) -> None:
        """Vertical trace position, in divisions (Tektronix CH:POSition)."""
        self._write(f"CH{channel}:POSition {divisions}")

    def set_probe_attenuation(self, channel: int, factor: float) -> None:
        """Tell the scope the probe attenuation factor (1×, 10×, 100×, …).

        Tektronix models this as a *gain* = 1/factor (a 10× probe → gain 0.1).
        Getting this wrong is silent and multiplies every reading by the ratio:
        a direct BNC cable (1×) on a channel left at gain 0.1 makes waveforms
        read 10× too large — the 2026-07-06 bench "wrong scale" bug. Verify with
        read_settings()['probe_gain'].
        """
        if self.simulation:
            self._last_probe_factor = factor
            return
        if self._vendor != "tektronix":
            raise DeviceError(
                f"set_probe_attenuation not verified for vendor '{self._vendor}'."
            )
        if factor <= 0:
            raise DeviceError("Probe attenuation factor must be positive.")
        with self.io_lock:
            self._write(f"CH{channel}:PRObe:GAIN {1.0 / factor:.6g}")
            self._check_scpi_errors("probe attenuation")

    def set_coupling(self, channel: int, coupling: str) -> None:
        """Set channel input coupling: 'DC' | 'AC' | 'GND' (Tektronix CH:COUPling)."""
        c = str(coupling).upper()
        if c not in ("DC", "AC", "GND"):
            raise DeviceError(f"Invalid coupling '{coupling}' (use DC/AC/GND).")
        if self.simulation:
            return
        with self.io_lock:
            self._write(f"CH{channel}:COUPling {c}")
            self._check_scpi_errors("coupling")

    def set_bandwidth_limit(self, channel: int, limit: str) -> None:
        """Set channel bandwidth limit: 'FULL' or 'TWENTY' (20 MHz) — Tektronix
        ``CH<x>:BANdwidth``. Reduces high-frequency noise on slow signals."""
        lim = str(limit).upper()
        arg = "TWEnty" if lim in ("TWENTY", "TWE", "20", "20MHZ") else "FULl"
        if self.simulation:
            return
        with self.io_lock:
            self._write(f"CH{channel}:BANdwidth {arg}")
            self._check_scpi_errors("bandwidth limit")

    def set_timebase(self, time_per_div_s: float) -> None:
        """Set the horizontal scale (Tektronix ``HORizontal:SCAle``).

        Vendor-guarded exactly like ``set_channel_scale`` and the other sibling
        setters — see that docstring for why an unguarded write is worse than a
        refusal.
        """
        if self.simulation:
            # Simulated instrument state — see set_channel_scale.
            self._last_tdiv = time_per_div_s
            return
        if self._vendor != "tektronix":
            raise DeviceError(
                f"set_timebase is not implemented for vendor "
                f"'{self._vendor}' — command not verified against a manual."
            )
        with self.io_lock:
            self._write(f"HORizontal:SCAle {time_per_div_s}")
            self._check_scpi_errors("timebase")

    def read_settings(self) -> dict:
        """Read the instrument's current display / trigger settings (best effort).

        Tektronix SCPI; returns any of ``tdiv``, ``vdiv``, ``voff_div``,
        ``trig_level`` that could be queried.

        Honesty contract: every value returned here is a genuine READBACK.  In
        simulation the returned tdiv/vdiv are the simulated instrument's state
        (there is no hardware, so what was set IS what it reads back — truthful
        for a simulated scope).  On a REAL backend with no open session, nothing
        is returned at all: the previous code echoed the last *requested* vdiv /
        tdiv back to the caller as though it had been read off the instrument,
        so a scale that a rejected/never-sent write had failed to apply still
        showed up in the panel as the scope's current setting.
        """
        if self.simulation:
            out = {}
            if getattr(self, "_last_tdiv", None):
                out["tdiv"] = self._last_tdiv
            if getattr(self, "_last_vdiv", None):
                out["vdiv"] = self._last_vdiv
            return out
        if self._instr is None:
            # Real backend, no session: report nothing rather than passing a
            # requested value off as an instrument readback.
            return {}

        def q(cmd: str):
            try:
                return float(self._query_text(cmd))
            except Exception:
                # A timed-out query leaves the output queue unterminated on
                # Tek USB scopes — clear it so the next query isn't garbled.
                self._recover_session()
                return None

        out: dict = {}
        tdiv = q("HORizontal:SCAle?")
        if tdiv:
            out["tdiv"] = tdiv
        vdiv = q("CH2:SCAle?") or q("CH1:SCAle?")
        if vdiv:
            out["vdiv"] = vdiv
        pos = q("CH2:POSition?")
        if pos is not None:
            out["voff_div"] = pos
        # A-tree first: valid on the TBS1000C family (the MAIn tree is the
        # older TDS fallback and times out on TBS, wedging the session).
        lvl = q("TRIGger:A:LEVel?")
        if lvl is None:
            lvl = q("TRIGger:MAIn:LEVel?")
        if lvl is not None:
            out["trig_level"] = lvl
        # Probe gain (0.1 == 10× probe) — surfaced so the panel can warn when a
        # channel is scaled as if a probe is attached to a bare BNC cable.
        gain = q("CH1:PRObe:GAIN?")
        if gain and gain > 0:
            out["probe_gain"] = gain
            out["probe_factor"] = round(1.0 / gain, 3)
        try:
            parts = self._query_text("CH1:COUPling?").strip().split()
            if parts:                      # guard: empty reply must not IndexError
                out["coupling"] = parts[-1]
        except Exception:
            self._recover_session()
        return out

    def acquire(self) -> None:
        """Arm the oscilloscope for a single triggered acquisition."""
        if self.simulation:
            return
        with self.io_lock:
            self._write("ACQuire:STOPAfter SEQuence")
            self._write("ACQuire:STATE RUN")

    def read_channel(self, channel: int) -> tuple[np.ndarray, np.ndarray]:
        """
        Return (time_s, voltage_V) numpy arrays for *channel* (1-indexed).

        Raises DeviceError if the waveform contains NaN values, which
        indicates the signal exceeded the vertical scale (UZH troubleshooting
        note: increase V/div on the oscilloscope).
        """
        if self.simulation:
            return self._simulated_waveform()

        # io_lock: the scope-panel live view (poller thread) and the scan
        # thread share this VISA session — an interleaved CURVE?/WFMPRE? pair
        # garbles both replies.
        with self.io_lock:
            if self._vendor == "lecroy":
                return self._read_channel_lecroy(channel)

            if self._vendor == "tektronix":
                # Fail fast if the channel isn't displayed: CURVE? on an
                # inactive source doesn't just error, it times out AND leaves
                # the output queue unterminated, so every later query returns
                # garbage until a device clear (observed live on TBS1052C,
                # event 2244 "Source waveform is not active").
                try:
                    sel = self._query_text(f"SELect:CH{channel}?").strip()
                except Exception as exc:
                    self._recover_session()
                    raise DeviceError(
                        f"CH{channel} state query failed — does this "
                        f"oscilloscope have a CH{channel}? ({exc})"
                    ) from exc
                # Parse the last whitespace token so this holds even if HEADer
                # is ON (":SELECT:CH1 0") despite the connect-time HEADer OFF.
                token = sel.split()[-1].upper() if sel.split() else sel.upper()
                if token in ("0", "OFF"):
                    raise DeviceError(
                        f"CH{channel} is not active on the oscilloscope "
                        "(display off). Toggle the channel on in the panel "
                        "or press the channel button on the scope."
                    )

            cmds = self._cmds
            try:
                if cmds["data_src"]:
                    self._write(cmds["data_src"].format(ch=channel))
                if cmds["data_enc"]:
                    self._write(cmds["data_enc"])
                if cmds.get("data_width"):
                    self._write(cmds["data_width"])
                if cmds["data_start"]:
                    self._write(cmds["data_start"])
                if cmds["data_stop"]:
                    self._write(cmds["data_stop"])

                raw = self._query_binary_values(
                    cmds["wfm_query"], datatype="b", is_big_endian=True
                )
                preamble_str = self._query_preamble()
            except DeviceError:
                raise
            except Exception as exc:
                self._recover_session()
                raise DeviceError(
                    f"CH{channel} waveform read failed: {exc}"
                ) from exc
        time_s, voltage_V = self._parse_waveform(np.array(raw), preamble_str)
        self._check_clipping(voltage_V, channel)
        return time_s, voltage_V

    def set_channel_display(self, channel: int, on: bool) -> None:
        """Turn a channel's display on/off (a channel must be active for
        CURVE? to return data — see read_channel).

        Tektronix ``SELect:CH<x> {ON|OFF}``; the query form is confirmed live
        on the TBS1052C and the set form is in the TBS1000C programmer manual
        (docs/research/tbs1000c_scpi.md).
        """
        if self.simulation:
            return
        if self._vendor != "tektronix":
            raise DeviceError(
                f"set_channel_display is not implemented for vendor "
                f"'{self._vendor}' — command not verified against a manual."
            )
        self._write(f"SELect:CH{channel} {'ON' if on else 'OFF'}")
        self._check_scpi_errors("channel display")

    def set_averaging(self, n_averages: int) -> None:
        """Set scope-side acquisition averaging (1 = plain sample mode).

        Tektronix ``ACQuire:MODe SAMple|AVErage`` + ``ACQuire:NUMAVg`` — the
        same sequence used working in oscilloscope_tek_fastframe.py
        (Dustin's MSO5204B toolkit); both query forms answer live on the
        TBS1052C.  Other vendors: not implemented, logged instead of guessed.
        """
        n = max(int(n_averages), 1)
        self._n_averages = n
        if self.simulation:
            return
        if self._vendor != "tektronix":
            logger.warning(
                "set_averaging not implemented for vendor '%s' — command "
                "not verified against a manual; scope left unchanged.",
                self._vendor,
            )
            return
        with self.io_lock:
            if n <= 1:
                self._write("ACQuire:MODe SAMple")
            else:
                self._write("ACQuire:MODe AVErage")
                self._write(f"ACQuire:NUMAVg {n}")
            self._check_scpi_errors("averaging config")

    @property
    def n_averages(self) -> int:
        return self._n_averages

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _check_scpi_errors(self, context: str) -> None:
        """Log any queued instrument errors (Tektronix event queue).

        The scope accepts unknown headers silently on the write channel and
        only reports them via *ESR?/ALLEv? — without this check, rejected
        commands (the old TRIGger:MODE form, for instance) fail silently.
        """
        if self.simulation or self._instr is None or self._vendor != "tektronix":
            return
        try:
            esr = int(float(self._query_text("*ESR?").strip()))
            if not esr & 0x3C:   # CME | EXE | DDE | QYE
                return
            events = self._query_text("ALLEv?").strip()
        except Exception:
            return
        logger.warning("Oscilloscope SCPI error(s) after %s: %s", context, events)

    def _recover_session(self) -> None:
        """Best-effort unwedge after a failed/timed-out query.

        A failed CURVE?/query on this family leaves the output queue
        unterminated ("Query INTERRUPTED"/"UNTERMINATED" events) and every
        subsequent reply comes back truncated until a VISA device clear.

        Holds io_lock (re-entrant): a device clear is a control transfer on
        the shared VISA handle, so it must never fire while another thread is
        mid ``query_binary_values`` on the same session — that would abort the
        in-flight bulk transfer and corrupt a scan waveform.  Callers already
        inside a ``with self.io_lock`` block (read_channel/_query_preamble)
        re-enter harmlessly; the read_settings/is_alive paths get serialized.
        """
        if self._instr is None:
            return
        with self.io_lock:
            try:
                self._instr.clear()
            except Exception:
                pass
            try:
                self._query_text("*ESR?")
                self._query_text("ALLEv?")
            except Exception:
                pass

    def _write(self, cmd: str) -> None:
        if self._instr is not None:
            with self.io_lock:
                self._log_io("TX", cmd)
                self._instr.write(cmd)

    def _log_io(self, direction: str, payload: str) -> None:
        io_logger.debug("scope %-4s %s", direction, payload)

    def _query_text(self, cmd: str) -> str:
        assert self._instr is not None
        with self.io_lock:
            self._log_io("TX", cmd)
            try:
                reply = self._instr.query(cmd)
            except Exception as exc:
                self._log_io("ERR", f"{cmd} -> {exc}")
                raise
        self._log_io("RX", f"{cmd} -> {reply.strip()}")
        return reply

    def _query_binary_values(self, cmd: str, datatype: str, is_big_endian: bool):
        assert self._instr is not None
        with self.io_lock:
            self._log_io("TX", cmd)
            try:
                values = self._instr.query_binary_values(
                    cmd, datatype=datatype, is_big_endian=is_big_endian
                )
            except Exception as exc:
                self._log_io("ERR", f"{cmd} -> {exc}")
                raise
        endian = "BE" if is_big_endian else "LE"
        self._log_io("RX", f"{cmd} -> {len(values)} pts [{datatype}, {endian}]")
        return values

    def _check_clipping(self, voltage_V: np.ndarray, channel: int) -> None:
        """Warn (and log) if the waveform contains NaN or is rail-to-rail clipped."""
        if np.any(np.isnan(voltage_V)):
            logger.warning(
                "CH%d waveform contains NaN values — signal likely exceeded "
                "the vertical scale. Increase V/div on the oscilloscope.",
                channel,
            )

    def _read_channel_lecroy(self, channel: int) -> tuple[np.ndarray, np.ndarray]:
        """LeCroy-specific waveform acquisition via COMM_FORMAT / C{ch}:WF? DAT1."""
        # Apply communication format once
        self._write("COMM_FORMAT DEF9,WORD,BIN")
        self._write("COMM_ORDER LO")

        # Binary waveform data
        raw = self._query_binary_values(
            f"C{channel}:WF? DAT1",
            datatype="h",       # signed 16-bit
            is_big_endian=False,
        )
        arr = np.array(raw, dtype=float)

        # Calibration from INSP? queries
        def _insp(key: str) -> float:
            resp = self._query_text(f"C{channel}:INSP? '{key}'")
            # Response format: 'KEY'            : value\n
            return float(resp.split(":")[-1].strip())

        try:
            vert_gain    = _insp("VERTICAL_GAIN")
            vert_offset  = _insp("VERTICAL_OFFSET")
            horiz_interv = _insp("HORIZ_INTERVAL")
            horiz_offset = _insp("HORIZ_OFFSET")
        except Exception:
            # Fallback if INSP not supported on older firmware
            vert_gain    = 1e-3
            vert_offset  = 0.0
            horiz_interv = 1e-9
            horiz_offset = 0.0

        n = len(arr)
        time_s    = horiz_offset + np.arange(n) * horiz_interv
        voltage_V = arr * vert_gain - vert_offset
        self._check_clipping(voltage_V, channel)
        return time_s, voltage_V

    def _parse_waveform(
        self, raw: np.ndarray, preamble: str
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Convert raw ADC counts to calibrated time/voltage arrays.
        Preamble parsing is vendor-agnostic: we look for
        x_increment, x_origin, y_multiplier, y_offset in the preamble.
        Falls back to generic estimates when fields are missing.
        """
        def _f(token: str) -> float | None:
            m = _NUM_RE.search(token)
            return float(m.group(0)) if m else None

        # 1) Tektronix key/value preambles (often ';' separated, mixed case)
        #    e.g. "XINcr 4.0E-7;XZEro -1.0E-3;YMUlt 2.0E-2;YOFf 127;YZEro 0.0"
        values: dict[str, float] = {}
        for token in re.split(r"[;,]", preamble):
            s = token.strip()
            if not s:
                continue
            m = re.match(r"^([A-Za-z_]+)", s)
            if not m:
                continue
            key = m.group(1).upper()
            val = _f(s[m.end():])
            if val is not None:
                values[key] = val

        x_inc = values.get("XINCR")
        x_orig = values.get("XZERO")
        y_mult = values.get("YMULT")
        y_zero = values.get("YZERO")
        y_off = values.get("YOFF")

        # 2) Positional preambles.
        #    Tektronix TBS/TDS families often return ';'-separated WFMPRE like:
        #    1;8;BINARY;RI;MSB;"Ch1,...";2000;Y;"s";1e-9;-1e-6;0;"V";0.2;0;0;...
        #    Keysight/Rigol typically return ','-separated SCPI preambles:
        #    FORMAT,TYPE,POINTS,COUNT,XINCREMENT,XORIGIN,XREFERENCE,
        #    YINCREMENT,YORIGIN,YREFERENCE
        if None in (x_inc, x_orig, y_mult, y_zero, y_off):
            sep = ";" if ";" in preamble else ","
            parts = [p.strip() for p in preamble.split(sep) if p.strip()]
            nums = [_f(p) for p in parts]
            try:
                if len(parts) >= 16:
                    # Tektronix numeric/positional WFMPRE?/WFMOutpre? fallback.
                    # Field order (0-indexed): 9=XINcr 10=XZEro 13=YMUlt
                    # 14=YOFf 15=YZEro — confirmed live on the TBS1052C.
                    # (Previously 14/15 were swapped, which corrupted absolute
                    # voltages whenever YOFf was non-zero — the common case.)
                    x_inc = x_inc if x_inc is not None else float(parts[9])
                    x_orig = x_orig if x_orig is not None else float(parts[10])
                    y_mult = y_mult if y_mult is not None else float(parts[13])
                    y_off = y_off if y_off is not None else float(parts[14])
                    y_zero = y_zero if y_zero is not None else float(parts[15])
                elif len(parts) >= 10:
                    x_inc = x_inc if x_inc is not None else nums[4]
                    x_orig = x_orig if x_orig is not None else nums[5]
                    y_mult = y_mult if y_mult is not None else nums[7]
                    y_zero = y_zero if y_zero is not None else nums[8]
                    y_off = y_off if y_off is not None else nums[9]
            except (TypeError, ValueError):
                pass

        if None in (x_inc, x_orig, y_mult, y_zero, y_off):
            n = len(raw)
            x_inc = 1e-9
            x_orig = -(n // 2) * x_inc
            y_mult = 1e-3
            y_zero = 0.0
            y_off = 0.0
            logger.warning(
                "Could not parse waveform preamble; using fallback scaling "
                "(time step 1 ns, y scale 1 mV/count)."
            )

        n = len(raw)
        time_s    = x_orig + np.arange(n) * x_inc
        voltage_V = (raw - y_off) * y_mult + y_zero
        return time_s, voltage_V

    def _simulated_waveform(self) -> tuple[np.ndarray, np.ndarray]:
        t = np.linspace(-20e-9, 180e-9, 500)
        amp = 0.1
        pulse = amp * np.exp(-0.5 * ((t - 40e-9) / 8e-9) ** 2)
        noise = np.random.normal(0.0, amp * 0.01, size=t.shape)
        return t, pulse + noise
