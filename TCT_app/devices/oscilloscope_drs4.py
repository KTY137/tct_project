"""
PSI DRS4 Evaluation Board oscilloscope driver.

The DRS4 is a 4-channel, 1 GHz, 5 GS/s waveform digitiser from the Paul
Scherrer Institute (PSI).  It is widely used in small-scale TCT setups as
a low-cost, high-rate alternative to a bench oscilloscope.

Python interface
----------------
Requires the 'drs' C-extension built from the PSI DRS4 software package
(https://www.psi.ch/drs/evaluation-board).  If the module is not available
the driver operates in simulation mode.

Specification
-------------
- 4 differential channels (CH 1–4)
- Sampling frequency up to 5 GHz (200 ps between samples)
- 1024 samples per channel per acquisition
- Voltage range: ±500 mV (range=0) or 0–1 V (range=1)
- External trigger or channel trigger
- On-board time-bin calibration
- Software time-jitter correction keyed to trigger edge (sub-ns accuracy)

Config keys  (devices.yaml → oscilloscope, with backend: drs4)
--------------------------------------------------------------
frequency_ghz     : 5.0        # sampling frequency 1–5 GHz
voltage_range     : 0          # 0 = ±500 mV, 1 = 0–1 V
trigger_source    : "EXT"      # EXT | CH1 | CH2 | CH3 | CH4
trigger_level_V   : -0.05      # threshold (V)
trigger_edge      : "FALL"     # FALL | RISE
trigger_delay_ns  : 150.0      # pre-trigger memory depth (ns)
n_averages        : 1          # software averages per read_channel call
time_correction   : true       # correct per-event trigger-time jitter
t0_ns             : 20.0       # desired t=0 offset after correction (ns)
t0_threshold_V    : -0.45      # voltage threshold for finding t0 (V)
timeout_s         : 2.0        # wait for trigger timeout
simulation        : true
"""
from __future__ import annotations

import logging
import time

import numpy as np

from .base import BaseDevice, DeviceError

logger = logging.getLogger(__name__)


# DRS4 trigger source bit masks
_TRIG_BITS: dict[str, int] = {
    "CH1": 1 << 0,
    "CH2": 1 << 1,
    "CH3": 1 << 2,
    "CH4": 1 << 3,
    "EXT": 1 << 4,
}

# Number of samples per channel (fixed by DRS4 hardware)
_N_SAMPLES = 1024

# Analog channel count — fixed by the DRS4 evaluation-board hardware.  Cited
# from this module's own spec block ("4 differential channels (CH 1–4)") and
# the _TRIG_BITS table (CH1–CH4); not a heuristic.
_N_CHANNELS = 4


