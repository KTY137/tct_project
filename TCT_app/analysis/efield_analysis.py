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

@dataclass(frozen=True)
class DepletionFitResult:
    """
    Result of a depletion-voltage fit from a bias (IV) scan's collected
    charge magnitude vs |bias voltage| (see ``fit_depletion_voltage``).

    Field notes
    -----------
    v_dep, v_dep_sigma : depletion voltage estimate and its 1-sigma
        uncertainty (V, positive magnitude), or ``None`` if the sweep did
        not have enough usable data to fit anything.
    threshold_frac : the ``|Q|`` fraction of Q_max that defines "depleted"
        (0.98 by default — same convention as before this dataclass existed).
    n_points : number of finite, sanitized (|V|, |Q|) pairs actually used.
    bracket : the ``(|V_lo|, |V_hi|)`` pair straddling the threshold
        crossing, or ``None`` when the crossing sits at the very first
        sampled point (nothing to bracket below it).
    n_crossings : how many times |Q| crosses the threshold across the whole
        sorted sweep (both directions). 1 is the normal, unambiguous case
        for a clean saturating curve; >1 means noise or a non-monotonic
        curve is making the "crossing" ill-defined.
    monotonic : whether |Q| is non-decreasing (within a 0.1%-of-Q_max
        tolerance, to absorb float/measurement noise without masking a real
        dip) from the first sample up to and including the crossing point.
    ambiguous : ``n_crossings > 1 or not monotonic`` — the load-bearing
        flag a caller should check before trusting ``v_dep`` at face value;
        do not infer this from ``quality`` alone.
    quality : 0-1 heuristic, see "Quality heuristic" below.
    method : fit method name, currently always ``"threshold_crossing"``
        (linear interpolation to the threshold — same algorithm the old
        bare-float ``estimate_depletion_voltage`` used).
    notes : short human-readable reason(s) when quality/certainty is
        degraded; empty string when there is nothing to flag.

    Quality heuristic
    ------------------
    ``quality`` is the unweighted mean of three 0-1 subscores:

    - bracket density: ``1 - min(bracket_width / V_range, 1)`` where
      ``bracket_width`` is the spacing between the two points straddling
      the crossing and ``V_range`` is the full sweep's |V| span — a
      crossing pinned down by two closely-spaced points scores near 1, one
      bracketed by two far-apart points (sparse sampling) scores near 0.
      When the crossing is unbracketed (``bracket is None``) this subscore
      is fixed at 0.3 (inherently less certain — see ``bracket``'s note).
    - plateau flatness: ``1 - min(std(|Q| at/after the crossing) / Q_max, 1)``
      — a flat plateau beyond the knee (as physics predicts once fully
      depleted) scores near 1; a scattered/noisy plateau scores lower. If
      fewer than 2 points lie at/after the crossing there is nothing to
      judge flatness by, so this subscore defaults to 1.0 (not penalized).
    - monotonicity: 1.0 if ``monotonic`` is True, else 0.0.

    Multiple threshold crossings are not scored directly in this average;
    they degrade quality indirectly, because the same noise that causes
    re-crossings usually also breaks plateau flatness and/or monotonicity.
    ``ambiguous`` (via ``n_crossings``) is the explicit, load-bearing signal
    for "don't trust this crossing" — treat ``quality`` as a continuous
    confidence dial, not a substitute for checking ``ambiguous``.
    """
    v_dep: float | None
    v_dep_sigma: float | None
    threshold_frac: float
    n_points: int
    bracket: tuple[float, float] | None
    n_crossings: int
    monotonic: bool
    ambiguous: bool
    quality: float
    method: str = "threshold_crossing"
    notes: str = ""


