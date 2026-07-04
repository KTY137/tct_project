"""
Tektronix MSO5204B FastFrame oscilloscope driver.

Thin ``BaseDevice`` adapter around a colleague's (Dustin's) vendored Tektronix
acquisition toolkit at ``vendor/dustin_scope/MSO5204B/{acquire,config,
translater}.py`` — see ``vendor/dustin_scope/__init__.py`` for the
provenance note and the two mechanical fixes applied there (module-level
call removed from translater.py; PEP 701 nested f-string quoting fixed in
config.py so it parses on the Python 3.10 this app is pinned to).

This is an ADDITIVE capability, following the same "separate class per
specialized backend" pattern as ``oscilloscope_drs4.py``. It does NOT modify
or replace the generic ``devices/oscilloscope.py:Oscilloscope`` class, which
remains the default vendor-agnostic one-shot-per-trigger driver.

What this adds over the generic driver
----------------------------------------
``Oscilloscope.read_channel()`` does one ``CURVE?`` per software-armed
trigger. Tektronix FastFrame instead buffers many triggered frames on the
scope (``HORizontal:FASTframe:COUNt`` + ``HORIZONTAL:FASTFRAME:STATE ON``)
and streams them back in one continuous transfer (``CURVEStream?``) — Dustin's
benchmark quotes ~380,000 Aq/s vs. ~280 Aq/s for one-shot acquisition. This
driver exposes that burst mode, an optional per-frame trigger-timestamp
readout, and scope-side hardware-averaged acquisition (``ACQuire:MODE
AVErage``), all converted to plain numpy arrays for this app's own
``data/hdf5_writer.py`` (Dustin's original scripts wrote CSV/binary files;
this driver never touches disk).

Config keys (devices.yaml -> oscilloscope, backend: tek_fastframe)
---------------------------------------------------------------------
visa_address      : VISA resource string (LAN/USB)
timeout_ms        : VISA timeout (ms) for ordinary queries (*IDN?, WFMOutpre?,
                     ACQ:STATE?, ...). Burst reads (CURVEStream?) set their own
                     long timeout right before the stream, matching Dustin's
                     script, since a burst read can take far longer than a
                     normal query.
trigger_channel   : e.g. "CH4"
trigger_level_V   : trigger threshold (V)
trigger_type      : e.g. "EDGE"
trigger_mode      : e.g. "NORMAL"
timescale_s       : horizontal scale (s/div)
vertical_scale_V  : vertical scale (V/div)
waveform_position : vertical position (divisions)
waveform_channel  : e.g. "CH4"
acquisition_mode  : e.g. "SAMPLE"
sample_rate_hz    : sample rate (Hz)
record_length     : samples per waveform/frame
num_frames        : frames per FastFrame burst (HORizontal:FASTframe:COUNt)
average_number    : hardware averages for acquire_averaged()
avg_timeout_s     : max wait for an averaged sequence to finish (s)
simulation        : bool

Safety
------
``connect()`` only opens the VISA session and reads ``*IDN?`` — it does NOT
call the vendored ``config.setup()`` (which issues ``*RST`` and reconfigures
trigger/acquisition state) and does NOT arm any acquisition, per this app's
rule that constructors/connect() must not have hidden side effects. Applying
the scope configuration and starting a burst/averaged acquisition are each
explicit, separate method calls (``apply_configuration()``,
``acquire_burst()``, ``acquire_burst_with_timestamps()``,
``acquire_averaged()``) so the calling layer (GUI / config-validator flow)
can require user confirmation before changing scope state or starting a long
acquisition, consistent with the way HV-enable/ramp and stage motion are
gated elsewhere in this app.

Known issue in the vendored code (documented, not silently patched)
---------------------------------------------------------------------
``vendor/dustin_scope/MSO5204B/acquire.py:mean_waveform()`` references two
names (``times``, ``num_frames``) that are never defined in that function —
calling it raises ``NameError``/``UnboundLocalError`` even for
``num_waveforms == 1``. Rather than "fix" a third-party vendored file beyond
the two authorized mechanical fixes, ``acquire_averaged()`` below reassembles
the *same* SCPI command sequence (``ACQuire:MODE AVErage``, ``ACQuire:NUMAVg``,
``ACQuire:STOPAfter SEQuence``, ``ACQuire:STATE ON/OFF``, ``WFMOutpre?``,
``ACQ:STATE?``, ``CURVE?``) that appears working, verbatim, elsewhere in
Dustin's own ``time_frames()``/``waveform()`` functions in the same file —
no command here is guessed.
"""
from __future__ import annotations

