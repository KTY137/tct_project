"""Tests for the slow-control WARN/ALARM excursion policy (Item 2,
DECISIONS 2026-07-12).

Policy under test (enforced in ScanController's slow-control snapshot path,
shared by the classic scan loop and the plan executor):

  * WARN (or UNAVAILABLE/stale) -> SAFE-HOLD PAUSE: motion stopped, HV HELD at
    setpoint, run -> PAUSED, operator prompt via the manual-pause seam carrying
    channel + value + threshold; operator Resumes or Aborts.
  * ALARM -> FULL FAIL-SAFE ABORT: HV ramped to 0 V, motion stopped, writer
    flushed; on_error carries channel + value + threshold.
  * Once per excursion: a per-channel latch suppresses a re-pause storm on an
    ongoing WARN after the operator acks, until the channel reads OK again.

Plus config_validator coverage of the per-channel thresholds.

Everything runs on fully-simulated backends; the excursion values are made
deterministic (noise=0, drift=0, nominal placed in the WARN/ALARM band) or
monkeypatched, never left to the drifting simulator.
"""
from __future__ import annotations

import time
import unittest.mock as mock

import pytest
import yaml

from controller.config_validator import validate_config, errors, warnings
from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import AutoConfirmGate
from devices.slow_control_base import AlarmStatus, SlowControlReading


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _acq(**p):
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params=p)


def _save():
    return ActionBlock(action=ActionType.SAVE_POINT, params={})


def _stage_plan(values):
    loop = LoopBlock(axis=Axis.STAGE_X, values=[float(v) for v in values],
                     children=[_acq(), _save()])
    return ScanPlan(name="stage", root=[loop])


def _limits(**over) -> PlanLimits:
    d = dict(x_min_mm=-50.0, x_max_mm=50.0, y_min_mm=-50.0, y_max_mm=50.0,
             z_min_mm=-10.0, z_max_mm=10.0, voltage_range_V=1000.0,
             max_points=1_000_000)
    d.update(over)
    return PlanLimits(**d)


def _flat_channel(name="temperature_C", unit="C", nominal=25.0, **thresholds):
    """A simulated channel with NO noise/drift, so value == nominal exactly."""
    ch = {"name": name, "unit": unit, "backend": "simulated",
          "nominal": nominal, "noise": 0.0, "drift_amplitude": 0.0,
          "drift_period_s": 60.0}
    ch.update(thresholds)
    return ch


@pytest.fixture
def make_ctrl(tmp_path):
    created: list = []

    def _factory(sc_channels):
        cfg = {
            "oscilloscope":       {"backend": "visa", "simulation": True},
            "motor_stage":        {"backend": "simulated"},
            "intensity_monitor":  {"backend": "simulated"},
            "camera":             {"simulation": True},
            "waveform_generator": {"simulation": True},
            "bias_supply":        {"backend": "simulated"},
            "output":             {"data_dir": str(tmp_path / "runs")},
            "slow_control":       {"channels": sc_channels},
        }
        path = tmp_path / "devices.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        dm = DeviceManager(config_path=str(path))
        assert dm.config_errors() == [], dm.config_errors()
        assert all(v == "ok" for v in dm.connect_all().values())
        dm.motor.home()                  # real homing (sim: instant, at origin)
        sm = StateMachine()
        for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
            sm.transition(st)
        ctrl = ScanController(dm, sm)
        created.append(dm)
        return dm, ctrl, sm

    yield _factory
    for dm in created:
        dm.disconnect_all()


