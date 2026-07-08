"""
Charge Collection Efficiency (CCE) normalised against a user-supplied
reference charge — the manual/interactive counterpart to
:func:`analysis.efield_analysis.compute_cce`, used by the Analysis panel's
"CCE vs. Bias" tab.

Definition
----------
::

    CCE(i) = |Q(i)| / |Q_ref|

``Q(i)`` is the (signed) collected charge at scan point ``i``, in pC. TCT
pulses are conventionally negative, so the numerator takes the magnitude —
see the sign-handling note in ``analysis/charge_calibration.py``. ``Q_ref``
is a single reference charge in pC — the collected charge at full
depletion for the same laser/bias setup — entered by the operator in the
"Q_ref (full depletion)" field. The result is dimensionless, nominally in
``[0, 1]``, though nothing here clamps the output: a point that reports more
charge than ``Q_ref`` (an under-estimated reference, or noise) yields
``CCE > 1`` on purpose, so the anomaly stays visible instead of being
silently clipped.

Reference-normalisation semantics
----------------------------------
This is deliberately the *manual* counterpart to
:func:`analysis.efield_analysis.compute_cce`: that function *derives*
``Q_ref`` automatically (defaults to ``max(|charges|)`` when none is given)
and returns an all-NaN array when no reference can be established —
appropriate for an unattended bias-scan reduction with no operator in the
loop. :func:`cce_vs_reference` instead always takes an explicit,
operator-supplied ``Q_ref`` (the GUI spin box), so a ``Q_ref`` of exactly 0
is a *user-input* edge case here, not a "no data" case — see the guard
below.

``q_ref == 0`` guard
---------------------
``reference_charge_pC`` is clamped to at least ``min_reference_pC`` in
magnitude before dividing, so an operator who has not (yet) set a sensible
``Q_ref`` gets a large-but-finite CCE rather than a ``ZeroDivisionError``
crashing an interactive plot callback. This preserves the original inline
GUI implementation's behaviour exactly (see git history of
``gui/analysis_panel.py``) and is a *different* policy from
``compute_cce``'s "return NaN" — deliberately, because a real ``Q_ref`` is
never physically 0 (full depletion always collects a non-zero charge), so
this guard exists purely to keep the interactive plot from throwing, not to
signal a meaningful physics result. In the current GUI the spin box floor
is 0.001 pC (see ``AnalysisPanel._spin_ref_charge``), so ``Q_ref == 0`` is
not reachable through the UI today; the guard exists for callers of this
function directly and for robustness if that floor ever changes.

Units
-----
``charges_pC``, ``reference_charge_pC``, ``min_reference_pC``: picocoulombs
(pC). Returns a dimensionless ``ndarray`` of the same shape as
``charges_pC``.
"""
from __future__ import annotations

import numpy as np


def cce_vs_reference(
    charges_pC,
    reference_charge_pC: float,
    *,
    min_reference_pC: float = 1e-12,
) -> np.ndarray:
    """``CCE(i) = |charges_pC[i]| / max(|reference_charge_pC|, min_reference_pC)``.

    Parameters
    ----------
    charges_pC : array_like
        Collected charge per point, in pC (signed; magnitude is used).
    reference_charge_pC : float
        Operator-supplied reference (full-depletion) charge, in pC.
    min_reference_pC : float, default 1e-12
        Floor applied to ``|reference_charge_pC|`` before dividing — see
        the "q_ref == 0 guard" section of the module docstring.

    Returns
    -------
    ndarray
        Same shape as ``charges_pC``; dimensionless CCE values.
    """
    q = np.abs(np.asarray(charges_pC, dtype=float))
    q_ref = max(abs(reference_charge_pC), min_reference_pC)
    return q / q_ref