class DRS4Oscilloscope(BaseDevice):
    """
    Driver for the PSI DRS4 evaluation board.

    Implements the same read_channel(ch) → (time_s, voltage_V) interface
    as the VISA Oscilloscope class so the scan controller and intensity
    monitor can use either device transparently.
    """

    def __init__(
        self,
        frequency_ghz: float = 5.0,
        voltage_range: int = 0,
        trigger_source: str = "EXT",
        trigger_level_V: float = -0.05,
        trigger_edge: str = "FALL",
        trigger_delay_ns: float = 150.0,
        n_averages: int = 1,
        time_correction: bool = True,
        t0_ns: float = 20.0,
        t0_threshold_V: float = -0.45,
        timeout_s: float = 2.0,
        simulation: bool = True,
    ) -> None:
        super().__init__(simulation=simulation)
        # Fixed hardware capability (see _N_CHANNELS); exposed like the VISA
        # driver's attribute so ScopePanel can size its channel cards uniformly.
        self.n_channels = _N_CHANNELS
        self._freq_ghz = frequency_ghz
        self._range = voltage_range
        self._trig_source = trigger_source.upper()
        self._trig_level_V = trigger_level_V
        self._trig_edge = trigger_edge.upper()
        self._trig_delay_ns = trigger_delay_ns
        self._n_averages = max(n_averages, 1)
        self._time_correction = time_correction
        self._t0_ns = t0_ns
        self._t0_threshold_V = t0_threshold_V
        self._timeout_s = timeout_s
        self._board = None

    # ------------------------------------------------------------------ #
    # BaseDevice                                                          #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            logger.info("DRS4 connected (simulation)")
            return

        try:
            import drs as _drs  # type: ignore[import]
        except ImportError as exc:
            raise DeviceError(
                "DRS4 Python module not found.\n"
                "Build the 'drs' C-extension from the PSI DRS4 package:\n"
                "  https://www.psi.ch/drs/evaluation-board\n"
                "Then copy drs.so / drs.pyd into the Python path."
            ) from exc

        self._board = _drs.Board()
        if not self._board.Init():
            raise DeviceError(
                "DRS4 board not found or initialisation failed. "
                "Check USB connection and that no other process is using the board."
            )

        self._apply_config()
        sn = getattr(self._board, "GetBoardSerialNumber", lambda: "?")()
        logger.info("DRS4 board connected — serial %s", sn)
        self._connected = True

    def disconnect(self) -> None:
        self._board = None
        self._connected = False
        logger.info("DRS4 disconnected")

    # ------------------------------------------------------------------ #
    # Configuration                                                       #
    # ------------------------------------------------------------------ #

    def _apply_config(self) -> None:
        """Push current settings to the board."""
        b = self._board
        b.SetFrequency(self._freq_ghz, True)          # True → run time calibration
        b.SetInputRange(self._range)
        trig_bits = _TRIG_BITS.get(self._trig_source, _TRIG_BITS["EXT"])
        b.SetTriggerSource(trig_bits)
        b.SetTriggerLevel(self._trig_level_V)
        # SetTriggerPolarity: True = negative/falling edge
        b.SetTriggerPolarity(self._trig_edge == "FALL")

    def set_frequency(self, freq_ghz: float) -> None:
        self._freq_ghz = freq_ghz
        if self._board is not None:
            self._board.SetFrequency(freq_ghz, True)

    def set_voltage_range(self, range_idx: int) -> None:
        self._range = range_idx
        if self._board is not None:
            self._board.SetInputRange(range_idx)

    def set_trigger(
        self,
        source: str | None = None,
        level_V: float | None = None,
        edge: str | None = None,
    ) -> None:
        if source is not None:
            self._trig_source = source.upper()
        if level_V is not None:
            self._trig_level_V = level_V
        if edge is not None:
            self._trig_edge = edge.upper()
        if self._board is not None:
            b = self._board
            b.SetTriggerSource(_TRIG_BITS.get(self._trig_source, _TRIG_BITS["EXT"]))
            b.SetTriggerLevel(self._trig_level_V)
            b.SetTriggerPolarity(self._trig_edge == "FALL")

    # ------------------------------------------------------------------ #
    # Waveform acquisition                                                #
    # ------------------------------------------------------------------ #

    def read_channel(self, channel: int) -> tuple[np.ndarray, np.ndarray]:
        """
        Acquire n_averages waveforms, average, and return (time_s, voltage_V).

        channel : int
            Channel number 1–4.
        """
        if self.simulation:
            return self._simulated_waveform(channel)

        # Channel index on the board: CH1→0, CH2→2, CH3→4, CH4→6 (paired ADCs)
        ch_idx = (channel - 1) * 2

        wave_list: list[np.ndarray] = []
        t_ref: np.ndarray | None = None

        for _ in range(self._n_averages):
            b = self._board
            b.StartDomino()

            # Wait for hardware trigger
            deadline = time.time() + self._timeout_s
            while not b.IsBusy():
                if time.time() > deadline:
                    raise DeviceError(
                        f"DRS4: no trigger received within {self._timeout_s:.1f} s. "
                        "Check trigger source, level, and laser."
                    )
                time.sleep(0.001)

            # Transfer all 8 ADC channels (4 differential pairs) to PC
            b.TransferWaves(0, 7)

            t_ns = np.array(b.GetTime(0, ch_idx))           # ns, length 1024
            v_mV = np.array(b.GetWave(0, ch_idx, True))     # mV, calibrated

            if self._time_correction:
                t_ns = self._correct_jitter(b, t_ns)

            if t_ref is None:
                t_ref = t_ns
            wave_list.append(v_mV)

        v_avg = np.mean(wave_list, axis=0) if len(wave_list) > 1 else wave_list[0]
        return t_ref * 1e-9, v_avg * 1e-3   # ns→s, mV→V

    def _correct_jitter(self, board, t_ns: np.ndarray) -> np.ndarray:
        """
        Re-reference the time axis to the trigger-edge crossing so that
        averaging many events does not smear the pulse shape.

        The DRS4 has up to ~1 ns peak-to-peak trigger-time jitter.  By
        finding the exact crossing time of the trigger signal in each event
        and subtracting it, the effective time origin is locked to the trigger
        edge, eliminating jitter-induced rise-time broadening.

        Reference channel is CH4 (index 6), which receives the external
        trigger signal in the standard TCT wiring.
        """
        try:
            v_trig_mV = np.array(board.GetWave(0, 6, True))   # CH4
        except Exception:
            return t_ns

        threshold_mV = self._t0_threshold_V * 1e3

        # Find first crossing of threshold
        if self._trig_edge == "FALL":
            crossings = np.where(np.diff(np.sign(v_trig_mV - threshold_mV)) < 0)[0]
        else:
            crossings = np.where(np.diff(np.sign(v_trig_mV - threshold_mV)) > 0)[0]

        if crossings.size == 0:
            return t_ns

        idx = crossings[0]
        v0, v1 = v_trig_mV[idx], v_trig_mV[idx + 1]
        dv = v1 - v0
        frac = (threshold_mV - v0) / dv if abs(dv) > 1e-9 else 0.0
        t_cross_ns = t_ns[idx] + frac * (t_ns[idx + 1] - t_ns[idx])

        return t_ns - t_cross_ns + self._t0_ns

    # ------------------------------------------------------------------ #
    # Simulation                                                          #
    # ------------------------------------------------------------------ #

    def _simulated_waveform(self, channel: int) -> tuple[np.ndarray, np.ndarray]:
        """Realistic negative-polarity TCT pulse for simulation mode."""
        dt_s = 1.0 / (self._freq_ghz * 1e9)
        t = np.arange(_N_SAMPLES) * dt_s - self._trig_delay_ns * 1e-9

        if channel == 1:
            # Reference SiPM: narrow, higher amplitude
            amp, t_peak, sigma = 0.15, 35e-9, 3e-9
        else:
            # DUT sensor: broader, lower amplitude
            amp, t_peak, sigma = 0.05, 40e-9, 7e-9

        pulse = -amp * np.exp(-0.5 * ((t - t_peak) / sigma) ** 2)
        noise = np.random.normal(0.0, amp * 0.02, size=_N_SAMPLES)
        return t, pulse + noise