def _wait_state(sm, state, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline and sm.state is not state:
        time.sleep(0.01)
    return sm.state is state


# --------------------------------------------------------------------------- #
# (a) WARN -> safe-hold pause with prompt; resume finishes; no re-pause storm  #
# --------------------------------------------------------------------------- #
def test_warn_pauses_with_prompt_then_resume_finishes(make_ctrl):
    dm, ctrl, sm = make_ctrl([
        _flat_channel("temperature_C", "C", nominal=31.0,
                      warn_high=30.0, alarm_high=35.0),
    ])
    prompts: list = []
    ctrl.on_manual_pause = lambda p: prompts.append(p)

    # 3 acquire points -> the first sample WARNs and safe-holds.
    ctrl.start_plan(_stage_plan([0.0, 1.0, 2.0]), _limits(), AutoConfirmGate())

    assert _wait_state(sm, AppState.PAUSED), "policy should safe-hold on WARN"
    assert len(prompts) == 1
    reason = prompts[0]
    assert "temperature_C" in reason
    assert "31" in reason and "30" in reason          # value + crossed threshold
    assert "warn" in reason.lower()
    assert "held" in reason.lower()                    # HV held / motion stopped

    ctrl.resume()
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    assert ctrl._writer._n_points == 3                 # all points eventually saved
    # Ongoing WARN after ack must NOT re-pause every subsequent snapshot.
    assert len(prompts) == 1


def test_no_repause_storm_and_rearm_after_ok(make_ctrl):
    """Direct policy calls: a persisting WARN pauses once (latched); it re-arms
    only after the channel returns to OK, then a fresh WARN pauses again."""
    dm, ctrl, sm = make_ctrl([
        _flat_channel("temperature_C", "C", nominal=25.0,
                      warn_high=30.0, alarm_high=35.0),
    ])
    prompts: list = []
    ctrl.on_manual_pause = lambda p: prompts.append(p)
    sm.transition(AppState.RUNNING)   # simulate an in-flight run

    def reading(status, value):
        return {"temperature_C": SlowControlReading(
            name="temperature_C", value=value, unit="C",
            timestamp=time.time(), status=status)}

    bias = dm.bias_supply
    # 1) first WARN -> pause + prompt, latch the channel.
    ctrl._apply_slow_control_policy(reading(AlarmStatus.WARN_HIGH, 31.0), bias)
    assert sm.state is AppState.PAUSED and len(prompts) == 1

    # 2) operator acks (resume); WARN persists -> latched -> NO new prompt.
    sm.transition(AppState.RUNNING)
    ctrl._apply_slow_control_policy(reading(AlarmStatus.WARN_HIGH, 31.0), bias)
    assert sm.state is AppState.RUNNING and len(prompts) == 1

    # 3) channel returns to OK -> latch cleared (excursion resolved).
    ctrl._apply_slow_control_policy(reading(AlarmStatus.OK, 25.0), bias)
    assert "temperature_C" not in ctrl._sc_latched

    # 4) a fresh WARN excursion pauses again.
    ctrl._apply_slow_control_policy(reading(AlarmStatus.WARN_HIGH, 31.0), bias)
    assert sm.state is AppState.PAUSED and len(prompts) == 2


# --------------------------------------------------------------------------- #
# (b) UNAVAILABLE / stale -> safe-hold pause                                   #
# --------------------------------------------------------------------------- #
def test_unavailable_sensor_pauses(make_ctrl):
    dm, ctrl, sm = make_ctrl([
        _flat_channel("humidity_pct", "%RH", nominal=45.0, warn_high=70.0),
    ])
    prompts: list = []
    ctrl.on_manual_pause = lambda p: prompts.append(p)
    # Make the sensor read fail -> read_with_status returns UNAVAILABLE.
    dm.slow_control.channels[0].read = mock.Mock(side_effect=RuntimeError("no sensor"))

    ctrl.start_plan(_stage_plan([0.0, 1.0]), _limits(), AutoConfirmGate())

    assert _wait_state(sm, AppState.PAUSED)
    assert len(prompts) == 1
    assert "humidity_pct" in prompts[0] and "unavailable" in prompts[0].lower()

    ctrl.resume()
    ctrl._thread.join(timeout=20)
    assert sm.state is AppState.FINISHED
    assert len(prompts) == 1                            # latched, no storm


# --------------------------------------------------------------------------- #
# (c) ALARM -> fail-safe abort, preserving data already taken                  #
# --------------------------------------------------------------------------- #
def test_alarm_aborts_failsafe_preserving_prior_point(make_ctrl):
    dm, ctrl, sm = make_ctrl([
        _flat_channel("temperature_C", "C", nominal=25.0,
                      warn_high=30.0, alarm_high=35.0),
    ])
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)

    # First slow-control read OK, subsequent reads ALARM -> the first point is
    # saved, the second acquire trips the alarm.
    calls = {"n": 0}
    sc = dm.slow_control.channels[0]

    def escalating():
        calls["n"] += 1
        return 25.0 if calls["n"] == 1 else 40.0       # 40 >= alarm_high 35
    sc.read = escalating

    ctrl.start_plan(_stage_plan([0.0, 1.0, 2.0]), _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.ABORTED
    assert ctrl._writer._n_points == 1                 # prior point preserved
    assert ch.setpoint_V == 0.0                        # HV ramped down
    assert not ch.driver.output_is_on_ch(ch.channel)   # output opened
    assert any(c.args and c.args[0] == 0.0 for c in ch.ramp_to.call_args_list)
    assert errs, "alarm should surface via on_error"
    reason = errs[-1]
    assert "temperature_C" in reason
    assert "40" in reason and "35" in reason
    assert "alarm" in reason.lower()


# --------------------------------------------------------------------------- #
# (d) config_validator coverage of per-channel thresholds                     #
# --------------------------------------------------------------------------- #
def _sc_cfg(channel):
    return {"slow_control": {"channels": [channel]}}


def test_valid_thresholds_are_clean():
    cfg = _sc_cfg(_flat_channel("t", "C", nominal=22.0,
                                alarm_low=-40.0, warn_low=-20.0,
                                warn_high=30.0, alarm_high=35.0))
    issues = validate_config(cfg)
    assert errors(issues) == []
    assert not any(w.startswith("[slow_control]") for w in warnings(issues))


def test_inverted_warn_band_errors():
    cfg = _sc_cfg(_flat_channel("t", "C", warn_low=30.0, warn_high=10.0))
    errs = errors(validate_config(cfg))
    assert any("warn_low" in e and "warn_high" in e for e in errs)


def test_alarm_high_below_warn_high_errors():
    cfg = _sc_cfg(_flat_channel("t", "C", warn_high=30.0, alarm_high=25.0))
    errs = errors(validate_config(cfg))
    assert any("alarm_high" in e and "warn_high" in e for e in errs)


def test_alarm_low_above_warn_low_errors():
    cfg = _sc_cfg(_flat_channel("t", "C", warn_low=-20.0, alarm_low=-10.0))
    errs = errors(validate_config(cfg))
    assert any("alarm_low" in e and "warn_low" in e for e in errs)


def test_non_numeric_threshold_errors():
    cfg = _sc_cfg(_flat_channel("t", "C", warn_high="hot"))
    errs = errors(validate_config(cfg))
    assert any("warn_high" in e and "number" in e for e in errs)


def test_unknown_channel_key_warns():
    cfg = _sc_cfg(_flat_channel("t", "C", warn_hi=30.0))   # typo'd threshold key
    ws = warnings(validate_config(cfg))
    assert any("warn_hi" in w and "slow_control" in w for w in ws)
    assert errors(validate_config(cfg)) == []             # typos never block
