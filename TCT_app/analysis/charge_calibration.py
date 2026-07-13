"""
Charge calibration for TCT signals.

The waveform analysis (:func:`analysis.waveform_analysis.analyse_waveform`)
produces a *raw* integrated charge in pC computed as ``∫V_scope dt / 50Ω``.
That implicitly assumes amplifier gain = 1 and a 50 Ω path, so it is not an
absolute charge.  This module maps that raw value to a meaningful charge using
one of two methods, selected in the ``charge_calibration`` config block:

``electronics``
    Analytic correction for the readout chain — divide by the amplifier gain
    (or transimpedance).  Absolute charge in pC.  Available immediately.

``reference_diode``
    Express the DUT charge in MIP-equivalent units (or absolute pC / electrons)
    using a calibrated reference PIN diode.  A minimum-ionising particle deposits
    ~75 e-h pairs per µm in silicon, so a reference of known thickness fixes the
    scale.  The ``k_factor`` is produced by the calibration routine and stored
    back into the config.

``none``
    No calibration — the raw integral is reported as pC (legacy behaviour).
"""
from __future__ import annotations

from dataclasses import dataclass

# Silicon physics constants
ELECTRON_CHARGE_C = 1.602176634e-19
MIP_EH_PER_UM = 75.0          # electron-hole pairs per µm for a MIP in silicon

def q_one_mip_pC(thickness_um: float) -> float:
    """Charge a MIP deposits in silicon of the given thickness, in pC."""
    return MIP_EH_PER_UM * thickness_um * ELECTRON_CHARGE_C * 1e12


@dataclass
class ChargeCalibration:
    method: str = "none"                     # none | electronics | reference_diode
    termination_ohm: float = 50.0
    amp_gain: float = 1.0                     # V/V voltage gain of the chain
    transimpedance_ohm: float | None = None  # V/A, if a TIA is used
    output_units: str = "pC"                 # pC | MIP | e
    diode_thickness_um: float = 300.0
    q_ref_raw_pC: float | None = None        # raw integral measured on the reference
    k_factor: float | None = None            # absolute pC per raw pC
    calibrated_at: str | None = None         # ISO timestamp of last calibration

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_config(cls, cfg: dict | None) -> "ChargeCalibration":
        cfg = cfg or {}
        ref = cfg.get("reference", {}) or {}
        return cls(
            method=str(cfg.get("method", "none")).lower(),
            termination_ohm=float(cfg.get("termination_ohm", 50.0)),
            amp_gain=float(cfg.get("amp_gain", 1.0)),
            transimpedance_ohm=_opt_float(cfg.get("transimpedance_ohm")),
            output_units=str(cfg.get("output_units", "pC")),
            diode_thickness_um=float(ref.get("diode_thickness_um", 300.0)),
            q_ref_raw_pC=_opt_float(ref.get("q_ref_raw_pC")),
            k_factor=_opt_float(ref.get("k_factor")),
            calibrated_at=ref.get("calibrated_at"),
        )

    def to_config(self) -> dict:
        """Serialise back to the devices.yaml ``charge_calibration`` shape."""
        return {
            "method": self.method,
            "termination_ohm": self.termination_ohm,
            "amp_gain": self.amp_gain,
            "transimpedance_ohm": self.transimpedance_ohm,
            "output_units": self.output_units,
            "reference": {
                "diode_thickness_um": self.diode_thickness_um,
                "q_ref_raw_pC": self.q_ref_raw_pC,
                "k_factor": self.k_factor,
                "calibrated_at": self.calibrated_at,
            },
        }

    # ------------------------------------------------------------------ #
    # Application                                                          #
    # ------------------------------------------------------------------ #

    def apply(self, raw_pC: float) -> tuple[float | None, str | None]:
        """Map a raw integrated charge (pC) to a calibrated (value, units).

        The raw integral is signed (negative for the usual negative TCT
        pulse); the calibrated output is the *magnitude* of the collected
        charge in the chosen units — the signed raw value stays available as
        ``dut_charge_pC``.  Returns ``(None, None)`` when no calibration is
        configured/available, in which case callers keep reporting the raw
        value as pC.
        """
        if raw_pC is None:
            return None, None
        raw_mag_pC = abs(raw_pC)

        if self.method == "electronics":
            # The raw integral is ∫V dt / termination_ohm — the analysis layer
            # takes the same termination_ohm from the config (DeviceManager
            # .analysis_kwargs falls back to it), so no 50 Ω re-scaling here.
            if self.transimpedance_ohm:
                # Q = ∫V dt / R_TIA;  ∫V dt = raw·1e-12·termination_ohm
                val = raw_mag_pC * self.termination_ohm / self.transimpedance_ohm
            else:
                gain = self.amp_gain if abs(self.amp_gain) > 1e-12 else 1.0
                val = raw_mag_pC / gain
            return float(val), "pC"

        if self.method == "reference_diode":
            if not self.k_factor:
                return None, None
            absolute_pC = raw_mag_pC * self.k_factor      # k maps |raw| pC → absolute pC
            if self.output_units == "MIP":
                qm = q_one_mip_pC(self.diode_thickness_um)
                return (float(absolute_pC / qm) if qm else None), "MIP"
            if self.output_units == "e":
                return float(absolute_pC * 1e-12 / ELECTRON_CHARGE_C), "e"
            return float(absolute_pC), "pC"

        return None, None

    # ------------------------------------------------------------------ #
    # Reference-diode routine                                              #
    # ------------------------------------------------------------------ #

    def compute_reference(
        self,
        q_ref_raw_pC: float,
        thickness_um: float,
        expected_pC: float | None = None,
    ) -> tuple[float, float]:
        """Compute (k_factor, expected_charge_pC) from a reference measurement.

        ``expected_pC`` is the charge the reference *should* have collected for
        this laser setting.  When omitted it defaults to the MIP charge for the
        reference thickness (the common "set the laser to 1 MIP in the reference"
        convention), so a DUT reported in MIP units reads 1.0 for a reference-
        equivalent pulse.
        """
        expected = expected_pC if expected_pC is not None else q_one_mip_pC(thickness_um)
        # The raw integral is signed (negative for the usual negative TCT
        # pulse); the calibration factor must map |raw| → the positive
        # expected charge, so use the magnitude.
        k = expected / abs(q_ref_raw_pC) if q_ref_raw_pC else float("nan")
        return float(k), float(expected)


def _opt_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
