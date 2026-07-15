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

* req 2 (A5.1) — ``sequence_active`` drives each panel's surgical
  ``set_manual_danger_locked`` (energize/motion-START controls lock; the
  emergency OFF/STOP affordances stay live — cockpit law 5) and UNCONDITIONALLY
  unlocks at every terminal (including a failure path);
* req 3 — the coordinator's modal error/warn shims reroute to the non-blocking
  status bus while a sequence runs and restore afterwards.

The per-panel *always-live* guarantee (OFF/STOP fire while locked, unlock
restores the panel's own busy-correct state) is pinned where the controls live:
tests/test_bias_danger_gate.py and tests/test_motor_danger_gate.py.

Idiom: ``QT_QPA_PLATFORM=offscreen``, a shared ``QApplication.instance()``, no
pytest-qt.
"""
from __future__ import annotations

import inspect
import logging
import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import yaml
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from controller.danger_gate import AutoConfirmGate
from controller.device_manager import DeviceManager
from controller.scan_controller import ScanController
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.sequencer import (
    EntryState, SequenceEntry, load_sequence_yaml, save_sequence_yaml,
)
from controller.state_machine import AppState, StateMachine
from gui.scan_coordinator import ScanCoordinator
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


class LockSpy:
    """A stand-in danger panel that records its manual-danger-lock state.

    A5.1: the composition root no longer blanket-``setEnabled``\\ s the panels
    (that greyed out the emergency OFF/STOP too); it calls the surgical
    ``set_manual_danger_locked`` seam instead — this spy pins that the wiring
    drives THAT method, True at arm and (unconditionally) False at every
    terminal.  The always-live behaviour of the real controls is verified in the
    panels' own danger-gate tests."""

    def __init__(self) -> None:
        self.locked = False

    def set_manual_danger_locked(self, locked: bool) -> None:
        self.locked = bool(locked)


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


def _bias_manual_pause_plan(name: str, hv: float = -5.0) -> ScanPlan:
    """Ramp bias to *hv* (a real, single-setpoint BiasStep — no leading 0.0
    value, so the pause below is hit while genuinely energized), acquire+save,
    a MID-plan MANUAL_PAUSE, then acquire+save again.  Shape mirrors
    tests/test_plan_executor.py's ``_bias_pause_plan`` (already proven against
    a real ScanController + AutoConfirmGate).

    A5.2a's ``assert_sequencer_compatible`` now rejects this shape fail-closed
    at BOTH ``SequenceCoordinator.load`` and ``SequenceRunner``'s own
    constructor — by design that makes it unreachable through the normal API,
    which is exactly why the one integration test below neutralizes those two
    checks: it is proving the A5.2b belt-and-braces guard holds even if a
    manual_pause plan ever slipped past them."""
    acquire = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={})
    save = ActionBlock(action=ActionType.SAVE_POINT, params={})
    pause = ActionBlock(action=ActionType.MANUAL_PAUSE, params={"prompt": "swap sample"})
    children = [acquire, save, pause, acquire, save]
    bias_loop = LoopBlock(axis=Axis.BIAS_V, values=[float(hv)], children=children)
    return ScanPlan(name=name, root=[bias_loop],
                    safety={"require_hv_confirmation": True})


def _sim_config_path(tmp_path) -> str:
    """A fully-simulated devices.yaml (mirrors tests/test_plan_executor.py's
    ``sim`` fixture) — used only by the one real-device integration test
    below; every other test in this file drives ``FakeScanCoordinator``."""
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


def _real_plan_limits() -> PlanLimits:
    return PlanLimits(
        x_min_mm=-50.0, x_max_mm=50.0, y_min_mm=-50.0, y_max_mm=50.0,
        z_min_mm=-10.0, z_max_mm=10.0, voltage_range_V=1000.0,
        max_points=1_000_000,
    )


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
# (7) req 2 — sequence_active locks/unlocks the manual danger panels           #
# --------------------------------------------------------------------------- #
def test_on_sequence_active_locks_and_unlocks_manual_danger_panels():
    from tct_gui import TCTMainWindow
    bias, motor = LockSpy(), LockSpy()
    main = SimpleNamespace(_sequence_active=False, _bias_panel=bias, _motor_panel=motor)

    TCTMainWindow._on_sequence_active(main, True)
    assert main._sequence_active is True
    # A5.1: the surgical lock is driven, NOT a blanket panel setEnabled.
    assert bias.locked is True and motor.locked is True

    TCTMainWindow._on_sequence_active(main, False)
    assert main._sequence_active is False
    assert bias.locked is False and motor.locked is False     # unconditional


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

    bias, motor = LockSpy(), LockSpy()
    main = SimpleNamespace(_sequence_active=False, _bias_panel=bias, _motor_panel=motor)
    coord.sequence_active.connect(lambda a: TCTMainWindow._on_sequence_active(main, a))

    coord.arm_and_start()
    assert bias.locked is True and motor.locked is True       # locked at arm

    fake.error_run("driver fault")          # entry 0 fails → fail-closed halt
    assert main._sequence_active is False
    assert bias.locked is False and motor.locked is False     # unlocked anyway


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


