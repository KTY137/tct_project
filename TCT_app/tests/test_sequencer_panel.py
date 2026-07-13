"""Headless tests for gui.sequencer_panel.SequencerPanel and its tct_gui wiring.

The panel is the operator face of the unattended Scan Sequencer.  These tests
exercise it against the REAL ``SequenceCoordinator`` engine driven by a
deterministic ``FakeScanCoordinator`` (the same seam idiom as
tests/test_sequence_coordinator.py), plus the REAL ``StateMachine`` and combined
``ArmedEnvelope`` derivation — so every queue edit, arm-text render, row update
and abort is deterministic and instant (``park_safe`` is an injected spy).

The two BINDING safety seams that live in ``tct_gui`` (not the panel) are pinned
here too, via the unbound-method-on-a-fake-``self`` idiom
tests/test_bias_trip_visibility.py already uses:

* req 2 — ``sequence_active`` locks the manual HV/motion danger panels and
  UNCONDITIONALLY re-enables at every terminal (including a failure path);
* req 3 — the coordinator's modal error/warn shims reroute to the non-blocking
  status bus while a sequence runs and restore afterwards.

Idiom: ``QT_QPA_PLATFORM=offscreen``, a shared ``QApplication.instance()``, no
pytest-qt.
"""
from __future__ import annotations

import inspect
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.sequencer import (
    EntryState, SequenceEntry, load_sequence_yaml, save_sequence_yaml,
)
from controller.state_machine import AppState, StateMachine
from gui.sequence_coordinator import SequenceCoordinator
from gui.sequencer_panel import _COL_STATE, SequencerPanel


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class FakeScanCoordinator(QObject):
    """Deterministic stand-in for gui.scan_coordinator.ScanCoordinator — exactly
    the seam SequenceCoordinator consumes (see test_sequence_coordinator.py)."""

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


class EnableSpy:
    """A stand-in danger panel that records its enabled state (Qt-compatible)."""

    def __init__(self) -> None:
        self.enabled = True

    def setEnabled(self, value: bool) -> None:  # noqa: N802 - Qt signature
        self.enabled = bool(value)

    def isEnabled(self) -> bool:  # noqa: N802 - Qt signature
        return self.enabled


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


def _harness(entries=()):
    """``(panel, coord, fake, sm, park)`` — a panel wired to a real coordinator.

    *entries* is an iterable of ``(name, plan, source_path)``.
    """
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    park = ParkSpy()
    coord = SequenceCoordinator(fake, sm, park_safe=park)
    panel = SequencerPanel(coord, channel_provider=lambda: 0)
    for name, plan, src in entries:
        panel._entries.append(SequenceEntry(name=name, plan=plan, source_path=src))
    if entries:
        panel._sync_coordinator()
    return panel, coord, fake, sm, park


def _chip(panel: SequencerPanel, row: int):
    return panel._table.cellWidget(row, _COL_STATE)


# --------------------------------------------------------------------------- #
# (0) headless construction + theme switch (non-negotiable smoke test)         #
# --------------------------------------------------------------------------- #
def test_panel_constructs_and_theme_switches():
    panel, _coord, *_ = _harness([("r0", _bias_motion_plan("r0"), None)])
    # Both themes render the envelope from tokens (the danger HV span differs).
    panel.refresh_theme("dark")
    dark_html = panel._envelope_html(panel._env)
    panel.refresh_theme("light")
    light_html = panel._envelope_html(panel._env)
    assert dark_html and light_html
    assert dark_html != light_html          # danger token is theme-specific
    panel.shutdown()                        # idempotent teardown


# --------------------------------------------------------------------------- #
# (1) arm text names EVERY routine + max-HV + travel                           #
# --------------------------------------------------------------------------- #
def test_arm_text_contains_every_routine_hv_and_travel():
    panel, *_ = _harness([
        ("cce_v_map", _bias_motion_plan("cce_v_map", hv=-150.0, travel=(-1.0, 1.0)), None),
        ("charge_map", _bias_motion_plan("charge_map", hv=-300.0, travel=(-2.0, 2.0)), None),
    ])
    summary = panel._env.summary
    assert "cce_v_map" in summary and "charge_map" in summary     # every routine
    assert "-300" in summary                                      # max-HV figure
    assert "-2..2 mm" in summary                                  # travel figure
    # The rendered latch text carries the same content (HV span does not drop it).
    latch_html = panel._latch._envelope_lbl.text()
    assert "cce_v_map" in latch_html and "-300" in latch_html


