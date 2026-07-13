"""Bias-supply polarity + multi-channel API (simulated backends only).

These never touch real hardware: the iseg driver is exercised in simulation
mode (safe defaults, no I/O) and the polarity safety logic is exercised
through SimulatedBiasSupply, which mirrors the real gating.
"""
import pytest

from devices.base import DeviceError
from devices.bias_supply_base import BiasSupplyBase, BiasReading, normalize_polarity
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.bias_supply_iseg import IsegBiasSupply


# --------------------------------------------------------------------------- #
# A minimal concrete subclass to probe the BiasSupplyBase defaults.           #
# --------------------------------------------------------------------------- #
class _MinimalSupply(BiasSupplyBase):
    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def set_voltage(self, voltage_V: float) -> None:
        self._setpoint_V = voltage_V

    def set_compliance(self, current_A: float) -> None:
        self._compliance_A = current_A

    def enable_output(self) -> None:
        self._output_on = True

    def output_off(self) -> None:
        self._output_on = False

    def read(self) -> BiasReading:
        return BiasReading(voltage_V=0.0, current_A=0.0, compliant=False)


class TestBaseDefaults:
    def test_supports_polarity_switch_default_false(self):
        assert _MinimalSupply().supports_polarity_switch() is False

    def test_get_polarity_default_none(self):
        assert _MinimalSupply().get_polarity() is None

    def test_channel_count_default_one(self):
        assert _MinimalSupply().channel_count() == 1

    def test_set_polarity_default_raises(self):
        s = _MinimalSupply()
        s.connect()
        with pytest.raises(DeviceError, match="not supported"):
            s.set_polarity("p")


class TestNormalizePolarity:
    @pytest.mark.parametrize(
        "raw,expected",
        [("p", "p"), ("P", "p"), ("positive", "p"), ("+", "p"),
         ("n", "n"), ("N", "n"), ("negative", "n"), ("-", "n")],
    )
    def test_accepts_known_forms(self, raw, expected):
        assert normalize_polarity(raw) == expected

    @pytest.mark.parametrize("raw", ["", "x", "pp", "0", "positiv3"])
    def test_rejects_garbage(self, raw):
        with pytest.raises(DeviceError, match="Invalid polarity"):
            normalize_polarity(raw)


class TestSimulatedPolarity:
    def _supply(self, **kw):
        s = SimulatedBiasSupply(**kw)
        s.connect()
        return s

    def test_default_supports_and_reports_polarity(self):
        s = self._supply(polarity="n")
        assert s.supports_polarity_switch() is True
        assert s.get_polarity() == "n"
        assert s.channel_count() == 1

    def test_channel_count_from_constructor(self):
        assert SimulatedBiasSupply(channel_count=4).channel_count() == 4

    def test_switch_allowed_when_off_and_discharged(self):
        # Fresh supply: output OFF, measured 0 V -> switch is legal.
        s = self._supply(polarity="n")
        s.set_polarity("p")
        assert s.get_polarity() == "p"

    def test_switch_refused_when_output_on(self):
        s = self._supply(polarity="n")
        s.enable_output()
        s.set_voltage(-100.0)
        with pytest.raises(DeviceError, match="output is ON"):
            s.set_polarity("p")
        assert s.get_polarity() == "n"     # unchanged

    def test_switch_refused_when_not_discharged(self):
        # Charge it up, then open the output relay: measured voltage persists,
        # so the discharge precondition must still block the switch.
        s = self._supply(polarity="n", voltage_range_V=1000.0)
        s.enable_output()
        s.set_voltage(-500.0)
        s.output_off()                     # output OFF but still charged
        assert not s._output_on
        with pytest.raises(DeviceError, match="discharge threshold"):
            s.set_polarity("p")
        assert s.get_polarity() == "n"     # unchanged

    def test_switch_allowed_after_ramp_down(self):
        s = self._supply(polarity="n", voltage_range_V=1000.0)
        s.enable_output()
        s.set_voltage(-500.0)
        s.set_voltage(0.0)                 # ramp/bleed down while ON -> discharged
        s.output_off()
        s.set_polarity("p")
        assert s.get_polarity() == "p"

    def test_not_reversible_supply_reports_and_refuses(self):
        s = self._supply(polarity_reversible=False, polarity="n")
        assert s.supports_polarity_switch() is False
        with pytest.raises(DeviceError, match="not supported"):
            s.set_polarity("p")


class TestIsegSimulationSafeDefaults:
    """iseg in simulation mode must expose safe defaults and never do I/O."""

    def _supply(self):
        s = IsegBiasSupply(simulation=True, voltage_range_V=2000.0)
        s.connect()
        return s

    def test_channel_count_defaults_to_one(self):
        assert self._supply().channel_count() == 1

    def test_supports_polarity_switch_false_in_sim(self):
        assert self._supply().supports_polarity_switch() is False

    def test_get_polarity_none_in_sim(self):
        assert self._supply().get_polarity() is None

    def test_set_polarity_refused_in_sim(self):
        s = self._supply()
        with pytest.raises(DeviceError, match="not supported"):
            s.set_polarity("p")
