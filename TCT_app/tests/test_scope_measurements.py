"""Unit tests for gui.scope_measurements.compute_measurements (pure, no Qt)."""
import numpy as np
import pytest

from analysis.waveform_analysis import analyse_waveform, correct_baseline
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


# --------------------------------------------------------------------------- #
# Shared baseline formula (analysis.waveform_analysis.correct_baseline).       #
# The reference-channel driver used to skip baseline subtraction entirely;     #
# these pin the extracted named formula and prove the DUT path is unchanged.   #
# --------------------------------------------------------------------------- #

class TestCorrectBaseline:
    def test_matches_legacy_inline_formula(self):
        # Reproduces the exact pre-refactor inline math that lived in
        # analyse_waveform:  baseline=mean(v[:n]); rms=std(v[:n]); v-baseline.
        rng = np.random.default_rng(0)
        v = rng.normal(0.0, 1.0, 500) + 0.37   # arbitrary DC offset
        n = 20
        corrected, baseline, rms = correct_baseline(v, n)
        assert baseline == pytest.approx(float(np.mean(v[:n])))
        assert rms == pytest.approx(float(np.std(v[:n])))
        np.testing.assert_allclose(corrected, v - float(np.mean(v[:n])))

    def test_removes_dc_offset(self):
        t = np.linspace(-20e-9, 180e-9, 500)
        pulse = -0.1 * np.exp(-0.5 * ((t - 60e-9) / 8e-9) ** 2)
        c0, b0, _ = correct_baseline(pulse, 20)
        c1, b1, _ = correct_baseline(pulse + 0.25, 20)   # +250 mV DC
        np.testing.assert_allclose(c0, c1, atol=1e-12)
        assert b1 - b0 == pytest.approx(0.25, abs=1e-9)

    def test_clamps_baseline_samples_and_handles_empty(self):
        v = np.arange(5, dtype=float)
        corrected, baseline, _ = correct_baseline(v, 999)   # n clamped to len
        assert baseline == pytest.approx(float(np.mean(v)))
        assert corrected.shape == v.shape
        # empty input must not raise
        c, b, r = correct_baseline(np.array([]), 20)
        assert c.size == 0 and b == 0.0 and r == 0.0


class TestAnalyseWaveformUnchangedByRefactor:
    def test_baseline_shifted_pulse_amplitude_and_charge_invariant(self):
        # DUT path golden: routing analyse_waveform's baseline through the
        # shared correct_baseline must leave amplitude/charge unchanged and
        # still immune to a DC offset (was true before the refactor, must stay
        # true after).
        t = np.linspace(-20e-9, 180e-9, 500)
        pulse = -0.1 * np.exp(-0.5 * ((t - 60e-9) / 8e-9) ** 2)
        r_flat = analyse_waveform(t, pulse)
        r_offset = analyse_waveform(t, pulse + 0.05)   # +50 mV DC
        assert r_offset.amplitude_V == pytest.approx(r_flat.amplitude_V, rel=1e-9)
        assert r_offset.charge_pC == pytest.approx(r_flat.charge_pC, rel=1e-9)
