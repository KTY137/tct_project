"""Direct unit tests for ``gui.sequencer_viewmodel.SequencerQueueViewModel`` —
the read-only queue/run mirror + source-queue data model half of the Scan
Sequencer split (``docs/design/u1_staging.md`` §5; QML-migration beat U1.3).

Reclaimed C→B/D from ``tests/test_sequencer_panel.py``: the six (a)-class tests
that pinned queue / run / envelope MODEL behavior move here and construct the VM
directly (no widget), fed — for the run-state rows — by a REAL
``SequenceCoordinator`` driven by a deterministic ``FakeScanCoordinator`` (the
panel test's seam idiom, ``tests/test_sequence_coordinator.py``), so the
*integration* semantics stay pinned, not just setter/getter behavior
(u1_staging §5.4).  Two of the six —
``test_arm_text_contains_every_routine_hv_and_travel`` and
``test_queue_edit_rederives_envelope_no_stale`` — are S2-manifest rows: their
assertions move host verbatim, never weaken.

Also carries the replicated standing-law pair (S2 Ruling Q3, modeled 1:1 on
``tests/test_run_state_viewmodel.py``): a viewmodel exposes NO run-control
callable, holds NO coordinator/state-machine/gate reference, and owns no
timer/thread — the structural read/command boundary that encodes hardware-safety
rule 2.

Idiom: ``QT_QPA_PLATFORM=offscreen``, a bare ``QCoreApplication`` (no widgets,
no QML engine — a plain ``QObject`` subtype), no pytest-qt.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QObject, Signal

from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.sequencer import SequenceEntry
from controller.state_machine import AppState, StateMachine
from gui.sequence_coordinator import SequenceCoordinator
from gui.sequencer_viewmodel import SequencerQueueViewModel
from tests._viewmodel_standing_law import (
    assert_no_command_surface,
    assert_owns_no_timer_or_thread,
)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


# --------------------------------------------------------------------------- #
# Deterministic run seam (the FakeScanCoordinator idiom of                     #
# tests/test_sequencer_panel.py / test_sequence_coordinator.py)                #
# --------------------------------------------------------------------------- #
class FakeScanCoordinator(QObject):
    """Deterministic stand-in for gui.scan_coordinator.ScanCoordinator — exactly
    the seam SequenceCoordinator consumes."""

    plan_finished = Signal()
    plan_error = Signal(str)

    def __init__(self, sm: StateMachine) -> None:
        super().__init__()
        self._sm = sm
        self._active = False
        self.execute_calls: list = []
        self.abort_calls = 0

    @property
    def plan_run_active(self) -> bool:
        return self._active

    def execute_plan(self, plan, gate) -> None:
        self.execute_calls.append((plan, gate))
        self._sm.transition(AppState.RUNNING)
        self._active = True

    def abort(self) -> None:
        self.abort_calls += 1

    def finish_run(self) -> None:
        self._sm.transition(AppState.FINISHED)
        self._active = False
        self.plan_finished.emit()

    def error_run(self, msg: str = "boom") -> None:
        self._sm.transition(AppState.ERROR)
        self._active = False
        self.plan_error.emit(msg)


class ParkSpy:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


def _ready_sm() -> StateMachine:
    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED,
               AppState.READY):
        sm.transition(st)
    return sm


def _plan(name: str, values=(0.0, 1.0)) -> ScanPlan:
    """An x-only stage raster (no bias → no HV in the envelope)."""
    loop = LoopBlock(
        axis=Axis.STAGE_X,
        values=[float(v) for v in values],
        children=[
            ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={}),
            ActionBlock(action=ActionType.SAVE_POINT, params={}),
        ],
    )
    return ScanPlan(name=name, root=[loop])


def _bias_motion_plan(name: str, hv: float = -300.0, travel=(-2.0, 2.0)) -> ScanPlan:
    """A bias → x plan so the combined envelope carries a real HV range + travel."""
    acquire = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={})
    save = ActionBlock(action=ActionType.SAVE_POINT, params={})
    x_loop = LoopBlock(axis=Axis.STAGE_X, values=[float(travel[0]), float(travel[1])],
                       children=[acquire, save])
    bias_loop = LoopBlock(axis=Axis.BIAS_V, values=[0.0, float(hv)], children=[x_loop])
    return ScanPlan(name=name, root=[bias_loop],
                    safety={"require_hv_confirmation": True})


def _wire_host(vm: SequencerQueueViewModel, coord: SequenceCoordinator,
               channel: int = 0):
    """Play the ``SequencerPanel`` host role (u1_staging §5.3): the HOST makes
    EVERY connection — the coordinator's terminals feed the VM mirror, and a
    queue edit (``queue_changed``) re-syncs the coordinator + re-feeds the
    freshly-derived envelope summary.  The VM itself never sees the coordinator or
    the gate — the gate built here is discarded (host-private)."""
    coord.entry_state_changed.connect(vm.on_entry_state)
    coord.sequence_progress.connect(vm.on_progress)
    coord.sequence_finished.connect(vm.on_finished)
    coord.sequence_error.connect(vm.on_error)
    coord.sequence_active.connect(vm.on_active)

    def _sync() -> None:
        coord.load(vm.named_plans, source_paths=vm.source_paths)
        if vm.count:
            env, _gate = coord.build_gate(channel)   # gate stays host-side
            vm.set_envelope_summary(env.summary)
        else:
            vm.set_envelope_summary("")

    vm.queue_changed.connect(_sync)
    return _sync


def _harness(entries=()):
    """``(vm, coord, fake, sm, park, sync)`` — a VM fed by a real coordinator.

    *entries* is an iterable of ``(name, plan, source_path)`` — appended straight
    onto the VM queue (the panel-harness idiom) then synced once.
    """
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    park = ParkSpy()
    coord = SequenceCoordinator(fake, sm, park_safe=park)
    vm = SequencerQueueViewModel()
    sync = _wire_host(vm, coord)
    for name, plan, src in entries:
        vm._entries.append(SequenceEntry(name=name, plan=plan, source_path=src))
    if entries:
        sync()
    return vm, coord, fake, sm, park, sync


# --------------------------------------------------------------------------- #
# (0) headless default construction (per-panel qml-boot gate, u1_staging §7.4a) #
# --------------------------------------------------------------------------- #
def test_default_construction_no_parent_does_not_raise():
    _app()
    vm = SequencerQueueViewModel(parent=None)
    assert isinstance(vm, SequencerQueueViewModel)
    assert vm.count == 0
    assert vm.active is False
    assert vm.done == 0 and vm.total == 0
    assert vm.rows == []
    assert vm.envelopeSummary == ""
    assert vm.outcomeWord == ""
    assert vm.lastError == ""
    assert vm.named_plans == [] and vm.source_paths == []


# --------------------------------------------------------------------------- #
# (1) arm text names EVERY routine + max-HV + travel (S2-manifest reclaim)      #
# --------------------------------------------------------------------------- #
def test_arm_text_contains_every_routine_hv_and_travel():
    vm, *_ = _harness([
        ("cce_v_map", _bias_motion_plan("cce_v_map", hv=-150.0, travel=(-1.0, 1.0)), None),
        ("charge_map", _bias_motion_plan("charge_map", hv=-300.0, travel=(-2.0, 2.0)), None),
    ])
    summary = vm.envelopeSummary
    assert "cce_v_map" in summary and "charge_map" in summary     # every routine
    assert "-300" in summary                                      # max-HV figure
    assert "-2..2 mm" in summary                                  # travel figure


# --------------------------------------------------------------------------- #
# (2) a queue edit re-derives the envelope (a stale summary is impossible)      #
#     — S2-manifest reclaim; the edit rides the VM's real add_routine data API.  #
# --------------------------------------------------------------------------- #
def test_queue_edit_rederives_envelope_no_stale(tmp_path):
    vm, *_ = _harness([("r0", _bias_motion_plan("r0", hv=-100.0), None)])
    s1 = vm.envelopeSummary
    assert "r0" in s1 and "-100" in s1 and "r1" not in s1

    # A genuine queue edit through the VM's data API: add_routine → queue_changed
    # → the host re-syncs + re-feeds the freshly-derived summary (no stale text).
    r1_path = tmp_path / "r1.yaml"
    _bias_motion_plan("r1", hv=-300.0).save_yaml(str(r1_path))
    assert vm.add_routine(str(r1_path)) is True

    s2 = vm.envelopeSummary
    assert s2 != s1
    assert "r1" in s2 and "-300" in s2       # widened + names the new routine


# --------------------------------------------------------------------------- #
# (3) rows track entry_state_changed through real coordinator advances          #
# --------------------------------------------------------------------------- #
def test_rows_track_running_and_done_states():
    vm, coord, fake, *_ = _harness([("r0", _plan("r0"), None),
                                    ("r1", _plan("r1"), None)])
    coord.arm_and_start()
    assert vm.rows[0][:2] == ("RUNNING", "busy")
    assert vm.rows[1][:2] == ("PENDING", "neutral")

    fake.finish_run()                       # entry 0 DONE, entry 1 RUNNING
    assert vm.rows[0][:2] == ("DONE", "neutral")       # quiet, NOT green
    assert vm.rows[1][:2] == ("RUNNING", "busy")

    fake.finish_run()                       # entry 1 DONE
    assert vm.rows[1][:2] == ("DONE", "neutral")


def test_rows_track_failed_and_skipped_states():
    vm, coord, fake, *_ = _harness([("r0", _plan("r0"), None),
                                    ("r1", _plan("r1"), None)])
    coord.arm_and_start()
    fake.error_run("fault")                 # entry 0 ERROR → FAILED, entry 1 SKIPPED
    assert vm.rows[0][:2] == ("FAILED", "crit")        # the only red row
    assert vm.rows[1][:2] == ("SKIPPED", "neutral")    # neutral, not red


# --------------------------------------------------------------------------- #
# (4) save / load the whole queue round-trips through the VM persistence API     #
# --------------------------------------------------------------------------- #
def test_save_load_queue_round_trip(tmp_path):
    vm, *_ = _harness([
        ("r0", _bias_motion_plan("r0"), None),
        ("r1", _plan("r1"), None),
    ])
    path = tmp_path / "night_run.yaml"
    assert vm.save(str(path)) is True
    assert path.exists()

    vm2, *_ = _harness()
    assert vm2.load(str(path)) is True
    assert [e.name for e in vm2._entries] == ["r0", "r1"]
    assert vm2.count == 2
    assert vm2.rows[0][:2] == ("PENDING", "neutral")   # a loaded queue is fresh
    # The plan snapshot round-tripped (bias loop preserved on r0) and the loaded
    # queue re-derived its combined envelope through the host sync.
    assert "r0" in vm2.envelopeSummary


# --------------------------------------------------------------------------- #
# (5) a fail-closed loader error surfaces + leaves the queue untouched          #
# --------------------------------------------------------------------------- #
def test_loader_error_surfaces_and_preserves_queue(tmp_path):
    vm, *_ = _harness([("keep_me", _plan("keep_me"), None)])
    errors: list = []
    vm.load_error.connect(errors.append)

    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 999\nentries: []\n", encoding="utf-8")   # unsupported
    assert vm.load(str(bad)) is False

    assert errors and "999" in errors[-1]                    # reason surfaced
    assert [e.name for e in vm._entries] == ["keep_me"]      # never shortened


# --------------------------------------------------------------------------- #
# (6) edits refuse while a run is active (queue immutable during a sequence)     #
# --------------------------------------------------------------------------- #
def test_edits_refuse_while_active():
    vm, coord, fake, *_ = _harness([("r0", _plan("r0"), None),
                                    ("r1", _plan("r1"), None)])
    coord.arm_and_start()
    assert vm.active is True
    # every source-queue mutator is a no-op while a run drives the queue
    assert vm.remove(0) is False
    assert vm.move(0, 1) is False
    assert vm.count == 2                     # queue untouched
    fake.error_run("fault")                  # terminal → active clears
    assert vm.active is False


# --------------------------------------------------------------------------- #
# (7) NOTIFY fires per feed (the single changed NOTIFY the host repaints off)    #
# --------------------------------------------------------------------------- #
def test_changed_notify_fires_per_feed():
    _app()
    vm = SequencerQueueViewModel()
    vm._entries.append(SequenceEntry(name="r0", plan=_plan("r0")))  # so row 0 exists
    fired = {"n": 0}
    vm.changed.connect(lambda: fired.__setitem__("n", fired["n"] + 1))
    vm.on_progress(1, 4)
    vm.on_active(True)
    vm.on_entry_state(0, "running", "")      # row 0 exists → updates + notifies
    vm.on_finished("finished")
    vm.on_error("boom")
    vm.set_envelope_summary("HV -300..0 V")
    assert fired["n"] == 6


# --------------------------------------------------------------------------- #
# (8) SAFETY-CRITICAL: no command surface, no upward reference (§1.2 boundary)   #
# --------------------------------------------------------------------------- #
def test_read_only_no_command_surface():
    """The queue viewmodel is a mirror + data model, not a remote. It must expose
    NO run-control callable (queue editing is DATA — it arms nothing; the
    coordinator's load()-refuses-while-active is the enforcing gate) and hold NO
    reference through which QML could issue a command — the structural
    read/command boundary that encodes hardware-safety rule 2."""
    _app()
    vm = SequencerQueueViewModel()
    assert_no_command_surface(
        vm,
        extra_names=("execute", "arm"),
        extra_attrs=("_scan",),
        extra_types=("SequenceCoordinator", "ArmedEnvelopeGate"),
    )


# --------------------------------------------------------------------------- #
# (9) Owns no timer / no thread (single-timer law)                              #
# --------------------------------------------------------------------------- #
def test_owns_no_timer_no_thread():
    _app()
    vm = SequencerQueueViewModel()
    assert_owns_no_timer_or_thread(vm)
