"""
Electric field profile reconstruction from an edge-TCT z-scan.

Theory
------
In a single-carrier (edge-illumination) regime with uniform carrier
injection at depth z, the drift velocity of carriers is:

    v_drift(z) = d_sensor / t_drift(z)

where d_sensor is the sensor thickness and t_drift is the measured pulse width.

The electric field is then:

    E(z) = v_drift(z) / mu

where mu is the carrier mobility (electrons: ~1350 cm²/Vs, holes: ~450 cm²/Vs
for silicon at ~20 °C, scaled by temperature if provided).

Reference:
  Kramberger et al., NIM A 476 (2002) 645–651.
  https://doi.org/10.1016/S0168-9002(01)01607-7

Usage
-----
    from analysis.efield_analysis import reconstruct_efield

    result = reconstruct_efield(
        z_positions_mm=scan_z,
        drift_times_s=scan_drift,
        sensor_thickness_mm=0.3,
        carrier="electrons",
    )   # -> EfieldResult with z_mm, E_V_cm, v_drift_cm_s, ...

Status
------
``estimate_depletion_voltage`` is used by the Analysis panel.  The E-field
reconstruction itself (``reconstruct_efield`` / ``silicon_mobility`` /
``compute_cce``) is NOT yet wired into any scan — it is the offline analysis
for edge-TCT z-scan drift-time data (planned feature, kept as the physics
roadmap).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# Mobility model (Jacoboni–Canali for silicon)
# ---------------------------------------------------------------------------

# Default mobilities at 300 K (cm²/Vs)
_MU0 = {"electrons": 1350.0, "holes": 450.0}

# Temperature coefficients (power-law exponent)
_MU_EXP = {"electrons": -2.42, "holes": -2.20}


def silicon_mobility(
    carrier: str = "electrons",
    temperature_K: float = 293.0,
) -> float:
    """
    Return silicon carrier mobility in cm²/Vs at the given temperature.
    Simple power-law scaling from 300 K reference values.

    Parameters
    ----------
    carrier : "electrons" or "holes"
    temperature_K : lattice temperature in Kelvin
    """
    if carrier not in _MU0:
        raise ValueError(f"carrier must be 'electrons' or 'holes', got {carrier!r}")
    mu0 = _MU0[carrier]
    exp = _MU_EXP[carrier]
    return mu0 * (temperature_K / 300.0) ** exp


# ---------------------------------------------------------------------------
# Main reconstruction
# ---------------------------------------------------------------------------

@dataclass
class EfieldResult:
    """Result of an electric field reconstruction from an edge-TCT z-scan."""
    z_mm:          np.ndarray  # depth positions (mm)
    drift_time_ns: np.ndarray  # measured drift times (ns)
    v_drift_cm_s:  np.ndarray  # reconstructed drift velocity (cm/s)
    E_V_cm:        np.ndarray  # reconstructed |E| field (V/cm)
    mobility_cm2_Vs: float     # mobility used (cm²/Vs)
    carrier:       str
    sensor_thickness_mm: float


def reconstruct_efield(
    z_positions_mm: np.ndarray,
    drift_times_s: np.ndarray,
    sensor_thickness_mm: float,
    carrier: str = "electrons",
    temperature_K: float = 293.0,
) -> EfieldResult:
    """
    Reconstruct the electric field profile E(z) from a z-scan drift-time map.

    Parameters
    ----------
    z_positions_mm : depth positions at which drift time was measured (mm)
    drift_times_s  : measured drift times in seconds (same length as z_positions_mm)
    sensor_thickness_mm : full sensor depletion depth / active thickness (mm)
    carrier        : "electrons" or "holes"
    temperature_K  : sensor temperature (affects mobility correction)

    Returns
    -------
    EfieldResult dataclass with z, drift_time, v_drift, E_V_cm, mobility used.

    Notes
    -----
    NaN entries in drift_times_s are propagated as NaN in the output.
    The z-axis is not resampled; pass sorted, evenly-spaced z if you want
    a smooth profile.
    """
    z   = np.asarray(z_positions_mm,  dtype=float)
    t_s = np.asarray(drift_times_s,   dtype=float)

    if z.shape != t_s.shape:
        raise ValueError("z_positions_mm and drift_times_s must have the same length.")

    d_cm = sensor_thickness_mm * 0.1  # mm → cm
    mu   = silicon_mobility(carrier, temperature_K)

    # v_drift = d / t_drift  [cm/s]
    v_cm_s = np.where(t_s > 0, d_cm / t_s, np.nan)

    # E = v / mu  [V/cm]
    E_V_cm = v_cm_s / mu

    return EfieldResult(
        z_mm=z,
        drift_time_ns=t_s * 1e9,
        v_drift_cm_s=v_cm_s,
        E_V_cm=E_V_cm,
        mobility_cm2_Vs=mu,
        carrier=carrier,
        sensor_thickness_mm=sensor_thickness_mm,
    )


# ---------------------------------------------------------------------------
# Charge collection efficiency from a bias scan
# ---------------------------------------------------------------------------

def compute_cce(
    charges_pC: np.ndarray,
    reference_charge_pC: float | None = None,
) -> np.ndarray:
    """
    Compute Charge Collection Efficiency (CCE) as a fraction.

    CCE(i) = Q(i) / Q_ref

    If reference_charge_pC is None, Q_ref = max(charges_pC) is used
    (useful for a bias scan where the sensor is fully depleted at the
    highest voltage point).

    Parameters
    ----------
    charges_pC : array of collected charges per scan point
    reference_charge_pC : expected charge at full collection

    Returns
    -------
    CCE array (same shape), values in [0, 1] range nominally.
    """
    # Raw TCT charge is signed (negative pulses) — CCE is a magnitude ratio.
    Q = np.abs(np.asarray(charges_pC, dtype=float))
    Q_ref = (abs(reference_charge_pC) if reference_charge_pC is not None
             else float(np.nanmax(Q)))
    if not np.isfinite(Q_ref) or Q_ref == 0:
        return np.full_like(Q, np.nan)
    return Q / Q_ref


# ---------------------------------------------------------------------------
# Depletion voltage estimation from a bias scan
# ---------------------------------------------------------------------------

def estimate_depletion_voltage(
    bias_V: np.ndarray,
    charges_pC: np.ndarray,
    saturation_fraction: float = 0.98,
) -> float | None:
    """
    Estimate depletion voltage as the bias point where collected charge
    reaches ``saturation_fraction`` of its maximum value.

    Parameters
    ----------
    bias_V : bias voltage array (any sign / order — |V| is sorted internally)
    charges_pC : collected charge at each bias point (signed raw values OK)
    saturation_fraction : fraction of max |charge| defining depletion

    Returns
    -------
    Estimated depletion voltage (V, positive), or None if it cannot be
    determined (fewer than 2 valid points, or no finite charge).
    """
    V = np.asarray(np.abs(bias_V), dtype=float)
    # Signed raw charge (negative pulses) would make nanmax pick the *least*
    # collected point — depletion is about the charge magnitude.
    Q = np.abs(np.asarray(charges_pC, dtype=float))
    if V.shape != Q.shape or len(V) < 2:
        return None

    # Sort by |bias| so interpolation works for any input ordering, and drop
    # non-finite points.
    ok = np.isfinite(V) & np.isfinite(Q)
    if np.count_nonzero(ok) < 2:
        return None
    order = np.argsort(V[ok])
    V, Q = V[ok][order], Q[ok][order]

    Q_max = float(np.max(Q))
    if Q_max <= 0:
        return None
    threshold = saturation_fraction * Q_max

    # First bias where the charge magnitude exceeds the threshold
    idx = int(np.argmax(Q >= threshold))

    # Linear interpolation between the bracketing points
    if idx == 0:
        return float(V[0])
    Q_lo, Q_hi = Q[idx - 1], Q[idx]
    V_lo, V_hi = V[idx - 1], V[idx]
    dQ = Q_hi - Q_lo
    if dQ == 0:
        return float(V[idx])
    return float(V_lo + (threshold - Q_lo) * (V_hi - V_lo) / dQ)