# --------------------------------------------------------------------------- #
# (11) A5.1 integration — the real coordinator signal drives the surgical lock  #
#      on REAL panels: energize/motion lock, OFF/ALL-OFF/STOP stay live, and a   #
#      True→False round-trip (via a FAILURE terminal) restores the real state.  #
# --------------------------------------------------------------------------- #
def test_real_panels_surgical_lock_round_trip_via_coordinator_signal():
    from PySide6.QtWidgets import QPushButton

    from controller.danger_gate import AutoConfirmGate
    from devices.bias_channel import BiasChannel
    from devices.bias_supply_simulated import SimulatedBiasSupply
    from devices.motor_simulated import SimulatedMotorStage
    from gui.motor_panel import MotorPanel
    from gui.multi_bias_panel import MultiBiasPanel
    from tct_gui import TCTMainWindow

    app = _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=ParkSpy())
    coord.load([("r0", _plan("r0")), ("r1", _plan("r1"))])
    coord.build_gate(channel=0)

    gate = AutoConfirmGate()
    motor = MotorPanel(SimulatedMotorStage(), gate=gate)
    bias = MultiBiasPanel([BiasChannel(SimulatedBiasSupply(), 0)], gate=gate)
    child = bias._panels[0]

    def _stop_btn() -> QPushButton:
        return next(b for b in motor.findChildren(QPushButton)
                    if b.objectName() == "dangerBtn" and b.text() == "STOP")

    # Exactly the production wiring: the coordinator's sequence_active signal
    # drives TCTMainWindow._on_sequence_active on a namespace holding real panels.
    main = SimpleNamespace(_sequence_active=False, _bias_panel=bias, _motor_panel=motor)
    coord.sequence_active.connect(lambda a: TCTMainWindow._on_sequence_active(main, a))
    try:
        # baseline: everything live
        assert child._btn_apply.isEnabled() and child._btn_off.isEnabled()
        assert bias._btn_all_off.isEnabled()
        assert all(w.isEnabled() for w in motor._motion_widgets)
        assert _stop_btn().isEnabled()

        coord.arm_and_start()
        # energize + motion-START controls are locked ...
        assert not child._btn_apply.isEnabled()
        assert not child._spin_comp.isEnabled()
        assert not any(w.isEnabled() for w in motor._motion_widgets)
        # ... but EVERY emergency de-energize / stop affordance stays LIVE (law 5)
        assert child._btn_off.isEnabled()
        assert bias._btn_all_off.isEnabled()
        assert _stop_btn().isEnabled()

        fake.error_run("driver fault")          # fail-closed terminal
        assert main._sequence_active is False
        # unconditional unlock restores the panels' own busy-correct enabled state
        assert child._btn_apply.isEnabled() and child._spin_comp.isEnabled()
        assert all(w.isEnabled() for w in motor._motion_widgets)
        assert child._btn_off.isEnabled() and _stop_btn().isEnabled()
    finally:
        motor.shutdown()
        bias.shutdown()
        motor.deleteLater()
        bias.deleteLater()
        app.processEvents()


# --------------------------------------------------------------------------- #
# (12) A5.2b — belt-and-braces guard: a manual_pause dialog request during a   #
#      running SEQUENCE must never block on a human (Mary defense-in-depth     #
#      finding).  The PRIMARY fix (A5.2a) rejects a manual_pause plan at       #
#      sequencer load; these pin the backstop for anything that slips through. #
# --------------------------------------------------------------------------- #
class _FakeMessageBox:
    """A controllable stand-in for QMessageBox's construct/addButton/exec/
    clickedButton() contract.  ``click`` (class attribute) selects which role
    ``clickedButton()`` reports as clicked, so a test can force either branch.
    Every construction is recorded (``instances``) so a test can pin "a dialog
    really was shown" without depending on Qt actually painting one."""
    Information = "information"
    AcceptRole = "accept"
    RejectRole = "reject"

    click = "accept"
    instances: list = []

    def __init__(self, icon, title, text, parent=None):
        self.icon, self.title, self.text, self.parent = icon, title, text, parent
        self._buttons: dict = {}
        self.exec_called = False
        type(self).instances.append(self)

    def addButton(self, text, role):
        btn = SimpleNamespace(text=text, role=role)
        self._buttons[role] = btn
        return btn

    def exec(self):
        self.exec_called = True

    def clickedButton(self):
        return self._buttons.get(type(self).click)


