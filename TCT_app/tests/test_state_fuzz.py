"""Seeded random-walk STATE FUZZER for the run lifecycle (Kaya's "fuzzy state
testing").

This drives the REAL :class:`StateMachine` + :class:`ScanController` against
fully-*simulated* devices through many short, seeded random walks.  Every walk
is a `random.Random(seed)` sequence of run-lifecycle operations drawn from an
alphabet of:

  * legal ops       — connect/home/configure/ready, arm HV, start a tiny plan,
                       pause, resume, abort, drain-to-terminal, advance/reset;
  * illegal ops     — start when not READY, resume when RUNNING, an illegal
                       StateMachine transition, unarmed-bias start, a plan that
                       fails validation, double-abort;
  * fault injection — bias-read failure, slow-control WARN (safe-hold) and ALARM
                       (fail-safe abort) via a monkeypatched snapshot, a motor
                       error, a gate DENY (:class:`DenyAllGate`), and an
                       envelope-out-of-range attempt (:class:`ArmedEnvelopeGate`
                       armed with a *mismatched* envelope).

After EVERY step the harness asserts the invariants below.  On ANY failure it
prints a `FUZZ REPRO: seed=... actions=[...]` line so the exact walk can be
replayed, then fails.

Invariants (the value of this file)
-----------------------------------
  (a) ``sm.state`` is always a valid :class:`AppState`.
  (b) an illegal transition / illegal op is REFUSED without a state change.
  (c) once a run's worker ends: HV is disarmed (``ctrl._hv_armed`` False), and
      for a bias-driving run the fail-safe ran (setpoint 0 V + output off); the
      terminal state is in {ABORTED, ERROR, FINISHED} (and lifecycle may then
      advance to CONFIGURED).
  (d) abort from a *parked* PAUSED run is always accepted → ABORTED (also proved
      deterministically for RUNNING and PAUSED below).
  (e) no exception ever escapes a worker thread uncaught (``threading.excepthook``).
  (f) on a terminal run the writer is closed (never half-open) and
      ``last_run_path`` is consistent (a flushed file on disk, or absent).

Everything is simulation-only and monkeypatched — a run is safe with real
hardware attached (no hardware/network I/O, no widgets).  Controller code is NOT
modified here; any real defect found is reported to Adam (see the module-level
note on the start-while-PAUSED gap and the xfail probe at the bottom).
"""
from __future__ import annotations

import random
import threading
import traceback
import unittest.mock as mock

import pytest
import yaml

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import AutoConfirmGate, DenyAllGate
from controller.arm_envelope import ArmedEnvelopeGate, envelope_from_plan
from devices.slow_control_base import AlarmStatus, SlowControlReading


TERMINAL = {AppState.FINISHED, AppState.ERROR, AppState.ABORTED}
# Forward lifecycle edge toward READY (the GUI's connect→home→configure→ready).
_FORWARD = {
    AppState.DISCONNECTED: AppState.CONNECTED,
    AppState.CONNECTED:    AppState.HOMED,
    AppState.HOMED:        AppState.CONFIGURED,
    AppState.CONFIGURED:   AppState.READY,
}
_JOIN_TIMEOUT = 10.0     # a run should terminate in ms; this is only a hang cap.


# --------------------------------------------------------------------------- #
# fully-simulated environment + tiny plan builders                            #
# --------------------------------------------------------------------------- #
def _sim_config(data_dir) -> dict:
    return {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "simulated"},
        "camera":             {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":        {"backend": "simulated"},
        "output":             {"data_dir": str(data_dir)},
    }


def _make_env(work_dir):
    """A ready ``(dm, ctrl, sm)`` on fully-simulated backends; sm at DISCONNECTED."""
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "devices.yaml"
    path.write_text(yaml.safe_dump(_sim_config(work_dir / "runs")), encoding="utf-8")
    dm = DeviceManager(config_path=str(path))
    assert dm.config_errors() == [], dm.config_errors()
    assert all(v == "ok" for v in dm.connect_all().values())
    dm.motor.zero_position()
    sm = StateMachine()
    ctrl = ScanController(dm, sm)
    # Non-raising recorders (the GUI wires these; a raising callback would be a
    # separate bug — here they must never perturb the run).
    ctrl.on_error = lambda m: None
    ctrl.on_finished = lambda: None
    ctrl.on_manual_pause = lambda p: None
    ctrl.on_point_done = lambda r: None
    ctrl.on_progress = lambda a, b: None
    return dm, ctrl, sm