# --------------------------------------------------------------------------- #
# (2) a queue edit re-derives the envelope (a stale summary is impossible)     #
# --------------------------------------------------------------------------- #
def test_queue_edit_rederives_envelope_no_stale():
    panel, *_ = _harness([("r0", _bias_motion_plan("r0", hv=-100.0), None)])
    s1 = panel._env.summary
    assert "r0" in s1 and "-100" in s1 and "r1" not in s1

    panel._entries.append(
        SequenceEntry(name="r1", plan=_bias_motion_plan("r1", hv=-300.0),
                      source_path=None))
    panel._sync_coordinator()

    s2 = panel._env.summary
    assert s2 != s1
    assert "r1" in s2 and "-300" in s2       # widened + names the new routine


# --------------------------------------------------------------------------- #
# (3) abort button → coordinator.abort_sequence (always live while active)      #
# --------------------------------------------------------------------------- #
def test_abort_button_calls_abort_sequence(monkeypatch):
    panel, coord, fake, *_ = _harness([("r0", _plan("r0"), None),
                                       ("r1", _plan("r1"), None)])
    assert panel._btn_abort.isEnabled() is False     # nothing to abort yet

    coord.arm_and_start()
    assert panel._btn_abort.isEnabled() is True       # live while a sequence runs

    calls: list = []
    monkeypatch.setattr(coord, "abort_sequence", lambda: calls.append(True))
    panel._btn_abort.click()
    assert calls == [True]


# --------------------------------------------------------------------------- #
# (4) rows track entry_state_changed with ladder-correct classes               #
# --------------------------------------------------------------------------- #
def test_rows_track_running_and_done_states():
    panel, coord, fake, *_ = _harness([("r0", _plan("r0"), None),
                                       ("r1", _plan("r1"), None)])
    coord.arm_and_start()
    assert _chip(panel, 0).text() == "RUNNING"
    assert _chip(panel, 0).property("state") == "busy"
    assert _chip(panel, 1).text() == "PENDING"
    assert _chip(panel, 1).property("state") == "neutral"

    fake.finish_run()                       # entry 0 DONE, entry 1 RUNNING
    assert _chip(panel, 0).text() == "DONE"
    assert _chip(panel, 0).property("state") == "neutral"    # quiet, NOT green
    assert _chip(panel, 1).text() == "RUNNING"

    fake.finish_run()                       # entry 1 DONE
    assert _chip(panel, 1).text() == "DONE"


def test_rows_track_failed_and_skipped_states():
    panel, coord, fake, *_ = _harness([("r0", _plan("r0"), None),
                                       ("r1", _plan("r1"), None)])
    coord.arm_and_start()
    fake.error_run("fault")                 # entry 0 ERROR → FAILED, entry 1 SKIPPED
    assert _chip(panel, 0).text() == "FAILED"
    assert _chip(panel, 0).property("state") == "crit"       # the only red row
    assert _chip(panel, 1).text() == "SKIPPED"
    assert _chip(panel, 1).property("state") == "neutral"    # neutral, not red


# --------------------------------------------------------------------------- #
# (5) save / load the whole queue round-trips through the panel                 #
# --------------------------------------------------------------------------- #
def test_save_load_queue_round_trip(tmp_path):
    panel, *_ = _harness([
        ("r0", _bias_motion_plan("r0"), None),
        ("r1", _plan("r1"), None),
    ])
    path = tmp_path / "night_run.yaml"
    panel._save_queue_to(str(path))
    assert path.exists()

    panel2, *_ = _harness()
    panel2._load_queue_from(str(path))
    assert [e.name for e in panel2._entries] == ["r0", "r1"]
    assert panel2._table.rowCount() == 2
    # The plan snapshot round-tripped (bias loop preserved on r0).
    assert panel2._env is not None and "r0" in panel2._env.summary


