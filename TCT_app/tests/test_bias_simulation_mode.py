"""End-to-end simulation-mode coverage for the HV bias supply.

Background (gap fixed 2026-07-11): the ``bias_supply`` section of
configs/devices.yaml shipped WITHOUT a ``simulation:`` key, so the Quick
Settings window rendered no toggle for it (every other device tab has one) and
a home rig had no advertised offline switch — even though the driver layer
already honours ``simulation`` (the iseg driver runs a no-I/O sim path and a
``SimulatedBiasSupply`` backend exists). This suite pins the whole chain:

  * ``config_validator`` accepts ``simulation`` for bias_supply (no typo warning),
  * ``DeviceManager`` connects the iseg backend with ``simulation: true`` doing
    NO hardware I/O, output OFF by default,
  * the ``simulated`` backend ramps its setpoint toward target and starts OFF,
  * SAFETY: enabling simulation does NOT bypass the danger-confirmation gate —
    an HV ramp in sim still routes through ``gate.confirm(...)`` exactly like a
    real supply (DenyAllGate aborts fail-safe; the gate sees an ``hv_ramp``).

Every test is hardware-safe: fully-simulated backends, no VISA/serial I/O, safe
to run with a real supply physically attached.
"""
from __future__ import annotations

import unittest.mock as mock

import pytest
import yaml

from controller.config_validator import validate_config, errors, warnings
from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import DenyAllGate
from devices.bias_supply_iseg import IsegBiasSupply
from devices.bias_supply_simulated import SimulatedBiasSupply


# --------------------------------------------------------------------------- #
# Config helpers                                                               #
# --------------------------------------------------------------------------- #
def _sim_config(tmp_path, bias_supply: dict) -> str:
    cfg = {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "simulated"},
        "camera":             {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":        bias_supply,
        "output":             {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def _limits(**over) -> PlanLimits:
    d = dict(
        x_min_mm=-50.0, x_max_mm=50.0,
        y_min_mm=-50.0, y_max_mm=50.0,
        z_min_mm=-10.0, z_max_mm=10.0,
        voltage_range_V=2000.0, max_points=1_000_000,
    )
    d.update(over)
    return PlanLimits(**d)


def _bias_plan(target, points=1):
    children: list = []
    for _ in range(points):
        children.append(ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={}))
        children.append(ActionBlock(action=ActionType.SAVE_POINT, params={}))
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)], children=children)
    return ScanPlan(name="bias", root=[loop],
                    safety={"require_hv_confirmation": True})


class _SpyGate:
    """Records every DangerAction and answers with a fixed allow/deny verdict."""

    def __init__(self, allow: bool) -> None:
        self._allow = allow
        self.actions: list = []

    def confirm(self, action) -> bool:
        self.actions.append(action)
        return self._allow


# --------------------------------------------------------------------------- #
# 1. Validator accepts the simulation key                                     #
# --------------------------------------------------------------------------- #
def test_validator_accepts_bias_simulation_key():
    cfg = {"bias_supply": {"backend": "iseg", "simulation": True,
                           "visa_address": "ASRL6::INSTR", "channel": 0,
                           "voltage_range_V": 2000, "compliance_A": 1e-4}}
    issues = validate_config(cfg)
    # No error, and crucially no "unknown key 'simulation'" typo warning.
    assert errors(issues) == []
    assert not any("simulation" in w for w in warnings(issues)), warnings(issues)


# --------------------------------------------------------------------------- #
# 2. iseg backend + simulation:true connects with NO hardware I/O             #
# --------------------------------------------------------------------------- #
def test_device_manager_iseg_simulation_connects_no_io(tmp_path):
    path = _sim_config(tmp_path, {
        "backend": "iseg", "simulation": True,
        "visa_address": "ASRL6::INSTR", "channel": 0,
        "voltage_range_V": 2000, "compliance_A": 4e-4,
    })
    dm = DeviceManager(config_path=path)
    assert dm.config_errors() == []
    # The real driver class is used, but in its internal no-I/O sim mode.
    assert isinstance(dm._bias_driver, IsegBiasSupply)
    assert dm._bias_driver.simulation is True

    results = dm.connect_all()
    try:
        assert all(v == "ok" for v in results.values()), results
        # A live VISA session is never opened in simulation.
        assert dm._bias_driver._inst is None
        # Output OFF by default — no auto-enable on connect (safety rule 1).
        ch = dm.bias_supply
        assert ch.driver.output_is_on_ch(ch.channel) is False
        assert ch.setpoint_V == 0.0
    finally:
        dm.disconnect_all()


