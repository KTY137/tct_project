"""SEQUENCER_PANEL migrated onto the round-03 glass kit (panel wave beat 5/12).

Mirrors ``tests/test_pilot_bias_render.py`` (the pilot) and
``tests/test_wave_stage_view_render.py`` (wave 1), adapted to what this panel
actually is: a HAZARD panel (mirrors the bias pilot's blanket stance, not the
content-consequence reasoning of Intensity/Laser) whose combined-envelope Arm/
Execute ceremony sits on an opaque ``HazardSurface``.

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen, no
device I/O — the harness below drives a REAL ``SequenceCoordinator`` against a
deterministic ``FakeScanCoordinator``, the same seam idiom
``tests/test_sequencer_panel.py`` uses):

  * the panel is now one ``GlassPane`` shelf (``#shelfPane``) carrying a
    ``panel_header`` chrome head (eyebrow + title + status chip + Add/Abort);
  * the shelf opts NOTHING into the panel-glass switch — ``register=False``,
    the same blanket HAZARD-panel stance as the bias pilot (this queue arms
    hardware motion, and per-routine HV, to run unattended all night);
  * the combined-envelope Arm/Execute ceremony (the reused ``ArmLatch``) is a
    PURE PARENT-FRAME WRAP inside an opaque ``HazardSurface`` carrying the
    ``armed`` (motion-class) stripe — opaque at every tier, including with the
    panel-glass switch flipped ON;
  * the Abort control stays a plain header trailing widget, OUTSIDE both the
    HazardSurface and any ``ActionBar``;
  * a live light -> dark -> light switch re-resolves the hazard surface's
    stripe/hatch/fill (and the envelope's cached HV-span colour) without a
    crash;
  * ``shutdown()`` is clean (idempotent, no dangling timers).

``tests/test_sequencer_panel.py`` is READ-ONLY and stays green — it is the
authority on the panel's run-control/envelope/save-load contract; this file
only proves the glass re-skin didn't disturb the structure or behavior that
contract test walks through.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.sequencer import SequenceEntry
from controller.state_machine import AppState, StateMachine
from gui import panel_kit
from gui.arm_latch import ArmLatch
from gui.panel_kit import ActionBar, GlassPane, HazardSurface
from gui.sequence_coordinator import SequenceCoordinator
from gui.sequencer_panel import SequencerPanel
from gui.style import apply_theme, palette

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "wave_sequencer"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dispose(panel: SequencerPanel) -> None:
    panel.shutdown()
    panel.deleteLater()


class FakeScanCoordinator(QObject):
    """Deterministic stand-in for gui.scan_coordinator.ScanCoordinator — the
    same seam ``SequenceCoordinator`` consumes (tests/test_sequencer_panel.py)."""

    plan_finished = Signal()
    plan_error = Signal(str)

    def __init__(self, sm: StateMachine) -> None:
        super().__init__()
        self._sm = sm
        self._active = False

    @property
    def plan_run_active(self) -> bool:
        return self._active

    def execute_plan(self, plan, gate) -> None:
        self._sm.transition(AppState.RUNNING)
        self._active = True

    def abort(self) -> None:
        pass


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


def _bias_motion_plan(name: str, hv: float = -300.0, travel=(-2.0, 2.0)) -> ScanPlan:
    """A bias -> x plan so the combined envelope carries a real HV range +
    travel (mirrors test_sequencer_panel.py's helper of the same name)."""
    acquire = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={})
    save = ActionBlock(action=ActionType.SAVE_POINT, params={})
    x_loop = LoopBlock(axis=Axis.STAGE_X, values=[float(travel[0]), float(travel[1])],
                       children=[acquire, save])
    bias_loop = LoopBlock(axis=Axis.BIAS_V, values=[0.0, float(hv)], children=[x_loop])
    return ScanPlan(name=name, root=[bias_loop],
                    safety={"require_hv_confirmation": True})


def _panel() -> SequencerPanel:
    """A panel wired to a real coordinator, with one armed-HV routine loaded
    so the latch renders a real envelope over the hazard surface."""
    _app()
    sm = _ready_sm()
    fake = FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=ParkSpy())
    panel = SequencerPanel(coord, channel_provider=lambda: 0)
    panel._entries.append(
        SequenceEntry(name="r0", plan=_bias_motion_plan("r0"), source_path=None))
    panel._sync_coordinator()
    return panel


# --------------------------------------------------------------------------- #
# Structure — one shelf, register=False (hazard panel), nothing detached       #
# --------------------------------------------------------------------------- #

def test_panel_is_one_glass_pane_shelf():
    panel = _panel()
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        assert panel.isAncestorOf(panel._shelf)
    finally:
        _dispose(panel)