def fit_depletion_voltage(
    bias_V: np.ndarray,
    charges_pC: np.ndarray,
    threshold_frac: float = 0.98,
) -> DepletionFitResult:
    """
    Fit the depletion voltage from a bias scan as the |V| point where the
    collected charge magnitude first reaches ``threshold_frac`` of its
    sweep maximum, linearly interpolated between the bracketing points —
    plus fit-quality diagnostics (see ``DepletionFitResult``).

    This never raises on bad/degenerate input (it feeds a GUI tile): fewer
    than 2 usable points, or a non-positive max charge, yields a result with
    ``v_dep=None``, ``quality=0.0``, and a ``notes`` string saying why.

    Parameters
    ----------
    bias_V : bias voltage array (any sign / order — |V| is sorted internally)
    charges_pC : collected charge at each bias point (signed raw values OK
        — magnitude is what defines "depleted")
    threshold_frac : fraction of max |charge| defining the depletion knee

    Returns
    -------
    DepletionFitResult
    """
    def _degenerate(n_points: int, notes: str) -> DepletionFitResult:
        return DepletionFitResult(
            v_dep=None, v_dep_sigma=None, threshold_frac=threshold_frac,
            n_points=n_points, bracket=None, n_crossings=0,
            monotonic=False, ambiguous=True, quality=0.0, notes=notes,
        )

    V_raw = np.asarray(bias_V, dtype=float)
    Q_raw = np.asarray(charges_pC, dtype=float)
    if V_raw.shape != Q_raw.shape:
        return _degenerate(0, "bias_V and charges_pC shapes differ")

    # Signed raw charge (negative pulses) would make nanmax pick the *least*
    # collected point — depletion is about the charge magnitude.
    V_abs = np.abs(V_raw)
    Q_abs = np.abs(Q_raw)
    ok = np.isfinite(V_abs) & np.isfinite(Q_abs)
    n_ok = int(np.count_nonzero(ok))
    if n_ok < 2:
        return _degenerate(n_ok, f"fewer than 2 finite (|V|, |Q|) points ({n_ok} usable)")

    # Sort by |bias| so interpolation works for any input ordering.
    order = np.argsort(V_abs[ok])
    V = V_abs[ok][order]
    Q = Q_abs[ok][order]
    n_points = len(V)

    Q_max = float(np.max(Q))
    if not np.isfinite(Q_max) or Q_max <= 0:
        return _degenerate(n_points, "max collected |charge| is non-positive")

    threshold = threshold_frac * Q_max

    # Crossings across the *whole* sorted sweep (both directions) — >1 means
    # noise or non-monotonic data is making "the" crossing ill-defined.
    below = Q < threshold
    n_crossings = int(np.count_nonzero(below[1:] != below[:-1]))

    # First bias where the charge magnitude reaches the threshold. Always
    # found: the Q_max point itself satisfies Q >= threshold for frac <= 1.
    idx = int(np.argmax(Q >= threshold))

    # "Non-decreasing up to the crossing" within a tolerance that absorbs
    # float/measurement noise but not a real dip.
    tol = 1e-3 * Q_max
    up_to = Q[: idx + 1]
    monotonic = bool(np.all(np.diff(up_to) >= -tol)) if len(up_to) > 1 else True

    notes_parts: list[str] = []

    if idx == 0:
        v_dep = float(V[0])
        bracket = None
        notes_parts.append(
            "threshold already exceeded at the lowest sampled |V|; true "
            "V_dep may lie below the sampled range"
        )
        dQ = Q[1] - Q[0]
        dV = V[1] - V[0]
        bracket_half_width = dV / 2.0
    else:
        V_lo, V_hi = V[idx - 1], V[idx]
        Q_lo, Q_hi = Q[idx - 1], Q[idx]
        bracket = (float(V_lo), float(V_hi))
        dQ = Q_hi - Q_lo
        dV = V_hi - V_lo
        v_dep = float(V[idx]) if dQ == 0 else float(
            V_lo + (threshold - Q_lo) * (V_hi - V_lo) / dQ)
        bracket_half_width = dV / 2.0

    slope = (dQ / dV) if dV != 0 else 0.0

    ambiguous = (n_crossings > 1) or (not monotonic)
    if n_crossings > 1:
        notes_parts.append(f"{n_crossings} threshold crossings found (noisy sweep)")
    if not monotonic:
        notes_parts.append("|charge| is not monotonic up to the crossing (possible dip)")

    # --- sigma: bracket half-width combined with local charge scatter,
    # propagated through the local dQ/dV slope at the crossing -----------
    # Charge-noise proxy: scatter of |Q| on the plateau (points at/after the
    # crossing). Physically those points should sit flat at ~Q_max, so their
    # spread is attributable to measurement noise, not to the real rise.
    post = Q[idx:]
    sigma_Q = float(np.std(post)) if len(post) >= 2 else None

    V_range = max(V[-1] - V[0], 1e-12)
    slope_scale = Q_max / V_range
    degenerate_slope = abs(slope) < 1e-6 * slope_scale

    if degenerate_slope:
        # Cannot propagate charge scatter through a ~flat local slope without
        # pretending precision — widen sigma to the full sweep span instead.
        v_dep_sigma = float(max(V_range, bracket_half_width, 1e-9))
        notes_parts.append(
            "local dQ/dV at the crossing is ~flat; V_dep_sigma widened to "
            "the sweep range instead of being propagated through the slope"
        )
    else:
        sigma_from_charge = (sigma_Q / abs(slope)) if sigma_Q is not None else 0.0
        v_dep_sigma = float(np.hypot(bracket_half_width, sigma_from_charge))
        if sigma_Q is None:
            notes_parts.append(
                "fewer than 2 points on the plateau beyond the crossing; "
                "V_dep_sigma reflects bracket spacing only (no charge-scatter term)"
            )

    # --- quality (see DepletionFitResult docstring for the formula) -----
    if bracket is not None:
        bracket_width = bracket[1] - bracket[0]
        density_score = 1.0 - min(bracket_width / V_range, 1.0)
    else:
        density_score = 0.3

    if len(post) >= 2:
        flatness_score = 1.0 - min(sigma_Q / Q_max, 1.0)
    else:
        flatness_score = 1.0

    monotonic_score = 1.0 if monotonic else 0.0

    quality = float(np.clip(
        (density_score + flatness_score + monotonic_score) / 3.0, 0.0, 1.0))

    return DepletionFitResult(
        v_dep=v_dep,
        v_dep_sigma=v_dep_sigma,
        threshold_frac=threshold_frac,
        n_points=n_points,
        bracket=bracket,
        n_crossings=n_crossings,
        monotonic=monotonic,
        ambiguous=ambiguous,
        quality=quality,
        notes="; ".join(notes_parts),
    )


def estimate_depletion_voltage(
    bias_V: np.ndarray,
    charges_pC: np.ndarray,
    saturation_fraction: float = 0.98,
) -> float | None:
    """
    Estimate depletion voltage as the bias point where collected charge
    reaches ``saturation_fraction`` of its maximum value.

    Thin wrapper: defers to ``fit_depletion_voltage`` (which additionally
    reports fit quality, bracket/ambiguity info, and an uncertainty) and
    returns just its ``v_dep`` field, for existing callers that only want
    the bare number.

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
    return fit_depletion_voltage(
        bias_V, charges_pC, threshold_frac=saturation_fraction).v_dep
