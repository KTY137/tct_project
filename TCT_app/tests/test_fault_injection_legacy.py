"""Phase-3 robustness: fault-injection tests for the LEGACY scan paths.

Covers the classic XY raster (``start`` / ``_run``) and the bias voltage sweep
(``start_voltage_scan`` / ``_run_voltage_scan``).  The plan executor is covered
in ``test_fault_injection.py``.

Each test injects a hardware fault into a fully-simulated backend and asserts
the fail-safe contract: the worker thread EXITS, the state machine reaches a
terminal state, the laser trigger is turned off, the writer is closed with no
dangling handle, and data taken before the fault is preserved.  Everything is
headless and simulated — no VISA / serial / Qt / hardware I/O.

Two behaviours worth calling out (asserted here as the code's *current*
contract, not as endorsements):

  * ``_run`` (XY raster) does NOT drive HV, so its ``finally`` does not run a
    bias failsafe.  On a bias-compliance TRIP the failsafe still fires, because
    ``_check_compliance`` ramps down itself before the loop breaks.
  * ``_run_voltage_scan`` ramps to 0 + opens the output on a compliance trip
    (HV IS left safe) but transitions to FINISHED, not ABORTED, because the trip
    ``break``s without setting the abort event.  See the note on that test.
"""
from __future__ import annotations

import unittest.mock as mock

import h5py
import pytest
import yaml

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController, ScanConfig, VoltageScanConfig
from devices.base import DeviceError
from devices.bias_supply_base import BiasReading


