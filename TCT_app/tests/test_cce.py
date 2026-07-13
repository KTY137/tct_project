"""analysis.cce.cce_vs_reference — identity with the original inline GUI
math it replaced (gui/analysis_panel.py _plot_cce / _export_cce_csv, before
this module existed).

Also covers analysis.efield_analysis.compute_cce_with_uncertainty /
CCEResult (D2) — CCE plus a per-point 1-sigma uncertainty propagated from
reference-sample scatter. Purely additive: the compute_cce/cce_vs_reference
tests above are untouched by it and keep passing unchanged."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from analysis.cce import cce_vs_reference
from analysis.efield_analysis import (
    CCEResult,
    compute_cce,
    compute_cce_with_uncertainty,
)


def _old_inline_formula(charges, q_ref):
    """Exact reproduction of the formula previously inlined in
    AnalysisPanel._plot_cce, kept here only to prove numeric identity."""
    return np.abs(np.array(charges)) / max(abs(q_ref), 1e-12)


@pytest.mark.parametrize("q_ref", [1.0, 0.5, -2.5, 100.0, 0.0, 1e-15])
def test_identity_with_old_inline_math(q_ref):
    charges = [-1.0, -2.0, -4.0, 0.0, 3.5, -0.001]
    expected = _old_inline_formula(charges, q_ref)
    actual = cce_vs_reference(charges, q_ref)
    np.testing.assert_array_equal(actual, expected)


def test_negative_charges_use_magnitude():
    cce = cce_vs_reference([-1.0, -2.0, -4.0], -4.0)
    np.testing.assert_allclose(cce, [0.25, 0.5, 1.0])


def test_q_ref_zero_is_clamped_not_a_zero_division():
    # No ZeroDivisionError / inf; matches the documented epsilon-clamp guard.
    cce = cce_vs_reference([1.0], 0.0)
    assert np.isfinite(cce).all()
    assert cce[0] == pytest.approx(1.0 / 1e-12)


def test_cce_can_exceed_one_when_reference_is_underestimated():
    cce = cce_vs_reference([-5.0], 1.0)
    assert cce[0] == pytest.approx(5.0)


def test_output_shape_matches_input():
    charges = np.linspace(-3, 3, 11)
    cce = cce_vs_reference(charges, 3.0)
    assert cce.shape == charges.shape


# --------------------------------------------------------------------------- #
# compute_cce_with_uncertainty / CCEResult (D2)                               #
# --------------------------------------------------------------------------- #

class TestHandComputedPropagation:
    def test_matches_hand_computed_sigma(self):
        charges = np.array([5.0, -10.0, 15.0])
        q_ref = np.array([9.0, 11.0])          # mean=10.0, std(ddof=0)=1.0
        r = compute_cce_with_uncertainty(charges, q_ref, charge_sigma_pC=0.5)

        np.testing.assert_allclose(r.cce, [0.5, 1.0, 1.5])
        assert r.ref_mean == pytest.approx(10.0)
        assert r.ref_std == pytest.approx(1.0)
        assert r.n_ref == 2
        # Hand-computed independently of the implementation's own formula:
        # sigma = sqrt((sigma_q/Qref)^2 + (cce*ref_std/Qref)^2),
        # Qref=10, sigma_q=0.5, ref_std=1.0 ->
        #   pt1: sqrt(0.05^2 + 0.05^2)  = 0.07071067811865477
        #   pt2: sqrt(0.05^2 + 0.10^2)  = 0.11180339887498948
        #   pt3: sqrt(0.05^2 + 0.15^2)  = 0.15811388300841897
        np.testing.assert_allclose(
            r.sigma,
            [0.07071067811865477, 0.11180339887498948, 0.15811388300841897],
        )
        assert r.q_term_included is True


class TestZeroAndNanRefHandling:
    def test_zero_ref_gives_nan_cce_and_sigma(self):
        r = compute_cce_with_uncertainty(np.array([1.0, 2.0]), np.array([0.0]))
        assert np.isnan(r.cce).all()
        assert np.isnan(r.sigma).all()
        assert r.notes != ""

    def test_all_nan_ref_gives_nan_cce_and_sigma(self):
        r = compute_cce_with_uncertainty(
            np.array([1.0, 2.0]), np.array([np.nan, np.nan])
        )
        assert np.isnan(r.cce).all()
        assert np.isnan(r.sigma).all()
        assert r.n_ref == 0
        assert np.isnan(r.ref_mean)

    def test_never_a_division_crash_on_degenerate_ref(self):
        # No ZeroDivisionError / warning-turned-exception; matches
        # compute_cce's degenerate-Q_ref "give up honestly" behaviour.
        r = compute_cce_with_uncertainty(np.array([1.0]), np.array([]))
        assert np.isnan(r.cce).all()
        assert np.isnan(r.sigma).all()

    def test_nan_charge_point_stays_nan_others_unaffected(self):
        r = compute_cce_with_uncertainty(
            np.array([np.nan, 5.0]), np.array([10.0, 10.0])
        )
        assert np.isnan(r.cce[0])
        assert np.isnan(r.sigma[0])
        assert np.isfinite(r.cce[1])
        assert np.isfinite(r.sigma[1])

    def test_ref_nans_are_filtered_not_counted(self):
        r = compute_cce_with_uncertainty(
            np.array([5.0]), np.array([9.0, 11.0, np.nan])
        )
        assert r.n_ref == 2
        assert r.ref_mean == pytest.approx(10.0)
        assert r.ref_std == pytest.approx(1.0)


class TestSigmaShrinksWithRefStd:
    def test_narrower_reference_scatter_gives_smaller_sigma(self):
        charges = np.array([5.0, 10.0])
        wide = compute_cce_with_uncertainty(charges, np.array([5.0, 15.0]))    # mean=10, std=5
        narrow = compute_cce_with_uncertainty(charges, np.array([9.0, 11.0]))  # mean=10, std=1
        assert narrow.ref_std < wide.ref_std
        assert np.all(narrow.sigma < wide.sigma)


class TestSigmaIsPureRefTermWhenChargeTermZero:
    def test_sigma_equals_cce_times_ref_relative_error(self):
        charges = np.array([3.0, -6.0, 9.0, 0.0])
        q_ref = np.array([18.0, 22.0])   # mean=20, std=2
        r = compute_cce_with_uncertainty(charges, q_ref)   # charge_sigma_pC default 0
        assert r.q_term_included is False
        ref_rel_err = r.ref_std / r.ref_mean
        np.testing.assert_allclose(r.sigma, np.abs(r.cce) * ref_rel_err)


class TestEquivalenceWithComputeCce:
    """cce field must equal compute_cce's output on the equivalent scalar
    reference -- compute_cce_with_uncertainty is additive, not a
    behaviour change to compute_cce."""

    @pytest.mark.parametrize("q_ref_scalar", [5.0, -5.0, 0.25])
    def test_cce_field_matches_compute_cce(self, q_ref_scalar):
        charges = np.array([-1.0, 2.0, -3.5, 0.0])
        expected = compute_cce(charges, reference_charge_pC=q_ref_scalar)
        r = compute_cce_with_uncertainty(charges, q_ref_scalar)
        np.testing.assert_array_equal(r.cce, expected)

    def test_degenerate_zero_reference_also_matches(self):
        charges = np.array([1.0, 2.0])
        expected = compute_cce(charges, reference_charge_pC=0.0)
        r = compute_cce_with_uncertainty(charges, 0.0)
        np.testing.assert_array_equal(r.cce, expected)


class TestCCEResultDataclassContract:
    def test_is_frozen(self):
        r = compute_cce_with_uncertainty(np.array([1.0]), np.array([2.0]))
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.cce = np.array([999.0])   # type: ignore[misc]

    def test_field_names(self):
        expected = {
            "cce", "sigma", "ref_mean", "ref_std", "n_ref",
            "charge_sigma_pC", "q_term_included", "notes",
        }
        actual = {f.name for f in dataclasses.fields(CCEResult)}
        assert actual == expected

    def test_charge_sigma_default_is_zero_and_echoed(self):
        r = compute_cce_with_uncertainty(np.array([1.0]), np.array([2.0]))
        assert r.charge_sigma_pC == 0.0
        assert r.q_term_included is False
