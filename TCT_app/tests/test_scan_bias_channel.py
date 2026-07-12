"""Scan targeting of a specific bias-supply channel.

The bias supply is now multi-channel: ``DeviceManager.bias_supply`` is the
primary :class:`BiasChannel` proxy (unchanged behavior) and
``DeviceManager.bias_channels`` is one proxy per HV channel.  A scan config may
carry an optional ``bias_channel`` index; the :class:`ScanController` resolves
it once per run:

  * ``None``  -> the primary proxy (historic single-channel path, unchanged),
  * an int    -> ``bias_channels[idx]`` (validated against the channel count),
  * out of range / wrong type -> raises and refuses to start (never a silent
    fall-back — this drives HV).

Every test is hardware-safe: it builds a fully *simulated* DeviceManager and a
2-channel :class:`SimulatedBiasSupply`; no VISA/serial/hardware I/O occurs.
"""
from __future__ import annotations

import unittest.mock as mock

import pytest
import yaml

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController, ScanConfig, VoltageScanConfig
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.bias_channel import BiasChannel


# --------------------------------------------------------------------------- #
# Fully-simulated 2-channel setup (no hardware)                                #
# --------------------------------------------------------------------------- #
def _sim_config_path(tmp_path):
    cfg = {
        "oscilloscope":      {"backend": "visa", "simulation": True},
        "motor_stage":       {"backend": "simulated"},
        "intensity_monitor": {"backend": "simulated"},
        "camera":            {"simulation": True},
        "waveform_generator":{"simulation": True},
        "bias_supply":       {"backend": "simulated"},
        "output":            {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


@pytest.fixture
def sim(tmp_path):
    """Return a ready-to-scan (dm, ctrl, sm) with a 2-channel simulated bias.

    All backends are simulated; the motor is marked homed without moving and
    the state machine is driven up to READY so a scan may start.
    """
    dm = DeviceManager(config_path=_sim_config_path(tmp_path))
    assert dm.config_errors() == []

    # Swap in a 2-channel simulated bias driver (mirrors test_bias_multichannel).
    drv = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0)
    dm._bias_driver = drv
    dm._bias_primary_ch = 0
    dm.bias_supply = BiasChannel(drv, 0)

    results = dm.connect_all()          # sim connects everything + enumerates channels
    assert all(v == "ok" for v in results.values()), results
    assert len(dm.bias_channels) == 2
    assert dm.bias_channels[0] is dm.bias_supply

    dm.motor.home()                     # real homing (sim: instant, at origin)

    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
        sm.transition(st)

    ctrl = ScanController(dm, sm)
    try:
        yield dm, ctrl, sm
    finally:
        dm.disconnect_all()


def _spy_channels(dm):
    """Wrap ramp_to/read/output_on/output_off on both channels with call spies."""
    for ch in dm.bias_channels:
        ch.ramp_to    = mock.Mock(wraps=ch.ramp_to)
        ch.read       = mock.Mock(wraps=ch.read)
        ch.output_on  = mock.Mock(wraps=ch.output_on)
        ch.output_off = mock.Mock(wraps=ch.output_off)
    return dm.bias_channels[0], dm.bias_channels[1]


def _fast_vscan(**kw):
    """A tiny, delay-free voltage scan config (0 -> -20 V in -10 V steps)."""
    base = dict(v_start_V=0.0, v_stop_V=-20.0, v_step_V=-10.0,
                ramp_step_V=100.0, ramp_delay_s=0.0, hold_delay_s=0.0,
                n_averages=1)
    base.update(kw)
    return VoltageScanConfig(**base)


# --------------------------------------------------------------------------- #
# _resolve_bias — the channel-selection logic                                  #
# --------------------------------------------------------------------------- #
class TestResolveBias:
    def test_none_resolves_to_primary_object(self, sim):
        dm, ctrl, _ = sim
        # Identity — the default path returns the exact historic object.
        assert ctrl._resolve_bias(VoltageScanConfig()) is dm.bias_supply
        assert ctrl._resolve_bias(VoltageScanConfig(bias_channel=None)) is dm.bias_supply
        assert ctrl._resolve_bias(ScanConfig()) is dm.bias_supply
        assert ctrl._resolve_bias(ScanConfig(bias_channel=None)) is dm.bias_supply

    def test_primary_index_resolves_to_primary_proxy(self, sim):
        dm, ctrl, _ = sim
        # Channel 0 is the primary proxy object itself.
        assert ctrl._resolve_bias(VoltageScanConfig(bias_channel=0)) is dm.bias_supply

    def test_explicit_index_resolves_to_that_channel(self, sim):
        dm, ctrl, _ = sim
        assert ctrl._resolve_bias(VoltageScanConfig(bias_channel=1)) is dm.bias_channels[1]
        assert ctrl._resolve_bias(ScanConfig(bias_channel=1)) is dm.bias_channels[1]

    @pytest.mark.parametrize("bad", [2, 5, -1, True, 1.0])
    def test_out_of_range_or_wrong_type_raises(self, sim, bad):
        _, ctrl, _ = sim
        with pytest.raises(ValueError, match="bias_channel"):
            ctrl._resolve_bias(VoltageScanConfig(bias_channel=bad))


# --------------------------------------------------------------------------- #
# Voltage scan routes ramp/read to the resolved channel                        #
# --------------------------------------------------------------------------- #
class TestVoltageScanChannelRouting:
    def test_default_uses_primary_channel(self, sim):
        dm, ctrl, sm = sim
        ch0, ch1 = _spy_channels(dm)

        ctrl.start_voltage_scan(_fast_vscan(bias_channel=None))
        ctrl._thread.join(timeout=10)

        assert not ctrl._thread.is_alive()
        assert sm.state is AppState.FINISHED
        # Primary (ch0) is driven; the second channel is never touched.
        assert ch0.ramp_to.called and ch0.read.called
        assert not ch1.ramp_to.called and not ch1.read.called

    def test_selected_channel_is_ramped_and_read(self, sim):
        dm, ctrl, sm = sim
        ch0, ch1 = _spy_channels(dm)

        recorded: list[tuple[float, float, float]] = []
        ctrl.on_vscan_point = lambda v, q, i: recorded.append((v, q, i))

        ctrl.start_voltage_scan(_fast_vscan(bias_channel=1))
        ctrl._thread.join(timeout=10)

        assert not ctrl._thread.is_alive()
        assert sm.state is AppState.FINISHED
        # Only channel 1 is ramped/read; the primary channel stays untouched.
        assert ch1.ramp_to.called and ch1.read.called
        assert not ch0.ramp_to.called and not ch0.read.called
        # Points were recorded (3 setpoints: 0, -10, -20 V).
        assert len(recorded) == 3
        # The channel was ramped back to 0 V at the end (fail-safe unchanged).
        assert dm.bias_channels[1].setpoint_V == 0.0


# --------------------------------------------------------------------------- #
# Out-of-range refuses to start BEFORE any hardware action                     #
# --------------------------------------------------------------------------- #
class TestRefuseToStart:
    def test_out_of_range_raises_and_touches_no_hardware(self, sim):
        dm, ctrl, sm = sim
        ch0, ch1 = _spy_channels(dm)

        with pytest.raises(ValueError, match="out of range"):
            ctrl.start_voltage_scan(_fast_vscan(bias_channel=5))

        # State machine never transitioned and no scan thread was launched.
        assert sm.state is AppState.READY
        assert ctrl._thread is None
        # No channel was ever commanded (no ramp/read/output toggling).
        for ch in (ch0, ch1):
            assert not ch.ramp_to.called
            assert not ch.read.called
            assert not ch.output_on.called
            assert not ch.output_off.called

    def test_xy_scan_out_of_range_raises_and_does_not_start(self, sim):
        _, ctrl, sm = sim
        with pytest.raises(ValueError, match="out of range"):
            ctrl.start(ScanConfig(bias_channel=9))
        assert sm.state is AppState.READY
        assert ctrl._thread is None


# --------------------------------------------------------------------------- #
# current_scan_type — read-only run-state accessor for the GUI facade          #
# --------------------------------------------------------------------------- #
class TestCurrentScanType:
    def test_none_before_any_run(self, sim):
        _, ctrl, _ = sim
        assert ctrl.current_scan_type is None

    def test_set_during_run_and_cleared_after(self, sim):
        _, ctrl, sm = sim

        # Sample the accessor from inside the running scan (the callback fires
        # on the worker thread, after _begin_run has published the type).
        seen: list[str | None] = []
        ctrl.on_vscan_point = lambda v, q, i: seen.append(ctrl.current_scan_type)

        ctrl.start_voltage_scan(_fast_vscan())
        ctrl._thread.join(timeout=10)

        assert not ctrl._thread.is_alive()
        assert sm.state is AppState.FINISHED
        # It read the canonical scan-type string while the run was in flight...
        assert seen and all(t == "voltage_scan" for t in seen)
        # ...and reverted to None (idle) once the run finished.
        assert ctrl.current_scan_type is None
