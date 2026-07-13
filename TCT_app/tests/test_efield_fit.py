"""analysis.efield_analysis.fit_depletion_voltage / DepletionFitResult —
the honest depletion-voltage fit (bracket, ambiguity, uncertainty, quality)
that replaces the old bare-float threshold crossing, plus equivalence with
the thin ``estimate_depletion_voltage`` wrapper that existing callers
(gui/analysis_panel.py, test_bias_and_calibration.py, test_cce.py) still
use unchanged."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from analysis.efield_analysis import (
    DepletionFitResult,
    estimate_depletion_voltage,
    fit_depletion_voltage,
)


def _clean_saturating(step=10.0, v_max=300.0, v_knee=150.0, q_max=4.0):
    """A perfectly clean saturating charge-vs-bias curve: linear rise to the
    knee, then a flat plateau at q_max."""
    V = np.arange(0.0, v_max + step, step)
    Q = np.minimum(V / v_knee, 1.0) * q_max
    return V, Q


class TestCleanCurve:
    def test_matches_known_knee(self):
        V, Q = _clean_saturating()
        r = fit_depletion_voltage(V, Q)
        # threshold_frac=0.98 default -> analytic knee at 0.98*150 = 147 V,
        # exactly reconstructible by linear interpolation on this curve.
        assert r.v_dep == pytest.approx(147.0)
        assert r.n_crossings == 1
        assert r.ambiguous is False
        assert r.monotonic is True
        assert r.quality > 0.9
        assert r.bracket == (140.0, 150.0)
        assert r.n_points == len(V)

    def test_sigma_is_finite_and_positive(self):
        V, Q = _clean_saturating()
        r = fit_depletion_voltage(V, Q)
        assert r.v_dep_sigma is not None
        assert np.isfinite(r.v_dep_sigma)
        assert r.v_dep_sigma > 0.0


class TestNoisyMultipleCrossings:
    def _noisy(self):
        V = np.arange(0.0, 301.0, 5.0)
        Q_clean = np.minimum(V / 150.0, 1.0) * 4.0
        noise = np.zeros_like(V)
        idxs = np.where(V >= 120.0)[0]
        # Deterministic oscillation (no RNG) large enough to re-cross the
        # 0.98*Q_max threshold repeatedly near the knee/plateau.
        noise[idxs] = 0.35 * np.sin(idxs * 1.3)
        return V, Q_clean + noise

    def test_flagged_ambiguous_and_degraded(self):
        V, Q = self._noisy()
        clean_r = fit_depletion_voltage(*_clean_saturating())
        r = fit_depletion_voltage(V, Q)
        assert r.n_crossings > 1
        assert r.ambiguous is True
        assert r.quality < clean_r.quality
        assert r.notes != ""
        assert "crossing" in r.notes


class TestNonMonotonicDip:
    def test_dip_before_knee_flags_ambiguous(self):
        V, Q = _clean_saturating()
        dip_idx = int(np.where(V == 130.0)[0][0])
        Q = Q.copy()
        Q[dip_idx] *= 0.5   # a real dip, far above the 0.1%-of-Qmax tolerance
        r = fit_depletion_voltage(V, Q)
        assert r.monotonic is False
        assert r.ambiguous is True
        assert r.notes != ""
        assert "monotonic" in r.notes or "dip" in r.notes

    def test_clean_curve_is_monotonic(self):
        V, Q = _clean_saturating()
        r = fit_depletion_voltage(V, Q)
        assert r.monotonic is True
        assert r.ambiguous is False


class TestBracketSigmaScaling:
    def test_sparse_bracket_has_larger_sigma_than_dense(self):
        # Same underlying knee (147 V), wildly different sampling density.
        V_sparse = np.array([0.0, 300.0])
        Q_sparse = np.array([0.0, 4.0])
        r_sparse = fit_depletion_voltage(V_sparse, Q_sparse)

        V_dense, Q_dense = _clean_saturating(step=2.0)
        r_dense = fit_depletion_voltage(V_dense, Q_dense)

        assert r_sparse.v_dep_sigma is not None
        assert r_dense.v_dep_sigma is not None
        assert r_sparse.v_dep_sigma > r_dense.v_dep_sigma
        assert r_sparse.quality < r_dense.quality


class TestDegenerateInputs:
    def test_fewer_than_two_points_returns_none(self):
        r = fit_depletion_voltage(np.array([100.0]), np.array([1.0]))
        assert r.v_dep is None
        assert r.v_dep_sigma is None
        assert r.quality == 0.0
        assert r.notes != ""

    def test_empty_arrays_return_none(self):
        r = fit_depletion_voltage(np.array([]), np.array([]))
        assert r.v_dep is None
        assert r.quality == 0.0

    def test_all_nan_returns_none(self):
        r = fit_depletion_voltage(np.array([0.0, -100.0]), np.array([np.nan, np.nan]))
        assert r.v_dep is None
        assert r.v_dep_sigma is None
        assert r.quality == 0.0
        assert r.n_points == 0

    def test_all_zero_charge_returns_none(self):
        V = np.array([0.0, 50.0, 100.0, 150.0])
        Q = np.zeros_like(V)
        r = fit_depletion_voltage(V, Q)
        assert r.v_dep is None
        assert r.quality == 0.0
        assert r.notes != ""

    def test_shape_mismatch_returns_none_not_raise(self):
        r = fit_depletion_voltage(np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0]))
        assert r.v_dep is None
        assert r.quality == 0.0

    def test_never_raises_on_garbage(self):
        # Feeds a GUI tile -- must degrade gracefully, never throw.
        r = fit_depletion_voltage(np.array([np.inf, -np.inf, np.nan]),
                                   np.array([np.inf, np.nan, -np.inf]))
        assert r.v_dep is None


class TestSignConventions:
    """Preserve the sign conventions the pre-existing tests
    (test_bias_and_calibration.py) already lock in: negative bias, negative
    raw (signed) charge, unsorted input -- all resolved via |V|/|Q|."""

    def test_negative_bias_negative_charge(self):
        v = -np.arange(0.0, 301.0, 20.0)
        q = -np.minimum(np.abs(v) / 150.0, 1.0) * 4.0
        r = fit_depletion_voltage(v, q)
        assert r.v_dep is not None
        assert 130.0 <= r.v_dep <= 160.0
        assert r.ambiguous is False

    def test_unsorted_input(self):
        v = np.array([-300.0, -50.0, -200.0, -100.0, -250.0, -150.0, 0.0])
        q = -np.minimum(np.abs(v) / 150.0, 1.0) * 4.0
        r = fit_depletion_voltage(v, q)
        assert r.v_dep is not None
        assert 130.0 <= r.v_dep <= 160.0


class TestWrapperEquivalence:
    """estimate_depletion_voltage must stay a thin wrapper: identical output
    to fit_depletion_voltage(...).v_dep, on every input shape this module
    exercises (clean, noisy/ambiguous, sparse, negative-sign, degenerate)."""

    @pytest.mark.parametrize("V, Q", [
        _clean_saturating(),
        (-np.arange(0.0, 301.0, 20.0),
         -np.minimum(np.abs(-np.arange(0.0, 301.0, 20.0)) / 150.0, 1.0) * 4.0),
        (np.array([0.0, 300.0]), np.array([0.0, 4.0])),
        (np.array([100.0]), np.array([1.0])),
        (np.array([0.0, -100.0]), np.array([np.nan, np.nan])),
    ])
    def test_wrapper_matches_fit_v_dep(self, V, Q):
        a = estimate_depletion_voltage(V, Q)
        b = fit_depletion_voltage(V, Q).v_dep
        assert a == b

    def test_wrapper_passes_through_saturation_fraction(self):
        V, Q = _clean_saturating()
        a = estimate_depletion_voltage(V, Q, saturation_fraction=0.9)
        b = fit_depletion_voltage(V, Q, threshold_frac=0.9).v_dep
        assert a == b
        assert a != estimate_depletion_voltage(V, Q)   # different threshold, different answer


class TestDataclassContract:
    def test_is_frozen(self):
        V, Q = _clean_saturating()
        r = fit_depletion_voltage(V, Q)
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.v_dep = 999.0   # type: ignore[misc]

    def test_field_names(self):
        expected = {
            "v_dep", "v_dep_sigma", "method", "threshold_frac", "n_points",
            "bracket", "n_crossings", "monotonic", "ambiguous", "quality",
            "notes",
        }
        actual = {f.name for f in dataclasses.fields(DepletionFitResult)}
        assert actual == expected

    def test_method_default(self):
        V, Q = _clean_saturating()
        r = fit_depletion_voltage(V, Q)
        assert r.method == "threshold_crossing"