def test_manual_pause_during_sequence_no_dialog_notify_and_abort(monkeypatch, caplog):
    """The core guard: while ``_sequence_active`` is True, ``_on_plan_manual_
    pause`` must NEVER construct a QMessageBox — it must ``notify()`` with a
    clear reason, log at warning, and trigger ``abort_sequence()`` (the exact
    path the Scan Sequencer panel's own Abort button uses) — never the plain
    per-run ``resume()``/``abort()``."""
    import tct_gui
    from tct_gui import TCTMainWindow

    class _ExplodingMessageBox:
        def __init__(self, *a, **k):
            raise AssertionError(
                "QMessageBox must never be constructed while a sequence is active")

    monkeypatch.setattr(tct_gui, "QMessageBox", _ExplodingMessageBox)

    notified: list = []
    monkeypatch.setattr(tct_gui, "notify",
                        lambda text, level="info": notified.append((text, level)))

    seq_calls = {"abort_sequence": 0}
    fake_seq = SimpleNamespace(
        abort_sequence=lambda: seq_calls.__setitem__(
            "abort_sequence", seq_calls["abort_sequence"] + 1))
    coord_calls = {"resume": 0, "abort": 0}
    fake_coord = SimpleNamespace(
        resume=lambda: coord_calls.__setitem__("resume", coord_calls["resume"] + 1),
        abort=lambda: coord_calls.__setitem__("abort", coord_calls["abort"] + 1),
    )
    main = SimpleNamespace(_sequence_active=True, _seq_coordinator=fake_seq,
                           _coordinator=fake_coord)

    with caplog.at_level(logging.WARNING):
        TCTMainWindow._on_plan_manual_pause(main, "swap sample")

    assert seq_calls["abort_sequence"] == 1
    assert coord_calls == {"resume": 0, "abort": 0}       # not the plain-dialog path
    assert notified and notified[-1][1] == "warn"
    assert "unattended sequence" in notified[-1][0]
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_manual_pause_during_sequence_missing_seq_coordinator_does_not_crash(monkeypatch):
    """Defensive: ``_sequence_active=True`` with no ``_seq_coordinator`` (should
    be unreachable — ``_on_sequence_active`` only sets the flag True while the
    coordinator that fired it is alive) must still notify and never dialog or
    raise into the caller."""
    import tct_gui
    from tct_gui import TCTMainWindow

    class _ExplodingMessageBox:
        def __init__(self, *a, **k):
            raise AssertionError("QMessageBox must never be constructed")

    monkeypatch.setattr(tct_gui, "QMessageBox", _ExplodingMessageBox)
    notified: list = []
    monkeypatch.setattr(tct_gui, "notify",
                        lambda text, level="info": notified.append((text, level)))

    main = SimpleNamespace(_sequence_active=True, _seq_coordinator=None)
    TCTMainWindow._on_plan_manual_pause(main, "swap sample")   # must not raise
    assert notified and notified[-1][1] == "warn"


def test_non_sequence_manual_pause_still_shows_dialog_resume_and_abort(monkeypatch):
    """Pin: outside a sequence, behavior is byte-identical to before this
    beat — a QMessageBox IS constructed and exec'd, and Resume/Abort clicks
    route to ``coordinator.resume()``/``abort()`` respectively."""
    import tct_gui
    from tct_gui import TCTMainWindow

    _FakeMessageBox.instances = []
    monkeypatch.setattr(tct_gui, "QMessageBox", _FakeMessageBox)

    calls = {"resume": 0, "abort": 0}
    fake_coord = SimpleNamespace(
        resume=lambda: calls.__setitem__("resume", calls["resume"] + 1),
        abort=lambda: calls.__setitem__("abort", calls["abort"] + 1),
    )
    main = SimpleNamespace(_sequence_active=False, _coordinator=fake_coord)

    _FakeMessageBox.click = _FakeMessageBox.AcceptRole      # "Resume plan" clicked
    TCTMainWindow._on_plan_manual_pause(main, "swap sample")
    assert len(_FakeMessageBox.instances) == 1
    assert _FakeMessageBox.instances[0].exec_called is True
    assert calls == {"resume": 1, "abort": 0}

    _FakeMessageBox.click = _FakeMessageBox.RejectRole      # "Abort plan" clicked
    TCTMainWindow._on_plan_manual_pause(main, "swap sample")
    assert len(_FakeMessageBox.instances) == 2
    assert calls == {"resume": 1, "abort": 1}


