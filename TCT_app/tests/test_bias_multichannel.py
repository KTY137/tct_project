"""Multi-channel bias-supply proxy, the real iseg polarity gate, and
backward-compatibility of the zero-arg (primary-channel) wrappers.

Every test is hardware-safe:
  * SimulatedBiasSupply exercises real per-channel state headlessly.
  * The real IsegBiasSupply gate is exercised with a sentinel ``_inst`` and a
    monkeypatched ``_query`` / ``_write`` — no VISA session is ever opened and
    no SCPI ever reaches a real instrument.
"""
import pytest
import yaml

from devices.base import DeviceError
from devices.bias_channel import BiasChannel
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.bias_supply_iseg import IsegBiasSupply
from controller.device_manager import DeviceManager


# --------------------------------------------------------------------------- #
# (a) Multi-channel isolation through the BiasChannel proxy                    #
# --------------------------------------------------------------------------- #
class TestMultiChannelProxy:
    def _driver(self, **kw):
        d = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0, **kw)
        d.connect()
        return d

    def test_setpoints_are_isolated_per_channel(self):
        drv = self._driver()
        ch0, ch1 = BiasChannel(drv, 0), BiasChannel(drv, 1)

        ch0.enable_output()
        ch0.set_voltage(-100.0)
        ch1.enable_output()
        ch1.set_voltage(200.0)

        assert ch0.setpoint_V == -100.0
        assert ch1.setpoint_V == 200.0
        assert ch0.read().voltage_V == -100.0
        assert ch1.read().voltage_V == 200.0

    def test_compliance_is_isolated_per_channel(self):
        drv = self._driver()
        ch0, ch1 = BiasChannel(drv, 0), BiasChannel(drv, 1)
        ch0.set_compliance(10e-6)
        ch1.set_compliance(50e-6)
        assert ch0.compliance_A == 10e-6
        assert ch1.compliance_A == 50e-6

    def test_polarity_is_isolated_per_channel(self):
        drv = self._driver(polarity="n")
        ch0, ch1 = BiasChannel(drv, 0), BiasChannel(drv, 1)
        # Both fresh: OFF and discharged -> switching CH0 is legal.
        ch0.set_polarity("p")
        assert ch0.get_polarity() == "p"
        assert ch1.get_polarity() == "n"      # unaffected

    def test_proxy_ramp_uses_channel_state(self):
        drv = self._driver()
        ch1 = BiasChannel(drv, 1)
        ch1.ramp_to(-300.0, step_V=100.0, delay_s=0.0)
        assert ch1.setpoint_V == -300.0
        # The primary channel (0) is untouched by ramping channel 1.
        assert drv.setpoint_V_ch(0) == 0.0

    def test_proxy_gate_survives_delegation(self):
        # The safety gate lives in the driver; the proxy must not bypass it.
        drv = self._driver(polarity="n")
        ch0 = BiasChannel(drv, 0)
        ch0.enable_output()
        ch0.set_voltage(-500.0)
        with pytest.raises(DeviceError, match="output is ON"):
            ch0.set_polarity("p")
        assert ch0.get_polarity() == "n"

    def test_passthrough_attributes(self):
        drv = self._driver()
        ch1 = BiasChannel(drv, 1)
        assert ch1.connected is True
        assert ch1.simulation is True
        assert ch1.voltage_range_V == 1000.0
        assert ch1.channel_count() == 1
        assert ch1.supports_polarity_switch() is True


# --------------------------------------------------------------------------- #
# DeviceManager exposes bias_channels + a stable primary bias_supply           #
# --------------------------------------------------------------------------- #
class TestDeviceManagerEnumeration:
    def test_defaults_to_single_channel_before_connect(self):
        dm = DeviceManager()
        assert isinstance(dm.bias_supply, BiasChannel)
        assert dm.bias_channels == [dm.bias_supply]

    def test_refresh_builds_one_proxy_per_channel(self):
        dm = DeviceManager()
        # Swap in a 3-channel simulated driver (no hardware, no I/O).
        drv = SimulatedBiasSupply(channel_count=3, voltage_range_V=1000.0)
        dm._bias_driver = drv
        dm._bias_primary_ch = 0
        dm.bias_supply = BiasChannel(drv, 0)
        drv.connect()

        chans = dm.refresh_bias_channels()
        assert len(chans) == 3
        assert [c.channel for c in chans] == [0, 1, 2]
        # Primary proxy object is reused and remains self.bias_supply.
        assert dm.bias_channels[0] is dm.bias_supply

    def test_refresh_falls_back_to_one_on_single_channel_driver(self):
        dm = DeviceManager()
        # Inject a simulated single-channel driver (never touch the real backend
        # the repo config may point at).
        drv = SimulatedBiasSupply(channel_count=1)
        dm._bias_driver = drv
        dm._bias_primary_ch = 0
        dm.bias_supply = BiasChannel(drv, 0)
        drv.connect()
        chans = dm.refresh_bias_channels()
        assert len(chans) == 1
        assert chans[0] is dm.bias_supply

    def test_channel_count_comes_from_the_config_not_only_injection(self, tmp_path):
        """``bias_supply.sim_channel_count`` is what makes the multi-channel path
        reachable in simulation — the mode the app normally runs in.  The tests
        above inject a driver; an OPERATOR only has devices.yaml, so pin that."""
        cfg = {
            "oscilloscope":      {"backend": "visa", "simulation": True},
            "motor_stage":       {"backend": "simulated"},
            "intensity_monitor": {"backend": "simulated"},
            "camera":            {"simulation": True},
            "waveform_generator": {"simulation": True},
            "bias_supply":       {"backend": "simulated", "sim_channel_count": 2},
            "output":            {"data_dir": str(tmp_path / "runs")},
        }
        path = tmp_path / "devices.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

        dm = DeviceManager(config_path=str(path))
        assert dm.config_errors() == []
        assert dm._bias_driver.channel_count() == 2
        # Constructor does NO I/O and does not enumerate: still just the primary.
        assert dm.bias_channels == [dm.bias_supply]

        dm._bias_driver.connect()
        try:
            assert [c.channel for c in dm.refresh_bias_channels()] == [0, 1]
        finally:
            dm._bias_driver.disconnect()