# --------------------------------------------------------------------------- #
# Fully-simulated setup (no hardware)                                          #
# --------------------------------------------------------------------------- #
def _sim_config_path(tmp_path):
    cfg = {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "simulated"},
        "camera":             {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":        {"backend": "simulated"},
        "output":             {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


@pytest.fixture
def sim(tmp_path):
    """Return a ready-to-scan ``(dm, ctrl, sm)`` on fully-simulated backends."""
    dm = DeviceManager(config_path=_sim_config_path(tmp_path))
    assert dm.config_errors() == []
    results = dm.connect_all()
    assert all(v == "ok" for v in results.values()), results

    dm.motor.zero_position()

    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
        sm.transition(st)

    ctrl = ScanController(dm, sm)
    try:
        yield dm, ctrl, sm
    finally:
        dm.disconnect_all()


def _grid(n_points, **over):
    """A tiny, delay-free XY ScanConfig with *n_points* along X (single Y row)."""
    cfg = dict(
        x_start_mm=0.0, x_stop_mm=0.1 * (n_points - 1), x_step_mm=0.1,
        y_start_mm=0.0, y_stop_mm=0.0, y_step_mm=0.1,
        z_mm=0.0, n_averages=1, settle_time_s=0.0,
    )
    cfg.update(over)
    return ScanConfig(**cfg)


def _fast_vscan(**over):
    """A delay-free IV sweep: 0 → -20 V in -10 V steps (3 setpoints)."""
    cfg = dict(v_start_V=0.0, v_stop_V=-20.0, v_step_V=-10.0,
               ramp_step_V=100.0, ramp_delay_s=0.0, hold_delay_s=0.0,
               n_averages=1)
    cfg.update(over)
    return VoltageScanConfig(**cfg)


# --------------------------------------------------------------------------- #
# Fault-injection + assertion helpers (mirror test_fault_injection.py)         #
# --------------------------------------------------------------------------- #
def raise_after(n_ok, exc, wraps=None):
    state = {"n": 0}

    def _f(*a, **k):
        state["n"] += 1
        if state["n"] > n_ok:
            raise exc
        return wraps(*a, **k) if wraps is not None else None

    _f.calls = state
    return _f


def join_or_fail(ctrl, timeout=20):
    ctrl._thread.join(timeout=timeout)
    assert not ctrl._thread.is_alive(), "worker thread did not exit after the fault"


def assert_writer_closed(ctrl):
    w = ctrl._writer
    assert w is not None, "no per-run writer was allocated"
    assert w._file is None, "HDF5 writer left a dangling open file handle"


def assert_writer_file_intact(ctrl):
    assert_writer_closed(ctrl)
    path = ctrl._writer.path
    assert path.exists(), "run file was never created"
    with h5py.File(path, "r") as f:
        assert "stop_time" in f.attrs, "writer did not flush/close cleanly"


# --------------------------------------------------------------------------- #
# 1. Mid-scan scope disconnect (XY raster)                                     #
# --------------------------------------------------------------------------- #
def test_scope_disconnect_mid_xy_scan(sim):
    """Scope read raises after the first point → ERROR, laser off, writer closed
    & intact, the first point preserved."""
    dm, ctrl, sm = sim
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    dm.scope.read_channel = raise_after(
        1, DeviceError("scope link lost"), wraps=dm.scope.read_channel)

    ctrl.start(_grid(3))
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert errs
    assert wf_off.called
    assert ctrl._writer._n_points == 1
    assert_writer_file_intact(ctrl)


# --------------------------------------------------------------------------- #
# 2. Bias compliance trip mid XY raster                                        #
# --------------------------------------------------------------------------- #
def test_xy_scan_compliance_trip_failsafe(sim):
    """A simulated compliance trip after the first point → ABORTED, bias ramped
    to 0 + output off (via _check_compliance), first point preserved."""
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    trip = {"armed": False}
    orig_read = ch.read

    def fake_read(*a, **k):
        if trip["armed"]:
            return BiasReading(voltage_V=-10.0, current_A=60e-6, compliant=True)
        return orig_read(*a, **k)

    ch.read = mock.Mock(side_effect=fake_read)
    ctrl.on_point_done = lambda r: trip.__setitem__("armed", True)

    ctrl.start(_grid(2))
    join_or_fail(ctrl)

    assert sm.state is AppState.ABORTED
    assert ctrl._writer._n_points == 1                 # first point kept
    assert any("compliance" in m.lower() for m in errs)
    assert ch.setpoint_V == 0.0                        # failsafed
    assert not ch.driver.output_is_on_ch(ch.channel)
    assert ch.output_off.called
    assert any(c.args and c.args[0] == 0.0 for c in ch.ramp_to.call_args_list)
    assert_writer_closed(ctrl)


# --------------------------------------------------------------------------- #
# 3. Bias read failures (not a trip) → 3-consecutive-failure DeviceError abort #
# --------------------------------------------------------------------------- #
def test_xy_scan_bias_read_failures_deviceerror(sim):
    """bias.read() raises on every compliance check → DeviceError after 3
    consecutive unreadable points, ERROR, the 2 tolerated points preserved.

    Note: the XY raster never energizes HV, so ``_run``'s finally runs no bias
    failsafe (and none is needed — nothing was driven)."""
    dm, ctrl, sm = sim
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    dm.bias_supply.read = raise_after(0, DeviceError("bias supply unreadable"))

    ctrl.start(_grid(3))
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert ctrl._writer._n_points == 2                 # 2 tolerated, 3rd aborts
    assert any("unreadable" in m.lower() for m in errs)
    assert wf_off.called
    assert_writer_file_intact(ctrl)


# --------------------------------------------------------------------------- #
# 4. Motor fault during a move (XY raster)                                     #
# --------------------------------------------------------------------------- #
def test_motor_fault_mid_xy_scan(sim):
    """move_to raises on the first point → ERROR, laser off, writer closed,
    nothing saved."""
    dm, ctrl, sm = sim
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    dm.motor.move_to = raise_after(0, DeviceError("motor comms fault"))

    ctrl.start(_grid(3))
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert errs
    assert wf_off.called
    assert ctrl._writer._n_points == 0
    assert_writer_closed(ctrl)


# --------------------------------------------------------------------------- #
# 5. Waveform-generator failure at acquire (XY raster)                         #
# --------------------------------------------------------------------------- #
def test_wavegen_output_on_fault_xy_scan(sim):
    """output_on() raises at the first acquire → ERROR without wedging the
    thread; output_off() still attempted in finally; writer closed."""
    dm, ctrl, sm = sim
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    dm.waveform_generator.output_on = raise_after(
        0, DeviceError("wavegen output enable failed"))

    ctrl.start(_grid(2))
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert errs
    assert wf_off.called
    assert ctrl._writer._n_points == 0
    assert_writer_closed(ctrl)


# --------------------------------------------------------------------------- #
# 6. Bias compliance trip mid voltage sweep (HV-driving legacy path)           #
# --------------------------------------------------------------------------- #
def test_voltage_scan_compliance_trip_failsafe(sim):
    """A compliance trip on the 2nd setpoint → the sweep breaks, ramps HV to 0
    and opens the output (HV left SAFE), and surfaces the trip via on_error.

    Contract quirk (asserted, not endorsed): the sweep transitions to FINISHED,
    not ABORTED, because the compliance break does not set the abort event.
    HV is nonetheless failsafed — the safety-critical facts below are what
    matter; the terminal LABEL is a state-semantics observation flagged for
    review.
    """
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    calls = {"n": 0}
    orig_read = ch.read

    def fake_read(*a, **k):
        calls["n"] += 1
        if calls["n"] >= 2:                            # trip from the 2nd read on
            return BiasReading(voltage_V=-10.0, current_A=60e-6, compliant=True)
        return orig_read(*a, **k)

    ch.read = mock.Mock(side_effect=fake_read)

    ctrl.start_voltage_scan(_fast_vscan())
    join_or_fail(ctrl)

    # HV is left safe on EVERY exit path — this is the safety contract.
    assert ch.setpoint_V == 0.0
    assert not ch.driver.output_is_on_ch(ch.channel)
    assert ch.output_off.called
    assert any(c.args and c.args[0] == 0.0 for c in ch.ramp_to.call_args_list)
    assert any("compliance" in m.lower() for m in errs)
    assert ctrl._writer._voltage_n == 1               # only the pre-trip point
    assert_writer_file_intact(ctrl)
    # Current contract: FINISHED (trip breaks without setting the abort event).
    assert sm.state is AppState.FINISHED
