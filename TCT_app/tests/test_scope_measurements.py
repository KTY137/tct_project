"""Unit tests for gui.scope_measurements.compute_measurements (pure, no Qt)."""
import numpy as np
import pytest

from gui.scope_measurements import compute_measurements, eng


def test_empty_returns_all_none():
    out = compute_measurements(None, None)
    assert set(out.values()) == {None}
    out = compute_measurements(np.array([]), np.array([]))
    assert out["vpp"] is None


def test_sine_vpp_and_frequency():
    f = 1e6  # 1 MHz
    t = np.linspace(0, 5e-6, 5000)   # 5 periods
    v = 0.5 * np.sin(2 * np.pi * f * t)
    m = compute_measurements(t, v)
    assert m["vpp"] == pytest.approx(1.0, rel=1e-2)
    assert m["vmax"] == pytest.approx(0.5, rel=1e-2)
    assert m["vmin"] == pytest.approx(-0.5, rel=1e-2)
    assert m["vmean"] == pytest.approx(0.0, abs=1e-3)
    assert m["vrms"] == pytest.approx(0.5 / np.sqrt(2), rel=1e-2)
    assert m["frequency"] == pytest.approx(f, rel=2e-2)
    assert m["period"] == pytest.approx(1.0 / f, rel=2e-2)


def test_negative_pulse_amplitude_and_rise():
    # Baseline 0, a negative-going gaussian pulse (TCT-like), amplitude ~ -0.1 V.
    t = np.linspace(-20e-9, 180e-9, 2000)
    v = -0.1 * np.exp(-0.5 * ((t - 40e-9) / 5e-9) ** 2)
    m = compute_measurements(t, v)
    # Amplitude carries the sign of the dominant excursion (negative pulse).
    assert m["amplitude"] == pytest.approx(-0.1, rel=5e-2)
    assert m["vmin"] == pytest.approx(-0.1, rel=5e-2)
    # A finite 10-90% rise time on the leading edge should be found.
    assert m["rise"] is not None and m["rise"] > 0


def test_eng_formatting():
    assert eng(5e-8, "s") == "50 ns"
    assert eng(0.5, "V") == "500 mV"
    assert eng(None, "V") == "—"
    assert eng(0.0, "s") == "0 s"
