"""Laser normalisation helpers."""
from __future__ import annotations


def normalise(dut_charge_pC: float, ref_charge_pC: float) -> float:
    """
    Return laser-normalised DUT charge.

    Q_norm = Q_DUT / Q_ref

    Returns 0.0 when the reference signal is zero or near-zero to
    avoid division by zero.
    """
    if abs(ref_charge_pC) < 1e-12:
        return 0.0
    return dut_charge_pC / ref_charge_pC
