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
        simulation: bool = False,
    ) -> None:
        super().__init__(simulation=simulation)
        self._address = visa_address
        self._vendor = vendor.lower()
        self._n_averages = n_averages
        self._timeout_ms = timeout_ms
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

        self._rm = pyvisa.ResourceManager()
        try:
            self._instr = self._rm.open_resource(self._address)
            self._instr.timeout = self._timeout_ms
            # Raw LAN sockets (TCPIP…::SOCKET) have no message framing — queries
            # hang without an explicit terminator.  USB / VXI-11 (::INSTR) don't
            # need this.
            if "SOCKET" in self._address.upper():
                self._instr.read_termination = "\n"
                self._instr.write_termination = "\n"
        except Exception as exc:
            raise DeviceError(f"Oscilloscope VISA open failed: {exc}") from exc

        idn = self._query_text("*IDN?").strip()
        logger.info("Oscilloscope connected: %s", idn)
        self._connected = True
        # Apply the configured trigger (previously this was never sent).
        try:
            self.configure_tct_trigger(self.trig_source, self.trig_level_V, self.trig_slope)
        except Exception as exc:
            logger.warning("Trigger config on connect failed: %s", exc)

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
        if self._instr is not None:
            try:
                self._instr.close()
            except Exception:
                pass
        self._instr = None
        self._connected = False

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
            self._write("TRIGger:MODE NORMal")
            self._write(f"TRIGger:SOURce {source}")
            self._write(f"TRIGger:LEVel {level_V}")
            self._write(f"TRIGger:SLOPe {slope}")

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
                continue
        return self._query_text(self._cmds["pre_query"])

    def set_channel_scale(self, channel: int, volts_per_div: float) -> None:
        self._last_vdiv = volts_per_div
        self._write(f"CH{channel}:SCAle {volts_per_div}")

    def set_channel_position(self, channel: int, divisions: float) -> None:
        """Vertical trace position, in divisions (Tektronix CH:POSition)."""
        self._write(f"CH{channel}:POSition {divisions}")

    def set_timebase(self, time_per_div_s: float) -> None:
        self._last_tdiv = time_per_div_s
        self._write(f"HORizontal:SCAle {time_per_div_s}")

    def read_settings(self) -> dict:
        """Read the instrument's current display / trigger settings (best effort).

        Tektronix SCPI; returns any of ``tdiv``, ``vdiv``, ``voff_div``,
        ``trig_level`` that could be queried.  Empty in simulation unless a scale
        was set this session (so the round-trip is testable)."""
        if self.simulation or self._instr is None:
            out = {}
            if getattr(self, "_last_tdiv", None):
                out["tdiv"] = self._last_tdiv
            if getattr(self, "_last_vdiv", None):
                out["vdiv"] = self._last_vdiv
            return out

        def q(cmd: str):
            try:
                return float(self._query_text(cmd))
            except Exception:
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
        lvl = q("TRIGger:MAIn:LEVel?")
        if lvl is None:
            lvl = q("TRIGger:A:LEVel?")
        if lvl is not None:
            out["trig_level"] = lvl
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

            cmds = self._cmds
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
        time_s, voltage_V = self._parse_waveform(np.array(raw), preamble_str)
        self._check_clipping(voltage_V, channel)
        return time_s, voltage_V

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

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
                    # Tektronix numeric/positional WFMPRE fallback.
                    x_inc = x_inc if x_inc is not None else float(parts[9])
                    x_orig = x_orig if x_orig is not None else float(parts[10])
                    y_mult = y_mult if y_mult is not None else float(parts[13])
                    y_zero = y_zero if y_zero is not None else float(parts[14])
                    y_off = y_off if y_off is not None else float(parts[15])
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