def _limits(**over) -> PlanLimits:
    d = dict(x_min_mm=-50.0, x_max_mm=50.0, y_min_mm=-50.0, y_max_mm=50.0,
             z_min_mm=-10.0, z_max_mm=10.0, voltage_range_V=1000.0,
             max_points=1_000_000)
    d.update(over)
    return PlanLimits(**d)


def _acq(**p):
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params=p)


def _save():
    return ActionBlock(action=ActionType.SAVE_POINT, params={})


def _pause(msg="hold"):
    return ActionBlock(action=ActionType.MANUAL_PAUSE, params={"prompt": msg})


def _wait(seconds):
    return ActionBlock(action=ActionType.WAIT, params={"seconds": float(seconds)})


def _stage_plan(values):
    loop = LoopBlock(axis=Axis.STAGE_X, values=[float(v) for v in values],
                     children=[_acq(), _save()])
    return ScanPlan(name="stage", root=[loop])


def _bias_plan(target, points=1):
    children = []
    for _ in range(points):
        children.extend([_acq(), _save()])
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)], children=children)
    return ScanPlan(name="bias", root=[loop],
                    safety={"require_hv_confirmation": True})


def _midpause_plan():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(), _save(), _pause(), _acq(), _save()])
    return ScanPlan(name="midpause", root=[loop])