# --------------------------------------------------------------------------- #
# (6) a fail-closed loader error surfaces + leaves the queue untouched         #
# --------------------------------------------------------------------------- #
def test_loader_error_surfaces_and_preserves_queue(tmp_path, monkeypatch):
    panel, *_ = _harness([("keep_me", _plan("keep_me"), None)])
    notified: list = []
    monkeypatch.setattr("gui.sequencer_panel.notify",
                        lambda text, level="info": notified.append((text, level)))

    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 999\nentries: []\n", encoding="utf-8")   # unsupported
    panel._load_queue_from(str(bad))

    assert notified and notified[-1][1] == "error"           # reason surfaced
    assert [e.name for e in panel._entries] == ["keep_me"]   # never shortened


# --------------------------------------------------------------------------- #
# (7) req 2 — sequence_active locks/unlocks the manual danger panels           #
# --------------------------------------------------------------------------- #
def test_on_sequence_active_locks_and_unlocks_manual_danger_panels():
    from tct_gui import TCTMainWindow
    bias, motor = EnableSpy(), EnableSpy()
    main = SimpleNamespace(_sequence_active=False, _bias_panel=bias, _motor_panel=motor)

    TCTMainWindow._on_sequence_active(main, True)
    assert main._sequence_active is True
    assert bias.enabled is False and motor.enabled is False

    TCTMainWindow._on_sequence_active(main, False)
    assert main._sequence_active is False
    assert bias.enabled is True and motor.enabled is True     # unconditional


# --------------------------------------------------------------------------- #
# (8) req 2 — re-enable is unconditional even after a FAILURE path             #
# --------------------------------------------------------------------------- #
def test_manual_danger_reenables_after_failure_path():
    from tct_gui import TCTMainWindow
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=ParkSpy())
    coord.load([("r0", _plan("r0")), ("r1", _plan("r1"))])
    coord.build_gate(channel=0)

    bias, motor = EnableSpy(), EnableSpy()
    main = SimpleNamespace(_sequence_active=False, _bias_panel=bias, _motor_panel=motor)
    coord.sequence_active.connect(lambda a: TCTMainWindow._on_sequence_active(main, a))

    coord.arm_and_start()
    assert bias.enabled is False and motor.enabled is False   # locked at arm

    fake.error_run("driver fault")          # entry 0 fails → fail-closed halt
    assert main._sequence_active is False
    assert bias.enabled is True and motor.enabled is True     # re-enabled anyway


# --------------------------------------------------------------------------- #
# (9) req 3 — modal shims suppressed while active, restored afterwards          #
# --------------------------------------------------------------------------- #
def test_modal_shims_suppressed_while_active_and_restored(monkeypatch):
    import tct_gui
    from tct_gui import TCTMainWindow

    class _MBStub:
        calls: list = []

        @staticmethod
        def critical(*a, **k):
            _MBStub.calls.append("critical")

        @staticmethod
        def warning(*a, **k):
            _MBStub.calls.append("warning")

    notified: list = []
    monkeypatch.setattr(tct_gui, "QMessageBox", _MBStub)
    monkeypatch.setattr(tct_gui, "notify",
                        lambda text, level="info": notified.append((text, level)))

    active = SimpleNamespace(_sequence_active=True)
    TCTMainWindow._show_error_dialog(active, "Scan Error", "boom")
    TCTMainWindow._show_warn_dialog(active, "Not ready", "later")
    assert _MBStub.calls == []                       # no blocking dialog exec
    assert ("Scan Error: boom", "error") in notified
    assert ("Not ready: later", "warn") in notified

    idle = SimpleNamespace(_sequence_active=False)
    TCTMainWindow._show_error_dialog(idle, "Scan Error", "boom")
    assert _MBStub.calls == ["critical"]             # modal restored when idle


# --------------------------------------------------------------------------- #
# (10) the sequence_active wiring actually exists in the composition root       #
# --------------------------------------------------------------------------- #
def test_sequence_active_wired_in_build_central():
    import tct_gui
    src = inspect.getsource(tct_gui.TCTMainWindow._build_central)
    assert "SequenceCoordinator(" in src
    assert "SequencerPanel(" in src
    assert "sequence_active.connect(self._on_sequence_active)" in src
    assert "park_safe=self._scanner.park_safe" in src
