"""Automatic scope measurements + a live measurement panel.

`compute_measurements` is a pure function (numpy in, dict out) so it is unit
testable without any Qt.  `MeasurementPanel` is a checkable list of measurements
that shows live values for the selected DUT trace, in the style of a bench
oscilloscope's "Measure" menu.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QGroupBox, QGridLayout, QCheckBox, QLabel


# (key, label, unit) — order defines display order.
MEASUREMENTS: list[tuple[str, str, str]] = [
    ("vpp",       "Vpp",        "V"),
    ("vmax",      "Vmax",       "V"),
    ("vmin",      "Vmin",       "V"),
    ("vmean",     "Vmean",      "V"),
    ("vrms",      "Vrms",       "V"),
    ("amplitude", "Amplitude",  "V"),
    ("rise",      "Rise (10-90%)", "s"),
    ("fall",      "Fall (90-10%)", "s"),
    ("period",    "Period",     "s"),
    ("frequency", "Frequency",  "Hz"),
]
_DEFAULT_ON = {"vpp", "amplitude", "rise", "frequency"}

_SI = [(1e-12, "p"), (1e-9, "n"), (1e-6, "µ"), (1e-3, "m"),
       (1.0, ""), (1e3, "k"), (1e6, "M"), (1e9, "G")]


def eng(value: float | None, unit: str) -> str:
    """Engineering-notation formatting: 5e-8,'s' -> '50 ns'."""
    if value is None or not np.isfinite(value):
        return "—"
    if value == 0:
        return f"0 {unit}"
    for scale, pre in reversed(_SI):
        if abs(value) >= scale:
            return f"{value / scale:.3g} {pre}{unit}"
    scale, pre = _SI[0]
    return f"{value / scale:.3g} {pre}{unit}"


def _baseline(v: np.ndarray) -> float:
    n = max(1, len(v) // 20)
    return float(np.mean(v[:n]))


def _edge_time(t: np.ndarray, s: np.ndarray, peak: float,
               lo: float, hi: float, rising: bool) -> float | None:
    """Time for the baseline-subtracted signal *s* (peak = signed peak) to go
    between *lo* and *hi* fractions of the peak on the main edge.

    ``rising`` selects the leading (True) or trailing (False) edge.
    """
    if peak == 0:
        return None
    a = s / peak                      # ~0 at baseline, ~1 at peak (any polarity)
    ipk = int(np.argmax(np.abs(s)))
    seg = np.arange(0, ipk + 1) if rising else np.arange(ipk, len(a))
    if len(seg) < 2:
        return None
    aa, tt = a[seg], t[seg]

    def _cross(level: float) -> float | None:
        # first index where aa crosses `level`
        for i in range(1, len(aa)):
            lo_v, hi_v = aa[i - 1], aa[i]
            if (lo_v - level) * (hi_v - level) <= 0 and hi_v != lo_v:
                frac = (level - lo_v) / (hi_v - lo_v)
                return float(tt[i - 1] + frac * (tt[i] - tt[i - 1]))
        return None

    t_lo, t_hi = _cross(lo), _cross(hi)
    if t_lo is None or t_hi is None:
        return None
    return abs(t_hi - t_lo)


def _frequency(t: np.ndarray, v: np.ndarray) -> tuple[float | None, float | None]:
    """Period and frequency from 50%-level upward crossings."""
    vmax, vmin = float(np.max(v)), float(np.min(v))
    mid = 0.5 * (vmax + vmin)
    if vmax - vmin < 1e-12:
        return None, None
    s = v - mid
    up = np.where((s[:-1] < 0) & (s[1:] >= 0))[0]
    if len(up) < 2:
        return None, None
    # interpolate crossing times for accuracy
    times = []
    for i in up:
        frac = (0.0 - s[i]) / (s[i + 1] - s[i]) if s[i + 1] != s[i] else 0.0
        times.append(t[i] + frac * (t[i + 1] - t[i]))
    period = float(np.mean(np.diff(times)))
    if period <= 0:
        return None, None
    return period, 1.0 / period


def compute_measurements(t: np.ndarray | None, v: np.ndarray | None) -> dict[str, float | None]:
    """Return all measurements (SI units) for one waveform; missing → None."""
    out: dict[str, float | None] = {k: None for k, _, _ in MEASUREMENTS}
    if t is None or v is None or len(v) == 0:
        return out
    v = np.asarray(v, dtype=float)
    t = np.asarray(t, dtype=float)
    vmax, vmin = float(np.max(v)), float(np.min(v))
    out["vpp"] = vmax - vmin
    out["vmax"] = vmax
    out["vmin"] = vmin
    out["vmean"] = float(np.mean(v))
    out["vrms"] = float(np.sqrt(np.mean(v * v)))
    base = _baseline(v)
    pos_dev, neg_dev = vmax - base, base - vmin
    peak = pos_dev if pos_dev >= neg_dev else -neg_dev
    out["amplitude"] = peak
    s = v - base
    out["rise"] = _edge_time(t, s, peak, 0.1, 0.9, rising=True)
    out["fall"] = _edge_time(t, s, peak, 0.9, 0.1, rising=False)
    period, freq = _frequency(t, v)
    out["period"] = period
    out["frequency"] = freq
    return out


class MeasurementPanel(QGroupBox):
    """Checkable list of automatic measurements with live values (DUT trace)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Measurements", parent)
        grid = QGridLayout(self)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        self._checks: dict[str, QCheckBox] = {}
        self._values: dict[str, QLabel] = {}
        for row, (key, label, _unit) in enumerate(MEASUREMENTS):
            chk = QCheckBox(label)
            chk.setChecked(key in _DEFAULT_ON)
            val = QLabel("—")
            val.setStyleSheet("font-weight: 700; color: #33c8ff;")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(chk, row, 0)
            grid.addWidget(val, row, 1)
            self._checks[key] = chk
            self._values[key] = val

    def update_values(self, t: np.ndarray | None, v: np.ndarray | None) -> None:
        vals = compute_measurements(t, v)
        for key, _label, unit in MEASUREMENTS:
            if self._checks[key].isChecked():
                self._values[key].setText(eng(vals[key], unit))
            else:
                self._values[key].setText("·")