import io
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from .base import BaseDevice, DeviceError

logger = logging.getLogger(__name__)
io_logger = logging.getLogger("tct.device_io")

# Candidate root(s) that contain the importable ``dustin_scope`` package,
# mirroring devices/bias_supply_e4control.py's _E4C_ROOTS resolution pattern.
_DUSTIN_ROOTS = [
    Path(__file__).parent.parent / "vendor",   # TCT_app/vendor
]


def _import_dustin_mso5204b() -> tuple[Any, Any, Any]:
    """
    Import and return (acquire, config, translater) from the vendored
    dustin_scope.MSO5204B package, adding TCT_app/vendor to sys.path if
    needed so this works without a pip install.
    """
    for root in _DUSTIN_ROOTS:
        if (root / "dustin_scope").is_dir():
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            break

    try:
        import importlib
        acquire = importlib.import_module("dustin_scope.MSO5204B.acquire")
        config = importlib.import_module("dustin_scope.MSO5204B.config")
        translater = importlib.import_module("dustin_scope.MSO5204B.translater")
        return acquire, config, translater
    except ImportError as exc:
        roots = " or ".join(str(r) for r in _DUSTIN_ROOTS)
        raise DeviceError(
            f"Cannot import vendored dustin_scope.MSO5204B modules from {roots}.\n"
            "translater.py additionally requires matplotlib and pandas "
            "(pip install matplotlib pandas tqdm) even though this driver "
            "never calls its plotting/CSV functions, because those imports "
            "are unconditional at module load time in the vendored file.\n"
            f"Original error: {exc}"
        ) from exc


