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
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import AutoConfirmGate
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.bias_channel import BiasChannel


# --------------------------------------------------------------------------- #
# Fully-simulated 2-channel setup (no hardware)                                #
# --------------------------------------------------------------------------- #
def _sim_config_path(tmp_path, bias_supply: dict | None = None):
    cfg = {
        "oscilloscope":      {"backend": "visa", "simulation": True},
        "motor_stage":       {"backend": "simulated"},
        "intensity_monitor": {"backend": "simulated"},
        "camera":            {"simulation": True},
        "waveform_generator":{"simulation": True},
        "bias_supply":       bias_supply or {"backend": "simulated"},
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


@pytest.fixture
def sim3(tmp_path):
    """Like ``sim``, but the 3 HV channels come from the CONFIG — no injection.

    ``bias_supply.sim_channel_count: 3`` is the simulation-only knob that makes
    the multi-channel path reachable with no hardware attached (before it, the
    manager always built a 1-channel ``SimulatedBiasSupply()``).  This fixture
    therefore exercises the whole chain the operator actually gets:
    devices.yaml → DeviceManager → BiasChannel views → ScanController.
    """
    path = _sim_config_path(tmp_path, {"backend": "simulated",
                                       "sim_channel_count": 3})
    dm = DeviceManager(config_path=path)
    assert dm.config_errors() == []

    results = dm.connect_all()
    assert all(v == "ok" for v in results.values()), results
    assert [c.channel for c in dm.bias_channels] == [0, 1, 2]
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


def _plan_limits(**over) -> PlanLimits:
    d = dict(
        x_min_mm=-50.0, x_max_mm=50.0,
        y_min_mm=-50.0, y_max_mm=50.0,
        z_min_mm=-10.0, z_max_mm=10.0,
        voltage_range_V=1000.0, max_points=1_000_000,
    )
    d.update(over)
    return PlanLimits(**d)


def _bias_plan_on_channel(target: float, channel: int | None) -> ScanPlan:
    """A one-setpoint HV plan whose ``safety['bias_channel']`` selects the channel."""
    children = [ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={}),
                ActionBlock(action=ActionType.SAVE_POINT, params={})]
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)], children=children)
    return ScanPlan(name="bias_ch", root=[loop],
                    safety={"require_hv_confirmation": True,
                            "bias_channel": channel})


def _spy_channels(dm):
    """Wrap ramp_to/read/enable_output/output_off on every channel with call spies."""
    for ch in dm.bias_channels:
        ch.ramp_to       = mock.Mock(wraps=ch.ramp_to)
        ch.read          = mock.Mock(wraps=ch.read)
        ch.enable_output = mock.Mock(wraps=ch.enable_output)
        ch.output_off    = mock.Mock(wraps=ch.output_off)
    return tuple(dm.bias_channels)


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
            assert not ch.enable_output.called
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


# --------------------------------------------------------------------------- #
# Config-driven multi-channel: bias_supply.sim_channel_count (simulation only)  #
#                                                                              #
# The channels here are NOT injected by the test — they come from devices.yaml, #
# which is the point: before this key the simulated supply always reported 1    #
# channel, so plan safety['bias_channel'] > 0 could not be reached in the mode  #
# the app normally runs in.                                                     #
# --------------------------------------------------------------------------- #
class TestConfiguredChannelCount:
    def test_third_channel_is_exposed_and_resolvable(self, sim3):
        dm, ctrl, _ = sim3
        assert len(dm.bias_channels) == 3
        assert ctrl._resolve_bias(VoltageScanConfig(bias_channel=2)) is dm.bias_channels[2]
        # ...and index 3 is still out of range (the count is a real bound).
        with pytest.raises(ValueError, match="out of range"):
            ctrl._resolve_bias(VoltageScanConfig(bias_channel=3))

    def test_plan_safety_bias_channel_runs_against_the_third_channel(self, sim3):
        dm, ctrl, sm = sim3
        ch0, ch1, ch2 = _spy_channels(dm)

        ctrl.arm_hv(True)
        ctrl.start_plan(_bias_plan_on_channel(-100.0, 2),
                        _plan_limits(), AutoConfirmGate())
        ctrl._thread.join(timeout=20)

        assert not ctrl._thread.is_alive()
        assert sm.state is AppState.FINISHED
        # ONLY channel 2 was driven; the other two were never touched.
        assert ch2.ramp_to.called and ch2.read.called
        for other in (ch0, ch1):
            assert not other.ramp_to.called
            assert not other.read.called
            assert not other.enable_output.called
        # The plan's HV target actually landed on channel 2...
        assert -100.0 in [c.args[0] for c in ch2.ramp_to.call_args_list if c.args]
        # ...and the run's fail-safe brought it back to 0 V + output OFF.
        assert ch2.setpoint_V == 0.0
        assert not dm._bias_driver.output_is_on_ch(2)
        assert ctrl._writer._n_points == 1

    def test_park_safe_covers_every_configured_channel(self, sim3):
        """SAFETY: the between-entries park must de-energize ALL exposed
        channels — a sequence may have armed any of them."""
        dm, ctrl, _ = sim3
        drv = dm._bias_driver
        for idx in (0, 1, 2):
            drv.set_voltage_ch(idx, -50.0 * (idx + 1))
            drv.output_on_ch(idx)
        assert all(drv.output_is_on_ch(i) for i in (0, 1, 2))

        ctrl.park_safe()

        for idx in (0, 1, 2):
            assert dm.bias_channels[idx].setpoint_V == 0.0
            assert not drv.output_is_on_ch(idx)

    def test_disconnect_all_leaves_every_channel_off(self, sim3):
        """Teardown through the PRIMARY proxy still parks every channel (the
        proxies share one driver, whose disconnect() ramps them all down)."""
        dm, _, _ = sim3
        drv = dm._bias_driver
        for idx in (0, 1, 2):
            drv.set_voltage_ch(idx, -200.0)
            drv.output_on_ch(idx)

        dm.disconnect_all()                 # fixture's finally re-runs it: idempotent

        for idx in (0, 1, 2):
            assert not drv.output_is_on_ch(idx)
            assert drv.setpoint_V_ch(idx) == 0.0
