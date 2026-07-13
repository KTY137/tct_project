"""A latched HV trip must ABORT the scan — it is not a clean finish, and it is
not silence.

Mary's review of the driver batch (c269e93): the iseg driver decodes the module
channel-status word into ``BiasReading.tripped`` / ``.output_on_hw`` (raw word on
``.status_word``), and **nothing consumed them** — ``_check_compliance`` read only
``reading.compliant``.

The failure that made this a MAJOR: on a REAL current trip the module switches the
channel OFF by itself.  The measured current therefore collapses to ~0, so
``compliant`` computes to **False** — no compliance breach! — and the scan kept
acquiring and writing points **with the HV off**, recorded in HDF5 as if biased.
Physically worthless data, produced silently.

The other half is law 8 (never launder UNKNOWN into a claim): the status fields are
``None`` whenever a backend cannot read a status word (every simulated supply,
Keithley, e4control, or a failed ``:READ:CHAN:STAT?`` on the iseg itself).  A
truthiness test (``if not reading.tripped``) would read "I don't know" as a
confident "not tripped".  UNKNOWN must never be treated as healthy — and must never
abort a run either.  Both halves are pinned below.

Everything runs on fully-simulated backends: the trip is injected by monkeypatching
``read()`` on the *simulated* BiasChannel to return the new fields (no ``devices/``
change, no hardware).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time

import h5py
import pytest
import yaml

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import (
    ScanController, ScanConfig, VoltageScanConfig,
)
from devices.bias_supply_base import BiasReading


# --------------------------------------------------------------------------- #
# harness                                                                      #
# --------------------------------------------------------------------------- #
@pytest.fixture
def make_ctrl(tmp_path):
    """(dm, ctrl, sm) on fully-simulated backends, state READY."""
    created: list = []

    def _factory():
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
        dm = DeviceManager(config_path=str(path))
        assert dm.config_errors() == [], dm.config_errors()
        assert all(v == "ok" for v in dm.connect_all().values())
        dm.motor.home()
        sm = StateMachine()
        for st in (AppState.CONNECTED, AppState.HOMED,
                   AppState.CONFIGURED, AppState.READY):
            sm.transition(st)
        ctrl = ScanController(dm, sm)
        ctrl._PAUSE_POLL_S = 0.02        # fast park supervision for tests
        created.append(dm)
        return dm, ctrl, sm

    yield _factory
    for dm in created:
        dm.disconnect_all()


def _vscan(**over) -> VoltageScanConfig:
    """A short, fast IV sweep: 0 → -20 V in 10 V steps (3 points)."""
    d = dict(v_start_V=0.0, v_stop_V=-20.0, v_step_V=-10.0,
             ramp_step_V=20.0, ramp_delay_s=0.0, hold_delay_s=0.0,
             n_averages=1)
    d.update(over)
    return VoltageScanConfig(**d)


def _xy(**over) -> ScanConfig:
    """A 4-point XY map (fast: no settle)."""
    d = dict(x_start_mm=0.0, x_stop_mm=0.1, x_step_mm=0.1,
             y_start_mm=0.0, y_stop_mm=0.1, y_step_mm=0.1,
             n_averages=1, settle_time_s=0.0)
    d.update(over)
    return ScanConfig(**d)


def _wait_state(sm, state, timeout=20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline and sm.state is not state:
        time.sleep(0.01)
    return sm.state is state


def _join(ctrl, timeout=20.0) -> None:
    if ctrl._thread is not None:
        ctrl._thread.join(timeout=timeout)
        assert not ctrl._thread.is_alive(), "worker thread did not finish"


def _saved_points(ctrl) -> int:
    """Points actually on DISK (the only honest count — callbacks can lie)."""
    path = ctrl.last_run_path
    assert path is not None and path.exists(), "run file was never written"
    with h5py.File(path, "r") as f:
        assert "stop_time" in f.attrs, "writer was not flushed/closed on abort"
        if "points" not in f or "x_mm" not in f["points"]:
            return 0
        return int(f["points"]["x_mm"].shape[0])


def _reading(**over) -> BiasReading:
    """A BiasReading carrying the driver's new status fields.

    Defaults are the *healthy iseg* case (status word readable, no trip, output
    confirmed on) — each test overrides exactly the field under test.
    """
    d = dict(voltage_V=-100.0, current_A=2e-9, compliant=False,
             status_word=0x0008, tripped=False, output_on_hw=True)
    d.update(over)
    return BiasReading(**d)


# =========================================================================== #
# THE BUG — a latched trip is a fail-safe abort, not a silent nothing         #
# =========================================================================== #
def test_latched_trip_midscan_aborts_and_failsafes(make_ctrl):
    """The headline case, through the shared ``_check_compliance`` (XY loop).

    ``tripped=True`` while ``compliant=False`` and the current at ~0 A — i.e.
    EXACTLY what a real trip looks like from the outside (the module opened the
    channel, so no compliance breach is measurable).  The old code saw a healthy
    reading and kept writing points with the HV off.
    """
    dm, ctrl, sm = make_ctrl()
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    bias = dm.bias_supply
    bias.ramp_to(-100.0, step_V=100.0, delay_s=0.0)     # operator biased the DUT
    assert bias.driver.output_is_on_ch(bias.channel)

    # The module trips once the first point is safely on disk.  Keyed on the
    # point callback, NOT on a read counter: a scan point costs more than one
    # bias.read() (the per-point snapshot plus the guard), and this test is about
    # the trip, not about that ratio.
    tripped_now = threading.Event()
    ctrl.on_point_done = lambda r: tripped_now.set()

    def tripping_read():
        if not tripped_now.is_set():
            return _reading()                            # healthy
        # The module latched a trip and opened the channel ITSELF: current ~0,
        # so `compliant` is False — the trip is visible ONLY in `tripped`.
        return _reading(voltage_V=0.0, current_A=1e-12, compliant=False,
                        status_word=0x0810, tripped=True, output_on_hw=False)
    bias.read = tripping_read

    ctrl.start(_xy())
    _join(ctrl)

    assert sm.state is AppState.ABORTED, "a latched trip must NOT settle FINISHED"
    assert ctrl._abort_event.is_set()
    # _bias_failsafe ran: HV ramped to 0 V and the output opened.
    assert bias.setpoint_V == 0.0
    assert not bias.driver.output_is_on_ch(bias.channel)
    # The operator was told, and told WHY.
    assert errs, "on_error never fired for a latched trip"
    assert "trip" in errs[-1].lower()
    # Data already taken is preserved; NOT ONE point was written after the trip.
    assert _saved_points(ctrl) == 1


def test_latched_trip_in_voltage_scan_aborts(make_ctrl):
    """The IV sweep evaluates its OWN BiasReading (it never calls
    ``_check_compliance``), so the trip guard has to be wired there too — this is
    the loop that actively DRIVES the HV, so missing a trip here means stepping
    the setpoint of a supply that has already dropped out."""
    dm, ctrl, sm = make_ctrl()
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    points: list = []
    ctrl.on_vscan_point = lambda v, c, i: points.append(v)
    bias = dm.bias_supply

    calls = {"n": 0}

    def tripping_read():
        calls["n"] += 1
        if calls["n"] < 2:
            return _reading(voltage_V=0.0)
        return _reading(voltage_V=0.0, current_A=1e-12, compliant=False,
                        status_word=0x0810, tripped=True, output_on_hw=False)
    bias.read = tripping_read

    ctrl.start_voltage_scan(_vscan())
    _join(ctrl)

    assert sm.state is AppState.ABORTED
    assert len(points) == 1, "the sweep kept recording IV points after the trip"
    assert bias.setpoint_V == 0.0
    assert not bias.driver.output_is_on_ch(bias.channel)
    assert errs and "trip" in errs[-1].lower()


def test_output_dropped_under_us_aborts(make_ctrl):
    """``output_on_hw is False`` while the DRIVER believes the output is ON.

    No latched trip bit — the channel just went away (inhibit, front panel, a trip
    the module already cleared).  Same verdict: whatever we acquire from here on is
    UNBIASED data that would be written to HDF5 as if biased.
    """
    dm, ctrl, sm = make_ctrl()
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    bias = dm.bias_supply
    bias.ramp_to(-100.0, step_V=100.0, delay_s=0.0)
    assert bias.driver.output_is_on_ch(bias.channel), "driver must believe ON"

    dropped_now = threading.Event()
    ctrl.on_point_done = lambda r: dropped_now.set()

    def dropped_read():
        if not dropped_now.is_set():
            return _reading()
        return _reading(voltage_V=0.0, current_A=1e-12, compliant=False,
                        status_word=0x0000, tripped=False, output_on_hw=False)
    bias.read = dropped_read

    ctrl.start(_xy())
    _join(ctrl)

    assert sm.state is AppState.ABORTED, "a dropped output must abort the run"
    assert ctrl._abort_event.is_set()
    assert bias.setpoint_V == 0.0
    assert not bias.driver.output_is_on_ch(bias.channel)
    assert errs and "off" in errs[-1].lower()
    assert _saved_points(ctrl) == 1


# =========================================================================== #
# LAW 8 — UNKNOWN is not healthy, and UNKNOWN is not a fault either           #
# =========================================================================== #
def test_unknown_trip_state_does_not_abort(make_ctrl):
    """``tripped=None`` (the backend cannot read a status word) must NOT abort.

    This is the half of the fix that is easy to get wrong in the other direction:
    a guard written as ``if reading.tripped is not False: abort`` would make every
    non-status-reporting backend (simulated, Keithley, e4control) unusable.
    UNKNOWN stays UNKNOWN — no claim, no abort, run continues.
    """
    dm, ctrl, sm = make_ctrl()
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    bias = dm.bias_supply
    bias.ramp_to(-100.0, step_V=100.0, delay_s=0.0)      # driver believes ON

    # Everything the module could have told us is None: this is what EVERY
    # simulated / non-iseg read looks like today.
    bias.read = lambda: _reading(status_word=None, tripped=None, output_on_hw=None)

    ctrl.start(_xy())
    _join(ctrl)

    assert sm.state is AppState.FINISHED, "UNKNOWN status was mistaken for a fault"
    assert not ctrl._abort_event.is_set()
    assert errs == []
    assert _saved_points(ctrl) == 4                      # the whole map was written


def test_default_bias_reading_has_unknown_status_and_never_aborts(make_ctrl):
    """The bare 3-field BiasReading every other backend still constructs must
    stay a no-op for the trip guard (defaults are None = UNKNOWN)."""
    dm, ctrl, sm = make_ctrl()
    bias = dm.bias_supply
    bias.ramp_to(-100.0, step_V=100.0, delay_s=0.0)
    legacy = BiasReading(voltage_V=-100.0, current_A=2e-9, compliant=False)
    assert legacy.tripped is None and legacy.output_on_hw is None
    bias.read = lambda: legacy

    ctrl.start(_xy())
    _join(ctrl)

    assert sm.state is AppState.FINISHED
    assert _saved_points(ctrl) == 4


def test_bias_hw_fault_truth_table(make_ctrl):
    """Pin the tri-state decode itself: ``is True`` / ``is False``, never truthiness.

    A truthiness guard (``if not reading.tripped``) passes rows 1-2 and silently
    fails row 3 — the exact bug.  A too-eager guard (``is not False``) fails rows
    4-6.  Only the tri-state decode passes all of them.
    """
    dm, ctrl, sm = make_ctrl()
    bias = dm.bias_supply
    bias.ramp_to(-100.0, step_V=100.0, delay_s=0.0)      # driver believes ON
    assert bias.driver.output_is_on_ch(bias.channel)

    # (tripped, output_on_hw, expect_fault)
    cases = [
        (False, True,  False),   # 1. healthy, fully reported
        (False, None,  False),   # 2. healthy, output state unknown
        (True,  False, True),    # 3. LATCHED TRIP — module opened the channel
        (True,  True,  True),    # 4. latched trip, output still shown on
        (None,  None,  False),   # 5. UNKNOWN — no status word at all
        (None,  True,  False),   # 6. UNKNOWN trip, output confirmed on
        (False, False, True),    # 7. output dropped under a driver that believes ON
    ]
    for tripped, on_hw, expect in cases:
        r = _reading(tripped=tripped, output_on_hw=on_hw)
        fault = ctrl._bias_hw_fault(bias, r)
        assert (fault is not None) is expect, (
            f"tripped={tripped!r}, output_on_hw={on_hw!r} -> {fault!r}")

    # UNKNOWN output_on_hw + a driver that believes ON is still not a fault...
    assert ctrl._bias_hw_fault(bias, _reading(output_on_hw=None)) is None
    # ...and output_on_hw=False is NOT a fault when the driver agrees it is off
    # (an unbiased scan is legal — the guard must not invent a fault there).
    bias.output_off()
    assert not bias.driver.output_is_on_ch(bias.channel)
    assert ctrl._bias_hw_fault(bias, _reading(output_on_hw=False)) is None
    # ...but a LATCHED TRIP is a fault regardless of what anyone believes.
    assert ctrl._bias_hw_fault(bias, _reading(tripped=True)) is not None


# =========================================================================== #
# The paused-run park watchdog inherits the trip guard                        #
# =========================================================================== #
def test_paused_run_aborts_on_latched_trip(make_ctrl):
    """A run parked in PAUSED HOLDS the HV — it is the worst place to miss a trip.

    The park watchdog polls ``_check_compliance``, so it inherits the hardware-fault
    guard for free.  Pin it: a trip latched WHILE PAUSED must fail-safe abort out of
    PAUSED (ABORTED is legal from PAUSED — no promotion through RUNNING).
    """
    dm, ctrl, sm = make_ctrl()
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    first_point = threading.Event()
    ctrl.on_vscan_point = lambda v, c, i: first_point.set()
    bias = dm.bias_supply

    ctrl.start_voltage_scan(_vscan(v_stop_V=-40.0, hold_delay_s=0.3))
    assert first_point.wait(timeout=20.0), "no IV point acquired"

    ctrl.pause()
    assert _wait_state(sm, AppState.PAUSED)
    assert bias.setpoint_V != 0.0, "the pause should be HOLDING HV"

    # The supply trips while the run sits parked at HV; nothing else is watching.
    bias.read = lambda: _reading(voltage_V=0.0, current_A=1e-12, compliant=False,
                                 status_word=0x0810, tripped=True,
                                 output_on_hw=False)

    assert _wait_state(sm, AppState.ABORTED, timeout=10.0), (
        "the paused-at-HV watchdog must fail-safe abort on a latched trip")
    _join(ctrl)
    assert bias.setpoint_V == 0.0                          # HV ramped down
    assert not bias.driver.output_is_on_ch(bias.channel)   # output opened
    assert errs and "trip" in errs[-1].lower()
    assert ctrl.last_run_path is not None                  # writer flushed


def test_paused_run_survives_unknown_status(make_ctrl):
    """The watchdog must not be trigger-happy either: an UNKNOWN status word while
    parked keeps holding HV and resumes to a clean FINISHED."""
    dm, ctrl, sm = make_ctrl()
    first_point = threading.Event()
    ctrl.on_vscan_point = lambda v, c, i: first_point.set()
    bias = dm.bias_supply
    bias.read = lambda: _reading(status_word=None, tripped=None, output_on_hw=None)

    ctrl.start_voltage_scan(_vscan(v_stop_V=-40.0, hold_delay_s=0.2))
    assert first_point.wait(timeout=20.0)

    ctrl.pause()
    assert _wait_state(sm, AppState.PAUSED)
    time.sleep(0.2)                          # several supervision sweeps
    assert sm.state is AppState.PAUSED       # still parked, still holding HV
    assert not ctrl._abort_event.is_set()

    ctrl.resume()
    _join(ctrl)
    assert sm.state is AppState.FINISHED


# =========================================================================== #
# A healthy run is untouched                                                  #
# =========================================================================== #
def test_healthy_run_with_tripped_false_is_unaffected(make_ctrl):
    """``tripped=False`` + ``output_on_hw=True`` — a fully-reporting, healthy iseg.
    The guard must be invisible: the whole map is acquired and written."""
    dm, ctrl, sm = make_ctrl()
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    done: list = []
    ctrl.on_point_done = lambda r: done.append(r)
    bias = dm.bias_supply
    bias.ramp_to(-100.0, step_V=100.0, delay_s=0.0)

    bias.read = lambda: _reading()           # healthy, fully reported

    ctrl.start(_xy())
    _join(ctrl)

    assert sm.state is AppState.FINISHED
    assert not ctrl._abort_event.is_set()
    assert errs == []
    assert len(done) == 4
    assert _saved_points(ctrl) == 4