def test_manual_pause_during_real_sequence_aborts_fail_safe_and_parks_hv(tmp_path, monkeypatch):
    """Integration / defense-in-depth: even if a manual_pause plan somehow got
    armed + running for REAL — bypassing BOTH of A5.2a's fail-closed
    compatibility gates (``SequenceCoordinator.load`` and ``SequenceRunner``'s
    own constructor re-check; production makes reaching that combination
    impossible, which is exactly why it is neutralized here on purpose) — the
    A5.2b guard aborts the sequence with NO dialog, and the paused worker's HV
    really ends up OFF: a real ``ScanController`` + simulated bias supply, not
    a mocked ``abort()`` call.  ``park.calls`` additionally confirms
    ``abort_sequence``'s own belt-and-braces re-park fired."""
    import controller.sequencer as sequencer_mod
    import gui.sequence_coordinator as seqcoord_mod
    import tct_gui
    from tct_gui import TCTMainWindow

    monkeypatch.setattr(seqcoord_mod, "assert_sequencer_compatible",
                        lambda plan, name="": None)
    monkeypatch.setattr(sequencer_mod, "assert_sequencer_compatible",
                        lambda plan, name="": None)

    app = _app()
    dm = DeviceManager(config_path=_sim_config_path(tmp_path))
    assert dm.config_errors() == []
    assert all(v == "ok" for v in dm.connect_all().values())
    dm.motor.home()
    try:
        sm = _ready_sm()
        ctrl = ScanController(dm, sm)
        scan_coord = ScanCoordinator(ctrl, sm, AutoConfirmGate(),
                                     lambda: _real_plan_limits())
        park = ParkSpy()
        seq_coord = SequenceCoordinator(scan_coord, sm, park_safe=park)

        main = SimpleNamespace(_sequence_active=False, _seq_coordinator=seq_coord,
                               _coordinator=scan_coord)
        seq_coord.sequence_active.connect(
            lambda active: setattr(main, "_sequence_active", bool(active)))

        prompts: list = []

        def _forward_manual_pause(prompt: str) -> None:
            prompts.append(prompt)
            TCTMainWindow._on_plan_manual_pause(main, prompt)

        scan_coord.manual_pause.connect(_forward_manual_pause)

        finished_words: list = []
        seq_coord.sequence_finished.connect(finished_words.append)
        errors: list = []
        scan_coord.error_dialog.connect(lambda t, m: errors.append((t, m)))

        class _CountingMessageBox:
            constructed = 0

            def __init__(self, *a, **k):
                _CountingMessageBox.constructed += 1

        monkeypatch.setattr(tct_gui, "QMessageBox", _CountingMessageBox)

        seq_coord.load([("night_shift", _bias_manual_pause_plan("night_shift"))])
        seq_coord.build_gate(channel=0)
        seq_coord.arm_and_start()
        assert not errors, f"plan execution refused: {errors}"

        # Cross-thread: the worker's on_manual_pause is delivered via a queued
        # signal (the same _ScanBridge every scan callback crosses on) — pump
        # the event loop until it lands, bounded like test_plan_executor.py's
        # sm.state polls.
        deadline = time.time() + 20
        while time.time() < deadline and not prompts:
            app.processEvents()
            time.sleep(0.01)
        assert prompts == ["swap sample"]

        # The guard ran synchronously while delivering the queued signal above.
        assert main._sequence_active is False
        assert finished_words == ["cancelled"]
        assert seq_coord.is_active is False
        assert park.calls >= 1                        # belt-and-braces re-park too
        assert _CountingMessageBox.constructed == 0    # no dialog, ever

        # Let the released worker actually run its fail-safe teardown.
        ctrl._thread.join(timeout=20)
        assert not ctrl._thread.is_alive()
        assert sm.state is AppState.ABORTED
        assert dm.bias_supply.is_output_on is False    # HV really parked
    finally:
        dm.disconnect_all()