# --------------------------------------------------------------------------- #
# 3. 'simulated' backend builds the SimulatedBiasSupply                        #
# --------------------------------------------------------------------------- #
def test_device_manager_simulated_backend(tmp_path):
    path = _sim_config(tmp_path, {"backend": "simulated"})
    dm = DeviceManager(config_path=path)
    assert dm.config_errors() == []
    assert isinstance(dm._bias_driver, SimulatedBiasSupply)


# --------------------------------------------------------------------------- #
# 4. Simulated backend ramps its setpoint toward target, starts OFF           #
# --------------------------------------------------------------------------- #
def test_sim_backend_output_off_by_default():
    sup = SimulatedBiasSupply(voltage_range_V=1000.0)
    sup.connect()
    try:
        assert sup.output_is_on_ch(0) is False
        assert sup.setpoint_V == 0.0
    finally:
        sup.disconnect()


def test_sim_backend_ramps_toward_setpoint():
    sup = SimulatedBiasSupply(voltage_range_V=1000.0)
    sup.connect()
    try:
        # Delay-free ramp so the test is instant; large step count exercises the
        # stepped ramp toward the target.
        sup.ramp_to(-100.0, step_V=25.0, delay_s=0.0)
        assert sup.setpoint_V == pytest.approx(-100.0)
        assert sup.output_is_on_ch(0) is True
        r = sup.read()
        assert r.voltage_V == pytest.approx(-100.0, abs=1.0)
        # Ramp back down and confirm the setpoint tracks the new target.
        sup.ramp_to(0.0, step_V=25.0, delay_s=0.0)
        assert sup.setpoint_V == pytest.approx(0.0)
    finally:
        sup.disconnect()


# --------------------------------------------------------------------------- #
# 5. SAFETY: sim mode does NOT bypass the HV confirmation gate                 #
# --------------------------------------------------------------------------- #
def _ready_iseg_sim(tmp_path):
    path = _sim_config(tmp_path, {
        "backend": "iseg", "simulation": True,
        "visa_address": "ASRL6::INSTR", "channel": 0,
        "voltage_range_V": 2000, "compliance_A": 4e-4,
    })
    dm = DeviceManager(config_path=path)
    assert dm.config_errors() == []
    assert all(v == "ok" for v in dm.connect_all().values())
    dm.motor.zero_position()
    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
        sm.transition(st)
    return dm, ScanController(dm, sm), sm


def test_hv_ramp_denied_in_sim_still_fails_safe(tmp_path):
    """The gate is consulted for the HV ramp even with a simulated supply; a
    denial aborts cleanly and leaves the output OFF at 0 V (no bypass)."""
    dm, ctrl, sm = _ready_iseg_sim(tmp_path)
    ch = dm.bias_supply
    ch.output_off = mock.Mock(wraps=ch.output_off)
    try:
        ctrl.arm_hv(True)
        ctrl.start_plan(_bias_plan(-300.0, points=2), _limits(), DenyAllGate())
        ctrl._thread.join(timeout=20)

        assert not ctrl._thread.is_alive()
        assert sm.state is AppState.ABORTED          # clean deny, not ERROR
        assert ch.setpoint_V == 0.0                  # never reached -300 V
        assert not ch.driver.output_is_on_ch(ch.channel)
        assert ch.output_off.called
        assert ctrl._writer._n_points == 0           # nothing acquired
        assert ctrl._hv_armed is False               # disarmed after the run
    finally:
        dm.disconnect_all()


def test_hv_ramp_gate_sees_hv_ramp_action_in_sim(tmp_path):
    """The DangerAction routed to the gate is a real ``hv_ramp`` carrying the
    target — proving the confirmation path is identical to the real supply."""
    dm, ctrl, sm = _ready_iseg_sim(tmp_path)
    gate = _SpyGate(allow=False)   # deny → no HV actually ramps, but gate is consulted
    try:
        ctrl.arm_hv(True)
        ctrl.start_plan(_bias_plan(-300.0), _limits(), gate)
        ctrl._thread.join(timeout=20)

        kinds = [a.kind for a in gate.actions]
        assert "hv_ramp" in kinds, kinds
        hv = next(a for a in gate.actions if a.kind == "hv_ramp")
        assert "-300" in hv.summary
        assert hv.detail.get("target_V") == pytest.approx(-300.0)
    finally:
        dm.disconnect_all()
