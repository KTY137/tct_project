"""Unit tests for analysis/waveform_analysis.py.

The critical cases are NEGATIVE pulses (the normal TCT polarity): the old CFD
implementation mixed |v| with the signed slope and returned wrong timing for
them, and charge/CCE signs were inconsistent downstream.
"""
import numpy as np
import pytest

from analysis.waveform_analysis import analyse_waveform


def _pulse(polarity: int, amp_V: float = 0.1, t0: float = 60e-9,
           sigma: float = 8e-9, baseline: float = 0.0,
           n: int = 500, t_start: float = -20e-9, t_stop: float = 180e-9):
    """Gaussian test pulse with a flat pre-trigger baseline region."""
    t = np.linspace(t_start, t_stop, n)
    v = baseline + polarity * amp_V * np.exp(-0.5 * ((t - t0) / sigma) ** 2)
    return t, v


class TestPolarityAndAmplitude:
    def test_positive_pulse(self):
        t, v = _pulse(+1)
        r = analyse_waveform(t, v)
        assert r.polarity == +1
        assert r.amplitude_V == pytest.approx(0.1, rel=0.02)

    def test_negative_pulse(self):
        t, v = _pulse(-1)
        r = analyse_waveform(t, v)
        assert r.polarity == -1
        assert r.amplitude_V == pytest.approx(0.1, rel=0.02)  # always magnitude

    def test_baseline_subtracted(self):
        t, v = _pulse(-1, baseline=0.05)
        r = analyse_waveform(t, v)
        assert r.amplitude_V == pytest.approx(0.1, rel=0.02)


class TestCharge:
    def test_charge_sign_follows_pulse(self):
        t, vneg = _pulse(-1)
        t2, vpos = _pulse(+1)
        rneg = analyse_waveform(t, vneg)
        rpos = analyse_waveform(t2, vpos)
        assert rneg.charge_pC < 0
        assert rpos.charge_pC > 0
        assert abs(rneg.charge_pC) == pytest.approx(abs(rpos.charge_pC), rel=1e-6)

    def test_charge_value(self):
        # Gaussian integral: amp * sigma * sqrt(2*pi); window 20-150 ns covers
        # the pulse at t0=60 ns, sigma=8 ns almost fully.
        t, v = _pulse(+1)
        r = analyse_waveform(t, v, termination_ohm=50.0)
        expected_C = 0.1 * 8e-9 * np.sqrt(2 * np.pi) / 50.0
        assert r.charge_pC == pytest.approx(expected_C * 1e12, rel=0.01)

    def test_termination_scales_charge(self):
        t, v = _pulse(+1)
        q50 = analyse_waveform(t, v, termination_ohm=50.0).charge_pC
        q100 = analyse_waveform(t, v, termination_ohm=100.0).charge_pC
        assert q50 == pytest.approx(2 * q100, rel=1e-9)

    def test_empty_window_yields_zero_not_nan(self):
        t, v = _pulse(-1)
        r = analyse_waveform(t, v, integration_window_s=(1e-3, 2e-3))
        assert r.charge_pC == 0.0


class TestTiming:
    def test_cfd_inside_leading_edge_negative_pulse(self):
        """Regression: old CFD used the signed slope → time outside the pulse."""
        t, v = _pulse(-1, t0=60e-9, sigma=8e-9)
        r = analyse_waveform(t, v, cfd_fraction=0.3)
        assert r.cfd_time_s is not None
        # 30 % crossing of a Gaussian at t0=60ns, sigma=8ns:
        # t = t0 - sigma*sqrt(2*ln(1/0.3)) ≈ 60ns - 12.4ns
        expected = 60e-9 - 8e-9 * np.sqrt(2 * np.log(1 / 0.3))
        assert r.cfd_time_s == pytest.approx(expected, abs=1e-9)

    def test_cfd_same_for_both_polarities(self):
        t, vneg = _pulse(-1)
        _, vpos = _pulse(+1)
        rneg = analyse_waveform(t, vneg)
        rpos = analyse_waveform(t, vpos)
        assert rneg.cfd_time_s == pytest.approx(rpos.cfd_time_s, abs=1e-12)

    def test_drift_time_symmetric_pulse(self):
        t, v = _pulse(-1, t0=60e-9, sigma=8e-9)
        r = analyse_waveform(t, v, onset_threshold_fraction=0.1)
        assert r.onset_time_s is not None and r.trailing_time_s is not None
        # Gaussian: onset/trailing symmetric around t0
        mid = 0.5 * (r.onset_time_s + r.trailing_time_s)
        assert mid == pytest.approx(60e-9, abs=1e-9)
        assert r.drift_time_s == pytest.approx(
            2 * 8e-9 * np.sqrt(2 * np.log(10)), rel=0.05)

    def test_rise_time_positive(self):
        t, v = _pulse(-1)
        r = analyse_waveform(t, v)
        assert r.rise_time_s is not None and r.rise_time_s > 0


class TestInputValidation:
    def test_empty_arrays_raise(self):
        with pytest.raises(ValueError):
            analyse_waveform(np.array([]), np.array([]))

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            analyse_waveform(np.arange(10, dtype=float), np.zeros(9))

    def test_too_short_for_baseline_raises(self):
        with pytest.raises(ValueError):
            analyse_waveform(np.arange(10, dtype=float), np.zeros(10),
                             baseline_samples=20)

    def test_bad_termination_raises(self):
        t, v = _pulse(-1)
        with pytest.raises(ValueError):
            analyse_waveform(t, v, termination_ohm=0.0)

    def test_flat_waveform_no_signal(self):
        t = np.linspace(0, 200e-9, 300)
        v = np.zeros_like(t)
        r = analyse_waveform(t, v)
        assert r.polarity == 0
        assert r.amplitude_V == 0.0
        assert r.charge_pC == 0.0
        assert r.cfd_time_s is None and r.rise_time_s is None