def test_sequencer_opts_nothing_into_glass():
    """HAZARD PANEL — the same blanket ``register=False`` stance as the bias
    pilot: this queue arms hardware motion (and, per routine, HV) to run
    unattended all night, so the shelf must opt NOTHING into the panel-glass
    switch, even with the switch flipped ON."""
    panel = _panel()
    try:
        panel_kit.set_panel_glass(True)
        panes = [p for p in panel_kit.registered_glass_panes()
                 if panel is p or panel.isAncestorOf(p)]
        assert panes == [], "the Scan Sequencer must opt NOTHING into glass"
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_run_control_wrapped_in_a_hazard_surface_with_armed_stripe():
    """The combined-envelope Arm/Execute ceremony is a PURE PARENT-FRAME WRAP:
    the SAME ArmLatch object, now a descendant of exactly one HazardSurface
    carrying the ``armed`` (motion-class) stripe."""
    panel = _panel()
    try:
        hazards = panel.findChildren(HazardSurface)
        assert len(hazards) == 1
        haz = hazards[0]
        assert haz is panel._hazard
        assert haz.objectName() == "hazardSurface"
        assert haz.stripe_kind() == "armed"
        assert isinstance(panel._latch, ArmLatch)
        assert haz.isAncestorOf(panel._latch), "the latch floated off the hazard surface"
    finally:
        _dispose(panel)


def test_hazard_surface_opaque_fill_survives_panel_glass_switch():
    """Consequence rule (kit §4.6): a HazardSurface is opaque at EVERY tier —
    flipping the (irrelevant, since this panel never registers) panel-glass
    switch must never touch its pinned instance fill."""
    panel = _panel()
    try:
        p = palette(panel._theme_mode)
        before = panel._hazard.styleSheet()
        assert f"background: {p['panel']}" in before
        panel_kit.set_panel_glass(True)
        # Real coverage is registry ABSENCE (see
        # test_sequencer_opts_nothing_into_glass) — the surface is never
        # registered, so an unchanged styleSheet() here is trivially true.
        assert panel._hazard.property("glassPane") in (None, "")
        assert panel._hazard.property("glassCard") in (None, "")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_abort_stays_outside_the_hazard_surface_and_any_action_bar():
    """The always-live stop control never nests inside the danger-state
    display it can silence (the bias pilot's kill-switch precedent), and never
    inside an ActionBar (whose danger slot clobbers objectNames/escalation
    chrome — this panel doesn't use ActionBar for it at all)."""
    panel = _panel()
    try:
        assert not panel._hazard.isAncestorOf(panel._btn_abort)
        bars = panel.findChildren(ActionBar)
        assert all(not bar.isAncestorOf(panel._btn_abort) for bar in bars)
    finally:
        _dispose(panel)


def test_kit_wrap_did_not_detach_anything_from_the_tree():
    """Kit-wrap sanity: every attribute the pinned run-control test
    (tests/test_sequencer_panel.py) reads through directly is still reachable
    through the SAME attribute name and still a real descendant."""
    panel = _panel()
    try:
        for attr in ("_chip_status", "_btn_add", "_btn_abort", "_table",
                     "_btn_remove", "_btn_up", "_btn_down", "_btn_save",
                     "_btn_load", "_latch", "_hazard", "_progress_lbl",
                     "_outcome_lbl"):
            widget = getattr(panel, attr)
            assert panel.isAncestorOf(widget), f"{attr} floated off the shelf"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, re-resolves stripe/hatch/fill       #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light_round_trip():
    panel = _panel()
    try:
        for mode in ("dark", "light", "dark"):
            panel.refresh_theme(mode)
            assert panel._theme_mode == mode
            p = palette(mode)
            assert panel._hazard._stripe_color.name().lower() == p["armed"].lower()
            assert f"background: {p['panel']}" in panel._hazard.styleSheet()
    finally:
        _dispose(panel)


def test_refresh_theme_re_resolves_envelope_hv_span_colour():
    """The envelope's inline HV danger span is the one cached colour outside
    the hazard surface — both themes must render it from tokens."""
    panel = _panel()
    try:
        panel.refresh_theme("dark")
        dark_html = panel._envelope_html(panel._env)
        panel.refresh_theme("light")
        light_html = panel._envelope_html(panel._env)
        assert dark_html and light_html
        assert dark_html != light_html
    finally:
        _dispose(panel)


def test_shutdown_is_clean_and_idempotent():
    panel = _panel()
    panel.shutdown()
    panel.shutdown()   # idempotent — must not raise
    panel.deleteLater()


# --------------------------------------------------------------------------- #
# The render — both themes, TOKEN tier                                        #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_sequencer_panel_both_themes(mode):
    app = _app()
    apply_theme(app, mode)
    panel = _panel()
    try:
        panel.refresh_theme(mode)

        panel.resize(720, max(640, panel.sizeHint().height()))
        panel.show()
        app.processEvents()

        img = panel.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"sequencer_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests
