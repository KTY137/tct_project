"""Phase-3 robustness: fault-injection tests for the PLAN executor.

Each test injects a hardware fault (via a fully-simulated backend or an
in-test monkeypatch of a sim device method), runs the ``start_plan`` /
``_run_plan`` worker to completion, and asserts the fail-safe contract holds:

  * the worker thread EXITS (a hung worker is itself a finding — every test
    joins with a timeout and fails if the thread is still alive),
  * the state machine ends in a terminal state (ERROR / ABORTED per the code's
    contract),
  * HV is left safe (ramped to 0 + output off) whenever the run drove bias,
  * the laser trigger (waveform generator) is turned off,
  * the HDF5 writer is closed with no dangling file handle, and data taken
    before the fault is preserved.

Everything is headless and simulated — no VISA / serial / Qt / hardware I/O.
The DeviceManager/StateMachine construction mirrors ``test_plan_executor.py``.

The legacy XY-scan and voltage-scan paths are covered in
``test_fault_injection_legacy.py``.
"""
from __future__ import annotations

import time
import threading
import unittest.mock as mock

import h5py
import pytest
import yaml

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import AutoConfirmGate
from devices.base import DeviceError
from devices.bias_supply_base import BiasReading


# --------------------------------------------------------------------------- #
# Fully-simulated setup (no hardware) — copied from test_plan_executor.py      #
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
    """Return a ready-to-run ``(dm, ctrl, sm)`` on fully-simulated backends."""
    dm = DeviceManager(config_path=_sim_config_path(tmp_path))
    assert dm.config_errors() == []
    results = dm.connect_all()
    assert all(v == "ok" for v in results.values()), results

    dm.motor.zero_position()            # homed without moving

    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
        sm.transition(st)

    ctrl = ScanController(dm, sm)
    try:
        yield dm, ctrl, sm
    finally:
        dm.disconnect_all()


def _limits(**over) -> PlanLimits:
    d = dict(
        x_min_mm=-50.0, x_max_mm=50.0,
        y_min_mm=-50.0, y_max_mm=50.0,
        z_min_mm=-10.0, z_max_mm=10.0,
        voltage_range_V=1000.0, max_points=1_000_000,
    )
    d.update(over)
    return PlanLimits(**d)


# --------------------------------------------------------------------------- #
# Plan builders                                                                #
# --------------------------------------------------------------------------- #
def _acq(**p):
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params=p)


def _save():
    return ActionBlock(action=ActionType.SAVE_POINT, params={})


def _wait(seconds):
    return ActionBlock(action=ActionType.WAIT, params={"seconds": seconds})


def _stage_plan(values):
    """An x-only stage raster: acquire + save at each x.  No bias."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[float(v) for v in values],
                     children=[_acq(), _save()])
    return ScanPlan(name="stage", root=[loop])


def _bias_plan(target, points=1):
    """Ramp bias to *target*, then *points* × (acquire + save) at that bias."""
    children = []
    for _ in range(points):
        children.extend([_acq(), _save()])
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)], children=children)
    return ScanPlan(name="bias", root=[loop],
                    safety={"require_hv_confirmation": True})


def _bias_stage_plan(target, xs):
    """Ramp bias, then raster x with acquire+save at each x (moves + bias)."""
    inner = LoopBlock(axis=Axis.STAGE_X, values=[float(x) for x in xs],
                      children=[_acq(), _save()])
    outer = LoopBlock(axis=Axis.BIAS_V, values=[float(target)], children=[inner])
    return ScanPlan(name="bias_stage", root=[outer],
                    safety={"require_hv_confirmation": True})


def _bias_wait_plan(target, seconds):
    """Ramp bias, then a long WAIT, then acquire+save (park in the wait)."""
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)],
                     children=[_wait(seconds), _acq(), _save()])
    return ScanPlan(name="bias_wait", root=[loop],
                    safety={"require_hv_confirmation": True})


def _stage_wait_plan(value, seconds):
    """Move to *value*, then a long WAIT, then acquire+save (no bias)."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[float(value)],
                     children=[_wait(seconds), _acq(), _save()])
    return ScanPlan(name="stage_wait", root=[loop])


# --------------------------------------------------------------------------- #
# Fault-injection + assertion helpers                                          #
# --------------------------------------------------------------------------- #
def raise_after(n_ok, exc, wraps=None):
    """Callable that succeeds *n_ok* times then raises *exc* on every later call.

    The first ``n_ok`` calls delegate to *wraps* (returning its value) when
    given, else return None.  ``.calls['n']`` records how many times it ran —
    used to assert "no further calls were attempted after the fault".
    """
    state = {"n": 0}

    def _f(*a, **k):
        state["n"] += 1
        if state["n"] > n_ok:
            raise exc
        return wraps(*a, **k) if wraps is not None else None

    _f.calls = state
    return _f


