"""Bias-supply setpoint clamp + charge-calibration sign handling."""
import numpy as np
import pytest

from devices.base import DeviceError
from devices.bias_supply_iseg import IsegBiasSupply
from analysis.charge_calibration import ChargeCalibration, q_one_mip_pC
from analysis.efield_analysis import compute_cce, estimate_depletion_voltage


class TestVoltageClamp:
    def _supply(self, range_V=1000.0):
        s = IsegBiasSupply(simulation=True, voltage_range_V=range_V)
        s.connect()
        return s

    def test_setpoint_within_range_ok(self):
        s = self._supply()
        s.set_voltage(-500.0)
        assert s.setpoint_V == -500.0

    def test_setpoint_beyond_range_raises(self):
        s = self._supply(range_V=1000.0)
        with pytest.raises(DeviceError, match="voltage_range_V"):
            s.set_voltage(-1500.0)

    def test_ramp_beyond_range_raises_before_ramping(self):
        s = self._supply(range_V=1000.0)
        with pytest.raises(DeviceError, match="voltage_range_V"):
            s.ramp_to(9999.0, step_V=100.0, delay_s=0.0)
        assert s.setpoint_V == 0.0     # nothing was applied

    def test_ramp_to_zero_always_allowed(self):
        s = self._supply(range_V=1000.0)
        s.ramp_to(-200.0, step_V=100.0, delay_s=0.0)
        s.ramp_to(0.0, step_V=100.0, delay_s=0.0)
        assert s.setpoint_V == 0.0


class TestChargeCalibrationSigns:
    def test_reference_k_positive_for_negative_raw(self):
        cal = ChargeCalibration(method="reference_diode",
                                diode_thickness_um=300.0)
        k, expected = cal.compute_reference(q_ref_raw_pC=-2.5, thickness_um=300.0)
        assert k > 0
        assert expected == pytest.approx(q_one_mip_pC(300.0))

    def test_apply_reference_diode_returns_positive(self):
        cal = ChargeCalibration(method="reference_diode", k_factor=1.5,
                                output_units="MIP", diode_thickness_um=300.0)
        val, units = cal.apply(-2.0)     # negative raw pulse
        assert units == "MIP"
        assert val is not None and val > 0

    def test_apply_electronics_gain(self):
        cal = ChargeCalibration(method="electronics", amp_gain=100.0)
        val, units = cal.apply(-50.0)
        assert units == "pC"
        assert val == pytest.approx(0.5)

    def test_apply_none_method(self):
        cal = ChargeCalibration(method="none")
        assert cal.apply(-1.0) == (None, None)


class TestCceAndDepletion:
    def test_cce_positive_for_negative_charges(self):
        cce = compute_cce(np.array([-1.0, -2.0, -4.0]), reference_charge_pC=-4.0)
        assert np.allclose(cce, [0.25, 0.5, 1.0])

    def test_depletion_voltage_negative_bias_negative_charge(self):
        """Typical p-in-n sensor: negative bias, negative raw charge."""
        v = -np.arange(0.0, 301.0, 20.0)
        q = -np.minimum(np.abs(v) / 150.0, 1.0) * 4.0   # saturates at |150 V|
        vdep = estimate_depletion_voltage(v, q)
        assert vdep is not None
        assert 130.0 <= vdep <= 160.0

    def test_depletion_voltage_unsorted_input(self):
        v = np.array([-300.0, -50.0, -200.0, -100.0, -250.0, -150.0, 0.0])
        q = -np.minimum(np.abs(v) / 150.0, 1.0) * 4.0
        vdep = estimate_depletion_voltage(v, q)
        assert vdep is not None
        assert 130.0 <= vdep <= 160.0

    def test_depletion_voltage_all_nan_returns_none(self):
        assert estimate_depletion_voltage(
            np.array([0.0, -100.0]), np.array([np.nan, np.nan])) is None