# --------------------------------------------------------------------------- #
# (b) The REAL iseg polarity gate (fake _inst + monkeypatched I/O)             #
# --------------------------------------------------------------------------- #
class _FakeIseg:
    """Builds a non-simulation IsegBiasSupply whose I/O is fully faked."""

    @staticmethod
    def make(volt="0.0V", status="0", pol_list="p,n", pol="n",
             status_raises=False):
        s = IsegBiasSupply(
            visa_address="TCPIP0::10.0.0.1::10001::SOCKET",
            voltage_range_V=2000.0,
        )
        s._connected = True
        s._inst = object()            # sentinel: not None, never touched
        writes: list[str] = []

        def fake_query(cmd: str) -> str:
            c = cmd.upper()
            if "POL:LIST" in c:
                return pol_list
            if "CHAN:STAT" in c:
                if status_raises:
                    raise DeviceError("simulated link failure")
                return status
            if "MEAS:VOLT" in c:
                return volt
            if "OUTP:POL?" in c:
                return pol
            return ""

        def fake_write(cmd: str) -> None:
            writes.append(cmd)

        s._query = fake_query          # type: ignore[assignment]
        s._write = fake_write          # type: ignore[assignment]
        s._writes = writes             # type: ignore[attr-defined]
        # Keep the confirm loop fast for the "never confirms" case.
        s._POL_CONFIRM_BUDGET_S = 0.02
        s._POL_POLL_INTERVAL_S = 0.005
        return s


class TestRealIsegPolarityGate:
    def test_refuses_when_output_is_on(self):
        # Status word bit 3 (Is On) set -> refuse even if the local flag is OFF.
        s = _FakeIseg.make(status=str(0x8))
        with pytest.raises(DeviceError, match="output is ON"):
            s.set_polarity("p")
        assert not s._writes                # relay was never commanded

    def test_refuses_when_not_discharged(self):
        s = _FakeIseg.make(status="0", volt="500.0V")     # 500 V >> 4 V (0.002*2000)
        with pytest.raises(DeviceError, match="discharge threshold"):
            s.set_polarity("p")
        assert not s._writes

    def test_refuses_when_status_query_returns_none(self):
        # Fail CLOSED: if the status word can't be read we must NOT throw the relay.
        s = _FakeIseg.make(status_raises=True)
        with pytest.raises(DeviceError, match="could not confirm the output is OFF"):
            s.set_polarity("p")
        assert not s._writes

    def test_raises_without_confirm_when_relay_never_moves(self):
        # OFF and discharged so the write is issued, but the readback never
        # reports the target -> raise (do NOT ramp) and leave output disabled.
        s = _FakeIseg.make(status="0", volt="0.0V", pol="n")   # confirm always 'n'
        with pytest.raises(DeviceError, match="was not"):
            s.set_polarity("p")
        # The switch was attempted exactly once...
        assert any("CONF:OUTP:POL P" in w.upper() for w in s._writes)
        # ...but the channel was never turned on as part of the failed switch.
        assert s._chs(s._ch)["output_on"] is False

    def test_confirmed_switch_returns_normally(self):
        s = _FakeIseg.make(status="0", volt="0.0V", pol="p")   # confirm reports 'p'
        s.set_polarity("p")            # must not raise
        assert any("CONF:OUTP:POL P" in w.upper() for w in s._writes)


# --------------------------------------------------------------------------- #
# (c) Backward-compatibility: zero-arg wrappers == primary channel            #
# --------------------------------------------------------------------------- #
class TestZeroArgWrappers:
    def test_iseg_zero_arg_matches_primary_channel_state(self):
        s = IsegBiasSupply(simulation=True, voltage_range_V=2000.0)
        s.connect()
        primary = s._ch

        s.set_compliance(50e-6)
        assert s.compliance_A == 50e-6
        assert s.compliance_A_ch(primary) == 50e-6

        s.enable_output()
        assert s._output_on is True
        s.set_voltage(-300.0)
        assert s.setpoint_V == -300.0
        assert s.setpoint_V_ch(primary) == -300.0

        # A channel-aware write to the primary is visible through the zero-arg view.
        s.set_voltage_ch(primary, -111.0)
        assert s.setpoint_V == -111.0

        s.output_off()
        assert s._output_on is False
        assert s.setpoint_V == 0.0

    def test_iseg_ramp_unchanged(self):
        s = IsegBiasSupply(simulation=True, voltage_range_V=1000.0)
        s.connect()
        s.ramp_to(-200.0, step_V=100.0, delay_s=0.0)
        assert s.setpoint_V == -200.0
        s.ramp_to(0.0, step_V=100.0, delay_s=0.0)
        assert s.setpoint_V == 0.0

    def test_simulated_zero_arg_matches_primary_channel(self):
        s = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0, polarity="n")
        s.connect()
        s.enable_output()
        s.set_voltage(-250.0)
        assert s.setpoint_V == -250.0
        assert s.setpoint_V_ch(0) == -250.0
        assert s.read().voltage_V == -250.0
        # Channel 1 untouched by the zero-arg (primary) calls.
        assert s.setpoint_V_ch(1) == 0.0
        assert s.get_polarity() == "n"