def join_or_fail(ctrl, timeout=20):
    """Join the worker thread; FAIL if it does not exit (a hung worker = bug)."""
    ctrl._thread.join(timeout=timeout)
    assert not ctrl._thread.is_alive(), "worker thread did not exit after the fault"


def assert_writer_closed(ctrl):
    """The per-run writer exists and holds no dangling open file handle."""
    w = ctrl._writer
    assert w is not None, "no per-run writer was allocated"
    assert w._file is None, "HDF5 writer left a dangling open file handle"


def assert_writer_file_intact(ctrl):
    """Stronger: the closed .h5 reopens cleanly and carries a stop_time.

    ``HDF5Writer.close()`` writes ``stop_time`` then flush+close, so its presence
    proves the file was flushed and closed rather than abandoned mid-write.
    """
    assert_writer_closed(ctrl)
    path = ctrl._writer.path
    assert path.exists(), "run file was never created"
    with h5py.File(path, "r") as f:
        assert "stop_time" in f.attrs, "writer did not flush/close cleanly"


# --------------------------------------------------------------------------- #
# 1. Mid-scan device disconnect — scope read starts raising                    #
# --------------------------------------------------------------------------- #
def test_scope_disconnect_midplan_stage(sim):
    """Scope goes dark mid-raster on a bias-free plan → clean ERROR, laser off,
    writer closed & intact, the point taken before the fault preserved."""
    dm, ctrl, sm = sim
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    # First DUT read succeeds (point 0), the second raises (disconnect).
    dm.scope.read_channel = raise_after(
        1, DeviceError("scope link lost"), wraps=dm.scope.read_channel)

    ctrl.start_plan(_stage_plan([0.0, 1.0, 2.0]), _limits(), AutoConfirmGate())
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert errs                                   # surfaced via on_error
    assert wf_off.called                          # laser trigger disabled
    assert ctrl._writer._n_points == 1            # point before fault preserved
    assert_writer_file_intact(ctrl)


def test_scope_disconnect_midplan_bias(sim):
    """Same fault while HV is energized → ERROR AND bias failsafe (ramp 0 + off)."""
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off

    dm.scope.read_channel = raise_after(
        1, DeviceError("scope link lost"), wraps=dm.scope.read_channel)

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_plan(-100.0, points=2), _limits(), AutoConfirmGate())
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert ctrl._writer._n_points == 1            # first point kept
    assert ch.setpoint_V == 0.0                   # HV ramped down
    assert not ch.driver.output_is_on_ch(ch.channel)   # output opened
    assert ch.output_off.called
    assert any(c.args and c.args[0] == 0.0 for c in ch.ramp_to.call_args_list)
    assert wf_off.called
    assert ctrl._hv_armed is False                # arm never sticky
    assert_writer_closed(ctrl)


# --------------------------------------------------------------------------- #
# 2. HV compliance trip mid-plan is already covered in test_plan_executor.py   #
#    (test_compliance_trip_mid_plan).  The LEGACY paths are covered in         #
#    test_fault_injection_legacy.py.  Not duplicated here.                     #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 3. Motor fault during a move                                                 #
# --------------------------------------------------------------------------- #
def test_motor_fault_midplan_bias_failsafe(sim):
    """move_to raises on the 2nd raster move → run stops, NO further moves are
    attempted, HV is failsafed, the error is surfaced, writer closed."""
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    # Move #1 (x=0) succeeds, move #2 (x=1) faults; x=2 must never be commanded.
    move_fn = raise_after(1, DeviceError("motor comms fault mid-move"),
                          wraps=dm.motor.move_to)
    dm.motor.move_to = move_fn

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_stage_plan(-50.0, [0.0, 1.0, 2.0]),
                    _limits(), AutoConfirmGate())
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert move_fn.calls["n"] == 2                # faulted on #2, no #3 attempted
    assert ctrl._writer._n_points == 1            # x=0 point preserved
    assert ch.setpoint_V == 0.0                   # HV failsafed
    assert not ch.driver.output_is_on_ch(ch.channel)
    assert ch.output_off.called
    assert errs
    assert_writer_closed(ctrl)


