"""Headless tests for gui.sequence_coordinator.SequenceCoordinator.

The coordinator is the Qt-side driver of the Scan Sequencer (the unattended
overnight routine queue).  These tests prove its contract against a
deterministic ``FakeScanCoordinator`` that models exactly the seam the real
``gui.scan_coordinator.ScanCoordinator`` exposes — the ``plan_finished`` /
``plan_error`` post-settle terminals, ``plan_run_active``, ``execute_plan`` and
``abort`` — plus the REAL ``SequenceRunner`` engine, the REAL
``StateMachine`` and the REAL combined ``ArmedEnvelope`` derivation.  A fake is
used (not a live background ScanController) so every advance, halt and abort is
deterministic; the coordinator itself is exercised end-to-end.

Idiom follows tests/test_scan_coordinator.py: ``QT_QPA_PLATFORM=offscreen``, a
shared ``QApplication.instance()``, no pytest-qt.  ``park_safe`` is an injected
spy (the coordinator's chosen seam), so no real HV ramp runs and the tests are
instant.

Covered
-------
* 2-entry end-to-end: both DONE, park between entries AND at the end,
  sequence_finished("finished"), sequence_active True→False.
* entry-1 error → entry 1 FAILED, entry 2 SKIPPED, parked, halted, active False.
* deny/compliance abort (state ABORTED) → "aborted" audit word maps from state.
* abort_sequence mid-run → runner CANCELLED, scan.abort called, parked, cancelled.
* idle-between-entries abort still parks + emits; not-active abort is a no-op.
* deep-copy snapshot isolation (req 3).
* gate privacy: no public ``gate`` attribute; passed only to execute_plan (req 1).
* sequence_active(bool) emission order pinned (True at arm; False before finished).
* FSM recovery: FINISHED→CONFIGURED→READY before the next entry's execute_plan.
* fail-closed on an engine raise never leaves sequence_active dangling True.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from controller.arm_envelope import ArmedEnvelope, ArmedEnvelopeGate
from controller.scan_plan import (
    ActionBlock, ActionType, Axis, LoopBlock, ScanPlan,
)
from controller.sequencer import EntryState
from controller.state_machine import AppState, StateMachine
from gui.sequence_coordinator import SequenceCoordinator


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class Spy:
    """Records every emission of a Qt signal as a tuple of its arguments."""

    def __init__(self, signal) -> None:
        self.calls: list = []
        signal.connect(lambda *a: self.calls.append(a))

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def last(self):
        return self.calls[-1]


class ParkSpy:
    """An injectable park_safe callable that counts calls (and optionally logs
    into a shared ordered event list to prove interleaving with execute_plan)."""

    def __init__(self, log: list | None = None) -> None:
        self.calls = 0
        self._log = log

    def __call__(self) -> None:
        self.calls += 1
        if self._log is not None:
            self._log.append("park")


class FakeScanCoordinator(QObject):
    """Deterministic stand-in for gui.scan_coordinator.ScanCoordinator.

    Exposes exactly the seam SequenceCoordinator depends on.  ``execute_plan``
    mimics a real start (READY→RUNNING via the shared state machine, run becomes
    active); the ``*_run`` test drivers simulate the post-settle terminal the
    real coordinator emits (state already settled, THEN the signal), so the
    error/aborted audit mapping is exercised deterministically.
    """

    plan_finished = Signal()
    plan_error = Signal(str)

    def __init__(self, sm: StateMachine, refuse: bool = False,
                 log: list | None = None) -> None:
        super().__init__()
        self._sm = sm
        self._active = False
        self._refuse = refuse
        self._log = log
        self.execute_calls: list = []   # (plan, gate, state_at_call)
        self.abort_calls = 0

    @property
    def plan_run_active(self) -> bool:
        return self._active

    def execute_plan(self, plan, gate) -> None:
        if self._log is not None:
            self._log.append(("exec", plan.name))
        self.execute_calls.append((plan, gate, self._sm.state))
        if self._refuse:
            return                      # never starts → plan_run_active stays False
        self._sm.transition(AppState.RUNNING)   # real start transitions internally
        self._active = True

    def abort(self) -> None:
        self.abort_calls += 1

    # -- test drivers: simulate the post-settle terminal --------------------
    def finish_run(self) -> None:
        self._sm.transition(AppState.FINISHED)
        self._active = False
        self.plan_finished.emit()

    def error_run(self, msg: str = "sim fault") -> None:
        self._sm.transition(AppState.ERROR)
        self._active = False
        self.plan_error.emit(msg)

    def gate_abort_run(self, msg: str = "denied by envelope gate") -> None:
        self._sm.transition(AppState.ABORTED)
        self._active = False
        self.plan_error.emit(msg)


def _ready_sm() -> StateMachine:
    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
               AppState.READY):
        sm.transition(st)
    return sm


def _plan(name: str, values=(0.0, 1.0)) -> ScanPlan:
    """An x-only stage raster: acquire + save at each x.  No bias → no HV arm."""
    loop = LoopBlock(
        axis=Axis.STAGE_X,
        values=[float(v) for v in values],
        children=[
            ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={}),
            ActionBlock(action=ActionType.SAVE_POINT, params={}),
        ],
    )
    return ScanPlan(name=name, root=[loop])


def _pause_plan(name: str) -> ScanPlan:
    """A plan whose compiled step list contains a manual_pause (human-gated)
    step — fundamentally incompatible with an unattended queue (Mary A5.2a)."""
    loop = LoopBlock(
        axis=Axis.STAGE_X,
        values=[0.0, 1.0],
        children=[
            ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={}),
            ActionBlock(action=ActionType.MANUAL_PAUSE,
                        params={"prompt": "change the laser filter"}),
            ActionBlock(action=ActionType.SAVE_POINT, params={}),
        ],
    )
    return ScanPlan(name=name, root=[loop])


def _setup(n: int = 2, refuse: bool = False, log: list | None = None):
    """``(coord, fake, sm, park)`` — n entries loaded + gate built, READY."""
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm, refuse=refuse, log=log)
    park = ParkSpy(log=log)
    coord = SequenceCoordinator(fake, sm, park_safe=park)
    coord.load([(f"r{i}", _plan(f"r{i}")) for i in range(n)])
    coord.build_gate(channel=0)
    return coord, fake, sm, park


# --------------------------------------------------------------------------- #
# (1) 2-entry queue end-to-end: both DONE, park between + at end               #
# --------------------------------------------------------------------------- #
def test_two_entry_end_to_end_finishes():
    log: list = []
    coord, fake, sm, park = _setup(2, log=log)
    active = Spy(coord.sequence_active)
    finished = Spy(coord.sequence_finished)

    coord.arm_and_start()
    # park BEFORE entry 0, then entry 0 executes.
    assert log == ["park", ("exec", "r0")]
    fake.finish_run()
    # park BETWEEN entries, then entry 1 executes.
    assert log == ["park", ("exec", "r0"), "park", ("exec", "r1")]
    fake.finish_run()
    # a final park, then the queue finishes.
    assert log == ["park", ("exec", "r0"), "park", ("exec", "r1"), "park"]

    assert [e.state for e in coord._runner.entries] == [EntryState.DONE,
                                                        EntryState.DONE]
    assert finished.last == ("finished",)
    assert active.calls == [(True,), (False,)]
    assert coord.is_active is False
    assert park.calls == 3


# --------------------------------------------------------------------------- #
# (2) entry 1 errors → FAILED + remainder SKIPPED + halted                     #
# --------------------------------------------------------------------------- #
def test_entry_one_error_halts_and_skips_remainder():
    coord, fake, sm, park = _setup(2)
    active = Spy(coord.sequence_active)
    finished = Spy(coord.sequence_finished)

    coord.arm_and_start()
    fake.error_run("boom")              # entry 0 → ERROR

    assert coord._runner.entries[0].state is EntryState.FAILED
    assert coord._runner.entries[1].state is EntryState.SKIPPED
    assert len(fake.execute_calls) == 1  # entry 1 never ran
    assert finished.last == ("halted",)
    assert active.calls == [(True,), (False,)]
    assert coord.is_active is False
    # park before entry 0 + a final park after the halt.
    assert park.calls == 2


# --------------------------------------------------------------------------- #
# (2b) a deny/compliance abort (state ABORTED) maps to the "aborted" word      #
# --------------------------------------------------------------------------- #
def test_gate_abort_maps_state_to_aborted_word():
    coord, fake, sm, park = _setup(2)
    finished = Spy(coord.sequence_finished)

    coord.arm_and_start()
    fake.gate_abort_run("denied")       # entry 0 → ABORTED (not ERROR)

    assert coord._runner.entries[0].state is EntryState.FAILED
    assert "aborted" in coord._runner.entries[0].message   # audit word from state
    assert coord._runner.entries[1].state is EntryState.SKIPPED
    assert finished.last == ("halted",)


# --------------------------------------------------------------------------- #
# (3) abort_sequence mid-run: CANCELLED rows, scan aborted, parked, active off  #
# --------------------------------------------------------------------------- #
def test_abort_sequence_mid_run():
    coord, fake, sm, park = _setup(2)
    active = Spy(coord.sequence_active)
    finished = Spy(coord.sequence_finished)

    coord.arm_and_start()               # entry 0 running
    park_before = park.calls
    coord.abort_sequence()

    assert fake.abort_calls == 1                       # live run aborted
    assert [e.state for e in coord._runner.entries] == [EntryState.CANCELLED,
                                                        EntryState.CANCELLED]
    assert park.calls > park_before                    # parked on abort
    assert finished.last == ("cancelled",)
    assert active.calls == [(True,), (False,)]
    assert coord.is_active is False

    # A stray late terminal (a real controller settles ABORTED after abort) must
    # be ignored — no double-finish, no dangling state.
    n_fin = finished.count
    fake.plan_finished.emit()
    fake.plan_error.emit("late")
    assert finished.count == n_fin


def test_abort_idle_between_entries_still_parks_and_emits():
    coord, fake, sm, park = _setup(2)
    active = Spy(coord.sequence_active)
    finished = Spy(coord.sequence_finished)

    coord.arm_and_start()
    # Force the transient "active, no run in flight" point.
    coord._entry_in_flight = False
    fake._active = False
    park_before = park.calls

    coord.abort_sequence()

    assert fake.abort_calls == 0                # no live run to abort
    assert park.calls > park_before             # parked anyway
    assert finished.last == ("cancelled",)
    assert active.calls[-1] == (False,)
    assert coord._runner.entries[0].state is EntryState.CANCELLED


def test_abort_when_not_active_is_noop():
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    park = ParkSpy()
    coord = SequenceCoordinator(fake, sm, park_safe=park)
    active = Spy(coord.sequence_active)
    finished = Spy(coord.sequence_finished)

    coord.abort_sequence()              # nothing loaded / armed

    assert active.count == 0
    assert finished.count == 0
    assert park.calls == 0              # must not touch hardware / a manual run


# --------------------------------------------------------------------------- #
# (4) deep-copy snapshot isolation (Mary req 3)                                #
# --------------------------------------------------------------------------- #
def test_load_deep_copies_plans_so_source_edits_do_not_alias():
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=lambda: None)

    src = _plan("r0", values=(0.0, 1.0))
    coord.load([("r0", src)])

    # Mutate the SOURCE plan AFTER load — by name, by loop values, structurally.
    src.name = "MUTATED"
    src.root[0].values = [999.0]
    src.root[0].children.append(
        ActionBlock(action=ActionType.WAIT, params={"seconds": 5.0}))

    snap = coord._runner.entries[0].plan
    assert snap is not src
    assert snap.name == "r0"
    assert snap.root[0].values == [0.0, 1.0]
    assert len(snap.root[0].children) == 2   # the appended WAIT never leaked in


# --------------------------------------------------------------------------- #
# (5) gate privacy (Mary req 1): no public gate attr; passed only to execute    #
# --------------------------------------------------------------------------- #
def test_union_gate_is_private_and_passed_only_to_execute_plan():
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=lambda: None)
    coord.load([("r0", _plan("r0")), ("r1", _plan("r1"))])

    env, gate = coord.build_gate(channel=0)

    assert isinstance(env, ArmedEnvelope)
    assert isinstance(gate, ArmedEnvelopeGate)
    # The union gate is NOT reachable via any public attribute — no leak into
    # panels (manual actions stay on the app QtDangerGate).
    assert not hasattr(coord, "gate")
    assert coord._gate is gate          # stored privately

    coord.arm_and_start()
    # The exact private gate is handed to execute_plan (and nowhere else).
    assert fake.execute_calls[0][1] is gate

    # The combined envelope names every routine the single hold-3s authorizes.
    assert "r0" in env.summary and "r1" in env.summary


def test_build_gate_refuses_without_a_loaded_sequence():
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=lambda: None)
    with pytest.raises(RuntimeError):
        coord.build_gate(channel=0)


# --------------------------------------------------------------------------- #
# (6) sequence_active emission order pinned                                    #
# --------------------------------------------------------------------------- #
def test_sequence_active_emission_order_pinned():
    coord, fake, sm, park = _setup(1)
    order: list = []
    coord.sequence_active.connect(lambda b: order.append(("active", b)))
    coord.sequence_finished.connect(lambda w: order.append(("finished", w)))

    coord.arm_and_start()
    assert order == [("active", True)]          # True at arm, before any terminal

    fake.finish_run()
    # active(False) is emitted BEFORE finished(word) on every terminal path.
    assert order == [("active", True), ("active", False), ("finished", "finished")]


# --------------------------------------------------------------------------- #
# (7) FSM recovery: FINISHED→CONFIGURED→READY before the next execute_plan      #
# --------------------------------------------------------------------------- #
def test_fsm_recovered_to_ready_between_entries():
    _app()
    sm = _ready_sm()
    transitions: list = []
    sm.add_callback(lambda old, new: transitions.append((old, new)))
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=lambda: None)
    coord.load([("r0", _plan("r0")), ("r1", _plan("r1"))])
    coord.build_gate(channel=0)

    coord.arm_and_start()
    assert fake.execute_calls[0][2] is AppState.READY   # entry 0 ran from READY
    fake.finish_run()                                    # RUNNING→FINISHED

    # entry 1 ran from READY, reached only via FINISHED→CONFIGURED→READY.
    assert fake.execute_calls[1][2] is AppState.READY
    assert (AppState.FINISHED, AppState.CONFIGURED) in transitions
    assert (AppState.CONFIGURED, AppState.READY) in transitions


# --------------------------------------------------------------------------- #
# (8) fail-closed: an engine raise never leaves sequence_active dangling True   #
# --------------------------------------------------------------------------- #
def test_engine_raise_fails_closed_without_dangling_active(monkeypatch):
    coord, fake, sm, park = _setup(2)
    err = Spy(coord.sequence_error)
    active = Spy(coord.sequence_active)
    finished = Spy(coord.sequence_finished)

    coord.arm_and_start()
    # Force record_outcome to raise (models an engine fault / lost race).
    def _boom(*_a, **_k):
        raise RuntimeError("engine boom")
    monkeypatch.setattr(coord._runner, "record_outcome", _boom)

    fake.finish_run()

    assert err.count == 1
    assert coord.is_active is False              # NEVER left dangling True
    assert active.calls[-1] == (False,)
    assert finished.last == ("error",)
    assert park.calls >= 1


def test_execute_plan_refusal_halts_fail_closed():
    # A refused execute_plan (plan_run_active stays False) must not hang the
    # queue waiting for a terminal that will never arrive — it halts fail-closed.
    coord, fake, sm, park = _setup(2, refuse=True)
    active = Spy(coord.sequence_active)
    finished = Spy(coord.sequence_finished)

    coord.arm_and_start()

    assert coord._runner.entries[0].state is EntryState.FAILED
    assert coord._runner.entries[1].state is EntryState.SKIPPED
    assert finished.last == ("halted",)
    assert active.calls == [(True,), (False,)]
    assert coord.is_active is False


# --------------------------------------------------------------------------- #
# (9) load refused while a sequence is active                                  #
# --------------------------------------------------------------------------- #
def test_load_refused_while_active():
    coord, fake, sm, park = _setup(2)
    coord.arm_and_start()
    with pytest.raises(RuntimeError):
        coord.load([("x", _plan("x"))])


def test_arm_refused_when_plan_run_already_active():
    coord, fake, sm, park = _setup(2)
    fake._active = True                 # a plan run is already live
    with pytest.raises(RuntimeError):
        coord.arm_and_start()


def test_arm_refused_without_a_built_gate():
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=lambda: None)
    coord.load([("r0", _plan("r0"))])
    with pytest.raises(RuntimeError):   # build_gate() was never called
        coord.arm_and_start()


# --------------------------------------------------------------------------- #
# (9b) fail-closed load: a manual_pause plan is rejected, nothing half-built   #
# (Mary A5.2a) — the panel surfaces the raised reason; the queue is not dropped #
# --------------------------------------------------------------------------- #
def test_load_rejects_manual_pause_plan_fail_closed():
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=lambda: None)
    rows = Spy(coord.entry_state_changed)
    progress = Spy(coord.sequence_progress)
    active = Spy(coord.sequence_active)

    with pytest.raises(ValueError) as ei:
        coord.load([("clean", _plan("clean")),
                    ("night_shift", _pause_plan("night_shift"))])
    msg = str(ei.value)
    assert "night_shift" in msg          # names the offending routine
    assert "manual_pause" in msg

    # Fail-closed: nothing built, no state mutated, no signal emitted, idle.
    assert coord._runner is None
    assert coord._entries == []
    assert rows.count == 0
    assert progress.count == 0
    assert active.count == 0
    assert coord.is_active is False


# --------------------------------------------------------------------------- #
# (10) progress + entry-row signals track the run                              #
# --------------------------------------------------------------------------- #
def test_progress_and_rows_emitted():
    coord, fake, sm, park = _setup(2)
    progress = Spy(coord.sequence_progress)
    rows = Spy(coord.entry_state_changed)

    coord.arm_and_start()
    fake.finish_run()
    fake.finish_run()

    assert progress.last == (2, 2)                 # both entries terminal
    # rows carry (index, EntryState value, message); a DONE row is eventually seen.
    assert any(c[1] == EntryState.DONE.value for c in rows.calls)
