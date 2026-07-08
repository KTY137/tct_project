"""analysis.cce.cce_vs_reference — identity with the original inline GUI
math it replaced (gui/analysis_panel.py _plot_cce / _export_cce_csv, before
this module existed)."""
from __future__ import annotations

import numpy as np
import pytest

from analysis.cce import cce_vs_reference


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