def _wait_plan(seconds):
    """A run that dwells in RUNNING inside an abortable WaitStep."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_wait(seconds), _acq(), _save()])
    return ScanPlan(name="wait", root=[loop])


def _warn_snapshot():
    return {"temp_C": SlowControlReading(name="temp_C", value=99.0, unit="C",
                                         timestamp=0.0, status=AlarmStatus.WARN_HIGH)}


def _alarm_snapshot():
    return {"temp_C": SlowControlReading(name="temp_C", value=140.0, unit="C",
                                         timestamp=0.0, status=AlarmStatus.ALARM_HIGH)}


# --------------------------------------------------------------------------- #
# run flavors: each returns (plan, gate, meta) and applies any fault patch     #
# meta keys: bias(bool), fault(str|None), parks(bool)                          #
# --------------------------------------------------------------------------- #
_START_FLAVORS = (
    "clean_stage", "clean_bias", "deny_stage", "deny_bias",
    "env_mismatch_stage", "env_mismatch_bias",
    "fault_motor", "fault_biasread", "fault_scwarn", "fault_scalarm",
    "midpause",
)


def _wait_state(sm, state, deadline_s=_JOIN_TIMEOUT):
    import time
    end = time.time() + deadline_s
    while time.time() < end and sm.state is not state:
        time.sleep(0.005)
    return sm.state is state


# --------------------------------------------------------------------------- #
# the walk                                                                     #
# --------------------------------------------------------------------------- #
class FuzzWalk:
    def __init__(self, dm, ctrl, sm, rng, thread_excs):
        self.dm, self.ctrl, self.sm, self.rng = dm, ctrl, sm, rng
        self.thread_excs = thread_excs
        self.actions: list[str] = []
        self.run: dict | None = None     # metadata for the in-flight/last run
        self._restores: list = []        # (obj, attr, orig) for fault patches

    # -- fault-patch bookkeeping -------------------------------------------- #
    def _patch(self, obj, attr, value):
        self._restores.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)

    def _do_restores(self):
        while self._restores:
            obj, attr, orig = self._restores.pop()
            setattr(obj, attr, orig)

    # -- thread helpers ----------------------------------------------------- #
    def _alive(self) -> bool:
        t = self.ctrl._thread
        return t is not None and t.is_alive()

    def _join(self):
        t = self.ctrl._thread
        if t is not None:
            t.join(timeout=_JOIN_TIMEOUT)
            assert not t.is_alive(), "worker thread did not terminate (hang)"

    # -- launch a run flavor ------------------------------------------------- #
    def _start_run(self, flavor):
        ctrl = self.ctrl
        meta = {"bias": False, "fault": None, "parks": False}
        if flavor == "clean_stage":
            plan, gate = _stage_plan([0.0, 1.0]), AutoConfirmGate()
        elif flavor == "clean_bias":
            ctrl.arm_hv(True)
            plan, gate = _bias_plan(-10.0), AutoConfirmGate()
            meta["bias"] = True
        elif flavor == "deny_stage":
            plan, gate = _stage_plan([0.0, 1.0]), DenyAllGate()
            meta["fault"] = "deny"
        elif flavor == "deny_bias":
            ctrl.arm_hv(True)
            plan, gate = _bias_plan(-10.0), DenyAllGate()
            meta["bias"], meta["fault"] = True, "deny"
        elif flavor == "env_mismatch_stage":
            # armed for a disjoint x window → the live move is out of envelope.
            gate = ArmedEnvelopeGate(envelope_from_plan(_stage_plan([45.0, 46.0]), 0))
            plan = _stage_plan([0.0, 1.0])
            meta["fault"] = "deny"
        elif flavor == "env_mismatch_bias":
            ctrl.arm_hv(True)
            gate = ArmedEnvelopeGate(envelope_from_plan(_bias_plan(-5.0), 0))
            plan = _bias_plan(-40.0)              # -40 V outside armed [-5, -5]
            meta["bias"], meta["fault"] = True, "deny"
        elif flavor == "fault_motor":
            self._patch(self.dm.motor, "move_to",
                        mock.Mock(side_effect=RuntimeError("sim motor fault")))
            plan, gate = _stage_plan([0.0, 1.0]), AutoConfirmGate()
            meta["fault"] = "motor"
        elif flavor == "fault_biasread":
            self._patch(self.dm.bias_supply, "read",
                        mock.Mock(side_effect=RuntimeError("sim bias read fault")))
            plan, gate = _stage_plan([0.0, 1.0, 2.0]), AutoConfirmGate()
            meta["fault"] = "biasread"
        elif flavor == "fault_scwarn":
            self._patch(self.dm.slow_control, "read_all", lambda: _warn_snapshot())
            plan, gate = _stage_plan([0.0, 1.0]), AutoConfirmGate()
            meta["fault"], meta["parks"] = "warn", True
        elif flavor == "fault_scalarm":
            self._patch(self.dm.slow_control, "read_all", lambda: _alarm_snapshot())
            plan, gate = _stage_plan([0.0, 1.0]), AutoConfirmGate()
            meta["fault"] = "alarm"
        elif flavor == "midpause":
            plan, gate = _midpause_plan(), AutoConfirmGate()
            meta["parks"] = True
        else:  # pragma: no cover
            raise AssertionError(flavor)

        ctrl.start_plan(plan, _limits(), gate)
        self.run = meta
        return f"start:{flavor}"

    # -- step dispatch ------------------------------------------------------- #
    def step(self) -> str:
        if self._alive():
            name = self._step_run_active()
        else:
            st = self.sm.state
            if st is AppState.READY:
                name = self._step_ready()
            elif st in TERMINAL:
                name = self._step_terminal()
            else:
                name = self._step_lifecycle()
        self.actions.append(name)
        return name

    def _step_run_active(self) -> str:
        ctrl, sm, rng = self.ctrl, self.sm, self.rng
        choice = rng.choice(["drain", "drain", "abort", "resume", "pause",
                             "illegal_resume", "double_abort", "noop"])
        if choice == "noop":
            return "noop"
        if choice == "illegal_resume":
            # resume() is a guarded no-op unless PAUSED — must never raise.
            ctrl.resume()
            return "illegal_resume"
        if choice == "double_abort":
            ctrl.abort(); ctrl.abort()
            self._join()
            return "double_abort"
        if choice == "pause":
            if sm.state is AppState.RUNNING:
                try:
                    ctrl.pause()          # may race the run to a terminal state
                except ValueError:
                    pass
            return "pause"
        if choice == "resume":
            ctrl.resume()
            return "resume"
        if choice == "abort":
            parked = self.run is not None and self.run.get("parks")
            was_paused = sm.state is AppState.PAUSED
            ctrl.abort()                  # sets abort_event → no further park
            self._join()
            if parked and was_paused:
                # (d) abort from a genuinely parked PAUSED run is always accepted.
                assert sm.state is AppState.ABORTED, \
                    f"abort from parked PAUSED → {sm.state}"
            return "abort"
        # drain: run to terminal, driving every park (which may only appear AFTER
        # this step began) forward with a resume-or-abort until the worker ends.
        self._drain_to_terminal()
        return "drain"

    def _drain_to_terminal(self):
        """Poll until the worker ends, resuming/aborting whenever it parks."""
        import time
        deadline = time.time() + _JOIN_TIMEOUT
        while self._alive():
            if self.sm.state is AppState.PAUSED:
                if self.rng.random() < 0.5:
                    self.ctrl.resume()
                else:
                    self.ctrl.abort()
            else:
                if time.time() >= deadline:
                    break
                time.sleep(0.005)
        assert not self._alive(), "worker thread did not terminate (hang)"

    def _step_ready(self) -> str:
        ctrl, sm, rng = self.ctrl, self.sm, self.rng
        r = rng.random()
        if r < 0.68:
            return self._start_run(rng.choice(_START_FLAVORS))
        if r < 0.80:
            return self._illegal_unarmed_bias()
        if r < 0.90:
            return self._illegal_bad_validation()
        if r < 0.96:
            ctrl.resume()                 # illegal_resume from READY → no-op
            assert sm.state is AppState.READY
            return "illegal_resume"
        sm.transition(AppState.DISCONNECTED)
        return "reset"

    def _step_terminal(self) -> str:
        rng = self.rng
        c = rng.choice(["advance", "advance", "reset", "illegal_transition",
                        "illegal_start"])
        if c == "advance":
            self.run = None
            self.sm.transition(AppState.CONFIGURED)
            return "advance"
        if c == "reset":
            self.run = None
            self.sm.transition(AppState.DISCONNECTED)
            return "reset"
        if c == "illegal_transition":
            return self._illegal_transition()
        return self._illegal_start()

    def _step_lifecycle(self) -> str:
        rng, sm = self.rng, self.sm
        c = rng.choice(["advance", "advance", "reset", "illegal_transition",
                        "illegal_start"])
        if c == "advance":
            sm.transition(_FORWARD[sm.state])
            return "advance"
        if c == "reset":
            if sm.state is not AppState.DISCONNECTED:
                sm.transition(AppState.DISCONNECTED)
            return "reset"
        if c == "illegal_transition":
            return self._illegal_transition()
        return self._illegal_start()

    # -- illegal ops (assert refusal + no state change inline) --------------- #
    def _illegal_transition(self) -> str:
        sm = self.sm
        pre = sm.state
        targets = [t for t in AppState if not sm.can(t)]
        t = self.rng.choice(targets)
        with pytest.raises(ValueError):
            sm.transition(t)
        assert sm.state is pre, "illegal transition changed state"
        return f"illegal_transition->{t.name}"

    def _illegal_start(self) -> str:
        # From any state where can(RUNNING) is False, start_plan must refuse
        # with no state change and no worker thread.
        ctrl, sm = self.ctrl, self.sm
        assert not sm.can(AppState.RUNNING)
        pre_state, pre_thread = sm.state, ctrl._thread
        with pytest.raises(RuntimeError):
            ctrl.start_plan(_stage_plan([0.0]), _limits(), AutoConfirmGate())
        assert sm.state is pre_state, "refused start changed state"
        assert ctrl._thread is pre_thread, "refused start launched a thread"
        return "illegal_start"

    def _illegal_unarmed_bias(self) -> str:
        ctrl, sm = self.ctrl, self.sm
        ctrl.arm_hv(False)
        pre_state, pre_thread = sm.state, ctrl._thread
        with pytest.raises(RuntimeError, match="armed"):
            ctrl.start_plan(_bias_plan(-10.0), _limits(), AutoConfirmGate())
        assert sm.state is pre_state
        assert ctrl._thread is pre_thread
        assert ctrl._hv_armed is False
        return "illegal_unarmed_bias"

    def _illegal_bad_validation(self) -> str:
        ctrl, sm = self.ctrl, self.sm
        ctrl.arm_hv(True)                 # a refused start must also clear the arm
        pre_state, pre_thread = sm.state, ctrl._thread
        with pytest.raises(ValueError, match="validation"):
            ctrl.start_plan(_stage_plan([0.0, 1000.0]), _limits(), AutoConfirmGate())
        assert sm.state is pre_state
        assert ctrl._thread is pre_thread
        assert ctrl._hv_armed is False    # arm latch cleared on refusal
        return "illegal_bad_validation"

    # -- invariants (after every step) --------------------------------------- #
    def check_invariants(self):
        ctrl, sm = self.ctrl, self.sm
        # (a)
        assert isinstance(sm.state, AppState), f"invalid state {sm.state!r}"
        # (e)
        assert not self.thread_excs, \
            "worker thread raised uncaught:\n" + "\n".join(self.thread_excs)

        if self.run is not None and not self._alive():
            self._do_restores()           # a faulted run is over; undo its patch
            st = sm.state
            assert st in TERMINAL, f"finished run left non-terminal state {st}"
            # (c) HV disarmed after every run
            assert ctrl._hv_armed is False, "HV still armed after run ended"
            if self.run["bias"]:
                ch = ctrl._dev.bias_supply
                assert ch.setpoint_V == 0.0, "bias not ramped to 0 on terminal"
                assert not ch.driver.output_is_on_ch(ch.channel), \
                    "bias output still on after terminal"
            # (f) writer/last_run_path consistency
            self._check_writer()

    def _check_writer(self):
        ctrl = self.ctrl
        w = ctrl._writer
        lrp = ctrl.last_run_path
        if w is None:
            assert lrp is None
            return
        assert w._file is None, "writer left half-open (file handle not closed)"
        assert lrp is not None, "last_run_path not published on terminal"
        assert lrp == w.path
        assert lrp.name == "waveforms.h5"
        assert lrp.exists(), "run file not flushed to disk"

    # -- teardown ------------------------------------------------------------ #
    def drain_and_check(self):
        if self._alive():
            self.ctrl.abort()
            self._join()
        self.check_invariants()

    def teardown(self):
        try:
            if self._alive():
                self.ctrl.abort()
                self._join()
        finally:
            self._do_restores()
            self.dm.disconnect_all()


# --------------------------------------------------------------------------- #
# fuzz driver                                                                  #
# --------------------------------------------------------------------------- #
def _run_fuzz(tmp_path, n_walks, n_steps, base_seed):
    orig_hook = threading.excepthook
    thread_excs: list[str] = []

    def _hook(args):
        thread_excs.append(
            "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback)))

    threading.excepthook = _hook
    seeds_used = []
    try:
        for w in range(n_walks):
            seed = base_seed + w
            seeds_used.append(seed)
            thread_excs.clear()
            dm, ctrl, sm = _make_env(tmp_path / f"walk_{w:03d}")
            walk = FuzzWalk(dm, ctrl, sm, random.Random(seed), thread_excs)
            step_i = -1
            try:
                for step_i in range(n_steps):
                    walk.step()
                    walk.check_invariants()
                walk.drain_and_check()
                assert not thread_excs, \
                    "worker thread raised uncaught:\n" + "\n".join(thread_excs)
            except BaseException:
                print(f"\nFUZZ REPRO: seed={seed} failed_at_step={step_i}")
                print(f"FUZZ REPRO: actions={walk.actions}")
                raise
            finally:
                walk.teardown()
    finally:
        threading.excepthook = orig_hook
    return seeds_used


# --------------------------------------------------------------------------- #
# fast smoke variant (unmarked) + the big walk (@slow)                         #
# --------------------------------------------------------------------------- #
def test_state_fuzz_smoke(tmp_path):
    """3 short walks — a fast, always-on guard on the run-lifecycle invariants."""
    seeds = _run_fuzz(tmp_path, n_walks=3, n_steps=22, base_seed=1_000)
    assert len(seeds) == 3


@pytest.mark.slow
def test_state_fuzz_walks(tmp_path):
    """The full seeded random-walk fuzz (sized well under the 60 s per-test cap)."""
    seeds = _run_fuzz(tmp_path, n_walks=30, n_steps=40, base_seed=20_260_712)
    assert len(seeds) == 30


# --------------------------------------------------------------------------- #
# deterministic strong checks for invariant (d): abort always accepted         #
# --------------------------------------------------------------------------- #
def test_abort_from_paused_reaches_aborted(tmp_path):
    dm, ctrl, sm = _make_env(tmp_path / "abort_paused")
    try:
        for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
                   AppState.READY):
            sm.transition(st)
        ctrl.start_plan(_midpause_plan(), _limits(), AutoConfirmGate())
        assert _wait_state(sm, AppState.PAUSED), "run should park in PAUSED"
        ctrl.abort()
        ctrl._thread.join(timeout=_JOIN_TIMEOUT)
        assert not ctrl._thread.is_alive()
        assert sm.state is AppState.ABORTED
        assert ctrl._hv_armed is False
        assert ctrl.last_run_path is not None and ctrl.last_run_path.exists()
        assert ctrl._writer._file is None            # never half-open
    finally:
        dm.disconnect_all()


def test_abort_from_running_reaches_aborted(tmp_path):
    dm, ctrl, sm = _make_env(tmp_path / "abort_running")
    try:
        for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
                   AppState.READY):
            sm.transition(st)
        ctrl.start_plan(_wait_plan(2.0), _limits(), AutoConfirmGate())
        assert _wait_state(sm, AppState.RUNNING)
        ctrl.abort()                                  # abort inside the WaitStep
        ctrl._thread.join(timeout=_JOIN_TIMEOUT)
        assert not ctrl._thread.is_alive()
        assert sm.state is AppState.ABORTED
        assert ctrl._writer._file is None
    finally:
        dm.disconnect_all()


# --------------------------------------------------------------------------- #
# FOUND BUG (reported to Adam): start_plan() is not refused while a run is      #
# already PAUSED.  can(RUNNING) is True from PAUSED (the resume edge), and      #
# start_plan guards ONLY on can(RUNNING) — it does not check for a live worker  #
# thread.  So starting a plan while one is paused unblocks the parked worker    #
# AND spawns a SECOND concurrent _run_plan thread, both sharing _writer /       #
# _abort_event / _hv_armed.  This test asserts the DESIRED behavior (refuse, or #
# at least no second worker) and is xfail(strict=False) so the suite stays      #
# green and flips to xpass the moment start_plan grows a live-run guard.        #
# --------------------------------------------------------------------------- #
@pytest.mark.xfail(reason="start_plan not refused while a run is PAUSED — spawns "
                          "a 2nd worker thread (reported to Adam)",
                   strict=False)
def test_start_while_paused_is_refused(tmp_path):
    dm, ctrl, sm = _make_env(tmp_path / "start_while_paused")
    try:
        for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
                   AppState.READY):
            sm.transition(st)
        ctrl.start_plan(_midpause_plan(), _limits(), AutoConfirmGate())
        assert _wait_state(sm, AppState.PAUSED)
        first = ctrl._thread
        try:
            ctrl.start_plan(_stage_plan([1.0]), _limits(), AutoConfirmGate())
        except RuntimeError:
            return  # desired: refused → xpass
        # Not refused: a second worker must NOT have been launched.
        assert ctrl._thread is first, "a second concurrent worker was spawned"
    finally:
        ctrl.abort()
        if ctrl._thread is not None:
            ctrl._thread.join(timeout=_JOIN_TIMEOUT)
        dm.disconnect_all()