class TekFastFrameOscilloscope(BaseDevice):
    """
    Driver for a Tektronix MSO5204B (or DPO5104 — same command set per
    Dustin's toolkit) using FastFrame burst acquisition.

    Does not implement the generic ``Oscilloscope`` interface's
    ``read_channel()``; the burst-oriented calls here return multi-frame
    numpy arrays, which need a different consumer (scan controller /
    hdf5_writer). See module docstring for the exposed methods.
    """

    def __init__(
        self,
        visa_address: str = "",
        timeout_ms: int = 10000,
        trigger_channel: str = "CH4",
        trigger_level_V: float = -0.0116,
        trigger_type: str = "EDGE",
        trigger_mode: str = "NORMAL",
        timescale_s: float = 10e-9,
        vertical_scale_V: float = 0.008,
        waveform_position: float = 0.0,
        waveform_channel: str = "CH4",
        acquisition_mode: str = "SAMPLE",
        sample_rate_hz: float = 10e9,
        record_length: int = 1000,
        num_frames: int = 20000,
        average_number: int = 512,
        avg_timeout_s: float = 30.0,
        simulation: bool = False,
    ) -> None:
        super().__init__(simulation=simulation)
        self._address = visa_address
        self._timeout_ms = int(timeout_ms)
        self._trigger_channel = trigger_channel
        self._trigger_level_V = float(trigger_level_V)
        self._trigger_type = trigger_type
        self._trigger_mode = trigger_mode
        self._timescale_s = float(timescale_s)
        self._vertical_scale_V = float(vertical_scale_V)
        self._waveform_position = float(waveform_position)
        self._waveform_channel = waveform_channel
        self._acquisition_mode = acquisition_mode
        self._sample_rate_hz = float(sample_rate_hz)
        self._record_length = int(record_length)
        self._num_frames = int(num_frames)
        self._average_number = int(average_number)
        self._avg_timeout_s = float(avg_timeout_s)

        self._instr: Any = None
        self._rm: Any = None
        self._acquire: Any = None
        self._config: Any = None
        self._translater: Any = None

    # ------------------------------------------------------------------ #
    # BaseDevice                                                          #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            logger.info("TekFastFrameOscilloscope connected (simulation)")
            return

        try:
            import pyvisa  # type: ignore[import]
        except ImportError as exc:
            raise DeviceError("pyvisa is not installed. Run: pip install pyvisa") from exc

        self._acquire, self._config, self._translater = _import_dustin_mso5204b()

        self._rm = pyvisa.ResourceManager()
        try:
            self._instr = self._rm.open_resource(self._address)
            self._instr.timeout = self._timeout_ms
        except Exception as exc:
            raise DeviceError(f"TekFastFrameOscilloscope VISA open failed: {exc}") from exc

        try:
            idn = self._query("*IDN?").strip()
        except Exception as exc:
            raise DeviceError(f"TekFastFrameOscilloscope *IDN? query failed: {exc}") from exc

        logger.info("TekFastFrameOscilloscope connected: %s", idn)
        self._connected = True
        # NOTE: deliberately does not call self._config.setup() or arm any
        # acquisition here — see module docstring "Safety" section.

    def disconnect(self) -> None:
        if self._instr is not None:
            try:
                self._instr.close()
            except Exception:
                pass
        self._instr = None
        self._connected = False

    def test_connection(self) -> str:
        """Query *IDN? and return the reply -- confirms the VISA link."""
        if self.simulation:
            return "Simulation mode -- TekFastFrameOscilloscope. No hardware queried."
        if not self._connected or self._instr is None:
            return "Not connected."
        try:
            return f"TekFastFrameOscilloscope OK:\n{self._query('*IDN?').strip()}"
        except Exception as exc:
            return f"*IDN? query failed: {exc}"

    # ------------------------------------------------------------------ #
    # Explicit, user-confirmed configuration (never called from connect)   #
    # ------------------------------------------------------------------ #

    def apply_configuration(self) -> None:
        """
        Push trigger/acquisition/timebase settings to the scope via the
        vendored ``config.setup()`` (Dustin's original — issues ``*RST`` and
        reconfigures trigger, timebase, and acquisition mode).

        This is a significant, visible state change (like a stage home or an
        HV ramp) and must be an explicit call the calling layer gates behind
        user confirmation -- never invoked implicitly from connect().
        """
        self._require_connected()
        if self.simulation:
            logger.info("apply_configuration: simulation mode, no-op")
            return
        with self.io_lock:
            self._config.setup(self._instr, self._build_config())

    # ------------------------------------------------------------------ #
    # Burst acquisition (FastFrame)                                       #
    # ------------------------------------------------------------------ #

    def acquire_burst(
        self, num_waveforms: int = 1, num_frames: int | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        FastFrame burst acquisition wrapping the vendored ``acquire.frames``.

        Returns
        -------
        time_s     : 1D array, length = record_length
        waveforms_V: 2D array, shape (n_frames_total, record_length)
        """
        self._require_connected()
        n_frames = num_frames if num_frames is not None else self._num_frames
        if self.simulation:
            return self._simulated_burst(n_frames)

        cfg = self._build_config(num_waveforms=num_waveforms, num_frames=n_frames)
        with self.io_lock:
            header, raw = self._acquire.frames(self._instr, cfg)
        return self._decode_curvestream(raw, header)

    def acquire_burst_with_timestamps(
        self, num_waveforms: int = 1, num_frames: int | None = None
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """
        Like ``acquire_burst`` but also returns per-frame trigger timestamps,
        wrapping the vendored ``acquire.time_frames``.

        Returns
        -------
        time_s      : 1D array, length = record_length
        waveforms_V : 2D array, shape (n_frames_total, record_length)
        timestamps  : list of raw ``HORizontal:FASTframe:TIMEStamp`` query
                      replies (one string per completed acquisition sequence;
                      format is Dustin's original, unparsed here)
        """
        self._require_connected()
        n_frames = num_frames if num_frames is not None else self._num_frames
        if self.simulation:
            time_s, waveforms = self._simulated_burst(n_frames)
            timestamps = [f"SIM,{i}" for i in range(waveforms.shape[0])]
            return time_s, waveforms, timestamps

        cfg = self._build_config(num_waveforms=num_waveforms, num_frames=n_frames)
        with self.io_lock:
            header, raw, times = self._acquire.time_frames(self._instr, cfg)
        time_s, waveforms = self._decode_curvestream(raw, header)
        return time_s, waveforms, times

    # ------------------------------------------------------------------ #
    # Hardware-averaged acquisition                                       #
    # ------------------------------------------------------------------ #

    def acquire_averaged(self, average_number: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        """
        Scope-side hardware-averaged single waveform (``ACQuire:MODE
        AVErage``). See module docstring "Known issue in the vendored code"
        for why this does not call the vendored ``mean_waveform()`` directly.

        Returns
        -------
        time_s     : 1D array, length = record_length
        waveform_V : 1D array, length = record_length (averaged)
        """
        self._require_connected()
        avg_n = average_number if average_number is not None else self._average_number
        if self.simulation:
            return self._simulated_average()

        with self.io_lock:
            self._write("ACQuire:STATE OFF")
            self._write("ACQuire:MODE AVErage")
            self._write(f"ACQuire:NUMAVg {avg_n}")
            self._write("ACQuire:STOPAfter SEQuence")
            self._write("ACQuire:STATE ON")
            header = self._query("WFMOutpre?")

            deadline = time.time() + self._avg_timeout_s
            while True:
                status = self._query("ACQ:STATE?").strip()
                if status == "0":
                    break
                if time.time() > deadline:
                    raise DeviceError(
                        f"Averaged acquisition did not complete within "
                        f"{self._avg_timeout_s:.1f} s (ACQ:STATE? still nonzero). "
                        "Check trigger source/level and that the trigger signal "
                        "is present."
                    )
                time.sleep(0.01)

            self._write("CURVE?")
            raw = self._instr.read_raw()

        time_s, waveforms = self._decode_curvestream([raw], header)
        return time_s, waveforms[0]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_config(
        self, num_waveforms: int = 1, num_frames: int | None = None
    ) -> dict:
        """Build the plain dict the vendored acquire.py/config.py expect."""
        return {
            "trigger_channel": self._trigger_channel,
            "trigger_level": self._trigger_level_V,
            "trigger_type": self._trigger_type,
            "trigger_mode": self._trigger_mode,
            "timescale": self._timescale_s,
            "vertical_scale": self._vertical_scale_V,
            "waveform_position": self._waveform_position,
            "waveform_channel": self._waveform_channel,
            "acquisition_mode": self._acquisition_mode,
            "sample_rate": self._sample_rate_hz,
            "record_length": self._record_length,
            "num_frames": num_frames if num_frames is not None else self._num_frames,
            "num_waveforms": num_waveforms,
            "average_number": self._average_number,
        }

    def _write(self, cmd: str) -> None:
        assert self._instr is not None
        with self.io_lock:
            io_logger.debug("tek_fastframe TX %s", cmd)
            self._instr.write(cmd)

    def _query(self, cmd: str) -> str:
        assert self._instr is not None
        with self.io_lock:
            io_logger.debug("tek_fastframe TX %s", cmd)
            try:
                reply = self._instr.query(cmd)
            except Exception as exc:
                io_logger.debug("tek_fastframe ERR %s -> %s", cmd, exc)
                raise
        io_logger.debug("tek_fastframe RX %s -> %s", cmd, reply.strip())
        return reply

    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError("TekFastFrameOscilloscope is not connected — call connect() first.")

    def _decode_curvestream(
        self, raw_chunks: list[bytes], header: str
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Decode a concatenated CURVEStream?/CURVE? binary-block response into
        (time_s, waveforms) numpy arrays.

        Reuses the vendored translater.py's block-parsing and scaling
        functions (``read_data_block``, ``scale_data``, ``generate_x``)
        unchanged; only the source is swapped from a file
        (``translater.binary_to_data`` opens ``filename``) to an in-memory
        ``io.BytesIO`` buffer so nothing is written to disk, and the header
        scaling factors come from the WFMOutpre? string already held in
        memory rather than a separate header CSV file
        (``translater.read_scaling_factors`` reads one from a path).  Field
        indices (YMULT=13, YOFF=14, YZERO=15, XINCR=9, XZERO=10, NR_PT=6)
        mirror ``translater.read_scaling_factors`` exactly.
        """
        t = self._translater
        scaling = self._scaling_from_header(header)
        nr_pt = int(scaling["NR_PT"])

        blob = b"".join(raw_chunks)
        buf = io.BytesIO(blob)
        scaled_y: list[float] = []

        while True:
            head = buf.read(2)
            if not head:
                break
            while head in (b";\n", b"\n"):
                head = buf.read(2)
                if not head:
                    break
            if not head:
                break

            if head == b"\n#":
                digit_byte = buf.read(1)
                if not digit_byte.isdigit():
                    raise DeviceError(f"Unexpected CURVEStream block format after \\n#: {digit_byte!r}")
                digits = int(digit_byte)
                raw_block = t.read_data_block(buf, digits)
                scaled_y.extend(
                    t.scale_data(raw_block, scaling["YMULT"], scaling["YOFF"], scaling["YZERO"])
                )
                continue

            if head.startswith(b"#") and head[1:2].isdigit():
                digits = int(head[1:2])
                raw_block = t.read_data_block(buf, digits)
                scaled_y.extend(
                    t.scale_data(raw_block, scaling["YMULT"], scaling["YOFF"], scaling["YZERO"])
                )
                continue

            raise DeviceError(f"Unrecognised CURVEStream block header: {head!r}")

        if not scaled_y:
            raise DeviceError("CURVEStream response contained no waveform blocks.")

        y = np.asarray(scaled_y, dtype=float)
        if len(y) % nr_pt != 0:
            raise DeviceError(
                f"CURVEStream payload ({len(y)} samples) is not a multiple of "
                f"NR_PT ({nr_pt}) from the WFMOutpre? header — acquisition or "
                "decode desync."
            )
        n_frames_total = len(y) // nr_pt
        waveforms = y.reshape(n_frames_total, nr_pt)

        x_inc = scaling["XINCR"]
        x_zero = scaling["XZERO"]
        time_s = x_zero + np.arange(nr_pt) * x_inc
        return time_s, waveforms

    def _scaling_from_header(self, header: str) -> dict:
        """
        Parse WFMOutpre? scaling factors directly from the in-memory header
        string, mirroring translater.read_scaling_factors's field indices
        (which reads the equivalent ';'-delimited row from a header CSV
        file). Positional indices: YMULT=13, YOFF=14, YZERO=15, XINCR=9,
        XZERO=10, NR_PT=6 (0-indexed WFMOutpre? fields).
        """
        import csv

        row = next(csv.reader(io.StringIO(header), delimiter=";"))
        return {
            "YMULT": float(row[13]),
            "YOFF": float(row[14]),
            "YZERO": float(row[15]),
            "XINCR": float(row[9]),
            "XZERO": float(row[10]),
            "NR_PT": float(row[6]),
        }

    # ------------------------------------------------------------------ #
    # Simulation                                                          #
    # ------------------------------------------------------------------ #

    def _simulated_burst(self, n_frames: int) -> tuple[np.ndarray, np.ndarray]:
        """
        Synthetic multi-frame burst: n_frames TCT-like negative pulses with
        per-frame jitter/noise, modeled on Oscilloscope._simulated_waveform().
        """
        n_frames = max(int(n_frames), 1)
        n_samples = self._record_length
        dt = 1.0 / self._sample_rate_hz
        t = np.arange(n_samples) * dt + self._timescale_s * -0.5

        rng = np.random.default_rng()
        waveforms = np.empty((n_frames, n_samples), dtype=float)
        amp = 0.1
        for i in range(n_frames):
            jitter_s = rng.normal(0.0, dt * 2)
            t_peak = t[n_samples // 2] + jitter_s
            sigma = 8e-9
            pulse = amp * np.exp(-0.5 * ((t - t_peak) / sigma) ** 2)
            noise = rng.normal(0.0, amp * 0.01, size=n_samples)
            waveforms[i] = pulse + noise
        return t, waveforms

    def _simulated_average(self) -> tuple[np.ndarray, np.ndarray]:
        """Low-noise averaged pulse (hardware averaging reduces noise ~1/sqrt(N))."""
        n_samples = self._record_length
        dt = 1.0 / self._sample_rate_hz
        t = np.arange(n_samples) * dt + self._timescale_s * -0.5
        amp = 0.1
        pulse = amp * np.exp(-0.5 * ((t - t[n_samples // 2]) / 8e-9) ** 2)
        noise_scale = amp * 0.01 / max(self._average_number, 1) ** 0.5
        noise = np.random.default_rng().normal(0.0, noise_scale, size=n_samples)
        return t, pulse + noise