def test_motor_fault_midmove_halts_stage_plan(sim):
    """A real move is started, then the readiness wait faults mid-motion.

    Fail-safe contract (rule 5: 'stop motion'): the in-flight stage is halted.
    ``_run_plan``'s ``finally`` best-effort-calls ``motor.stop()`` on EVERY exit
    path (see ``_motor_stop_safe``), so a fault DURING a move no longer lets the
    sim stage keep driving toward 45 mm — HV/wavegen/writer are failsafed AND
    the motor is stopped.  (Formerly an xfail(strict) gap; closed in the M2.2
    review fix.)
    """
    dm, ctrl, sm = sim
    stop_spy = mock.Mock(wraps=dm.motor.stop)
    dm.motor.stop = stop_spy

    def boom(*a, **k):
        raise DeviceError("motor comms lost mid-move")

    dm.motor.wait_until_ready = boom      # move_to starts the real async move

    ctrl.start_plan(_stage_plan([45.0]), _limits(), AutoConfirmGate())
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    # The in-flight stage IS halted on the error path — the fail-safe fix.
    assert stop_spy.called


# --------------------------------------------------------------------------- #
# 4. Bias read failures (not a trip) → 3-consecutive-failure DeviceError abort #
# --------------------------------------------------------------------------- #
def test_bias_read_failures_deviceerror_plan(sim):
    """bias.read() raises on every compliance check → after 3 consecutive
    unreadable points the run raises DeviceError, fails safe, and preserves the
    two points taken while the single-glitch tolerance still held."""
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    # read() raises everywhere it is called: swallowed inside _acquire_core
    # (best-effort context), counted inside _check_compliance.
    ch.read = raise_after(0, DeviceError("bias supply unreadable"))

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_plan(-30.0, points=3), _limits(), AutoConfirmGate())
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert ctrl._writer._n_points == 2            # 2 tolerated, 3rd aborts
    assert any("unreadable" in m.lower() for m in errs)
    assert ch.setpoint_V == 0.0                   # HV failsafed
    assert not ch.driver.output_is_on_ch(ch.channel)
    assert ch.output_off.called
    assert_writer_closed(ctrl)


# --------------------------------------------------------------------------- #
# 5. Waveform-generator failure at acquire (output_on raises)                  #
# --------------------------------------------------------------------------- #
def test_wavegen_output_on_fault_plan(sim):
    """output_on() raises at the first acquire → the run errors WITHOUT wedging
    the thread, and output_off() is still attempted in the finally."""
    dm, ctrl, sm = sim
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    dm.waveform_generator.output_on = raise_after(
        0, DeviceError("wavegen output enable failed"))

    ctrl.start_plan(_stage_plan([0.0, 1.0]), _limits(), AutoConfirmGate())
    join_or_fail(ctrl)

    assert sm.state is AppState.ERROR
    assert errs
    assert wf_off.called                          # attempted in finally
    assert ctrl._writer._n_points == 0
    assert_writer_closed(ctrl)


# --------------------------------------------------------------------------- #
# 6. Abort during a long WaitStep — prompt exit + fail-safe                    #
# --------------------------------------------------------------------------- #
def _spy_wait_entry(ctrl):
    """Wrap _abortable_sleep so a test can wait until the run parks in it."""
    entered = threading.Event()
    orig = ctrl._abortable_sleep

    def spy(seconds):
        entered.set()
        return orig(seconds)

    ctrl._abortable_sleep = spy
    return entered


def test_abort_during_wait_bias_plan(sim):
    """Abort while parked in a 30 s WAIT (HV energized) → exits < 0.5 s, ABORTED,
    HV ramped to 0 + output off, writer closed."""
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    entered = _spy_wait_entry(ctrl)

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_wait_plan(-20.0, seconds=30.0), _limits(), AutoConfirmGate())

    assert entered.wait(timeout=10), "run never reached the WaitStep"
    t0 = time.monotonic()
    ctrl.abort()
    join_or_fail(ctrl, timeout=5)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, f"abort during WaitStep took {elapsed:.2f}s"
    assert sm.state is AppState.ABORTED
    assert ch.setpoint_V == 0.0                   # HV failsafed on abort
    assert not ch.driver.output_is_on_ch(ch.channel)
    assert ch.output_off.called
    assert_writer_closed(ctrl)


def test_abort_during_wait_stage_plan(sim):
    """Abort while parked in a 30 s WAIT (no HV) → exits < 0.5 s, ABORTED,
    laser off, writer closed."""
    dm, ctrl, sm = sim
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off
    entered = _spy_wait_entry(ctrl)

    ctrl.start_plan(_stage_wait_plan(1.0, seconds=30.0), _limits(), AutoConfirmGate())

    assert entered.wait(timeout=10), "run never reached the WaitStep"
    t0 = time.monotonic()
    ctrl.abort()
    join_or_fail(ctrl, timeout=5)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, f"abort during WaitStep took {elapsed:.2f}s"
    assert sm.state is AppState.ABORTED
    assert wf_off.called
    assert_writer_closed(ctrl)
