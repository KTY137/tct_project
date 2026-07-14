"""MOTOR_PANEL migrated onto the round-03 glass kit (panel wave beat 10/12).

Mirrors ``tests/test_wave_sequencer_render.py`` / ``test_wave_calibration_render.py``
(waves 5/7, the hazard precedents), adapted to what this panel actually is: a
HAZARD panel (stage motion) whose every stage-commanding cluster — the jog
cross, the absolute Move-to, and Home/Center/Zero + the emergency STOP — sits
on ONE opaque ``HazardSurface``, while the position readout + status chips
(display) and the scan-integration helpers (copy/emit, no motion) stay outside
it (the danger topology: display vs trigger).

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen, a
simulated motor, never connected — no device I/O, hardware-safety rule 1):

  * the panel is now one ``GlassPane`` shelf (``#shelfPane``) carrying a
    ``panel_header`` chrome head; the shelf opts NOTHING into the panel-glass
    switch (``register=False``);
  * BLANKET register=False — unlike calibration (which kept two rollout-vetted
    parameter registrations), this panel registers NOTHING at all: the motor
    panel has zero existing registrations to preserve and every card is
    motion-adjacent;
  * every widget that COMMANDS the stage (jog X/Y/Z buttons, Move to,
    Home all, Center, Zero here, STOP) is a descendant of exactly one opaque
    ``HazardSurface`` carrying the ``armed`` (motion-class) stripe — opaque at
    every tier, including with the panel-glass switch flipped ON, never
    registered;
  * the display widgets (X/Y/Z position labels + the status chips) and the
    scan-integration helpers do NOT sit inside the hazard wrap;
  * a live light -> dark -> light switch re-resolves the hazard surface's
    stripe/hatch/fill without a crash;
  * the frame contract is intact: the live stage view is still reachable and a
    real descendant, the splitter still holds shelf + stage view.

The gated-motion DangerGate wiring, the jog one-tap path, the transport-lock
discipline and the reload/shutdown lifecycle are pinned byte-identical by the
adjacent suites (``test_motor_danger_gate.py``, ``test_motor_frame_contract.py``,
``test_motor_panel_reload.py``, ``test_motor_icon_theming.py``); this file only
proves the glass re-skin left the structure and the danger topology intact.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from devices.motor_simulated import SimulatedMotorStage
from gui import panel_kit
from gui.motor_panel import MotorPanel
from gui.panel_kit import GlassPane, HazardSurface
from gui.style import apply_theme, palette

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "wave_motor"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel() -> MotorPanel:
    _app()
    return MotorPanel(SimulatedMotorStage())


def _dispose(panel: MotorPanel) -> None:
    app = _app()
    panel.shutdown()
    panel.deleteLater()
    app.processEvents()


def _button(panel: MotorPanel, text: str) -> QPushButton:
    for btn in panel.findChildren(QPushButton):
        if btn.text().strip().casefold() == text.casefold():
            return btn
    raise AssertionError(f"no button labelled {text!r} in the motor panel")


# The controls that COMMAND the stage — every one must live inside the hazard.
_COMMAND_LABELS = ("X+", "X−", "Y+", "Y−", "Z+", "Z−",
                   "Move to", "Home all", "Center", "Zero here", "STOP")


# --------------------------------------------------------------------------- #
# Structure — one shelf (register=False), blanket: NOTHING registers            #
# --------------------------------------------------------------------------- #

def test_panel_is_one_glass_pane_shelf():
    panel = _panel()
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        assert panel.isAncestorOf(panel._shelf)
    finally:
        _dispose(panel)


def test_blanket_register_false_nothing_under_the_panel_registers():
    """BLANKET stance (Adam's topology): this panel has zero rollout-vetted
    registrations to preserve and every card is motion-adjacent, so NOTHING
    under it — not the shelf, not any card, not the hazard surface — opts into
    the panel-glass switch."""
    panel = _panel()
    try:
        registered = [
            p for p in panel_kit.registered_glass_panes()
            if panel is p or panel.isAncestorOf(p)
        ]
        assert registered == [], (
            "motor is a blanket-register=False hazard panel — nothing may "
            f"register, found {registered}")
        assert panel._shelf.property("glassPane") in (None, "")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Hazard topology — every commanding widget inside; display widgets outside     #
# --------------------------------------------------------------------------- #

def test_one_hazard_surface_with_armed_stripe():
    panel = _panel()
    try:
        hazards = panel.findChildren(HazardSurface)
        assert len(hazards) == 1
        haz = hazards[0]
        assert haz is panel._hazard
        assert haz.objectName() == "hazardSurface"
        assert haz.stripe_kind() == "armed"
    finally:
        _dispose(panel)


def test_every_stage_commanding_widget_sits_inside_the_hazard_surface():
    """The invariant: every widget that COMMANDS the stage — the jog cluster,
    the absolute Move-to, Home/Center/Zero, and the emergency STOP — is a
    descendant of the one opaque HazardSurface."""
    panel = _panel()
    try:
        haz = panel._hazard
        for label in _COMMAND_LABELS:
            btn = _button(panel, label)
            assert haz.isAncestorOf(btn), f"{label!r} is not inside the hazard wrap"
        # And the jog buttons the panel tracks by axis are all inside too.
        for axis, buttons in panel._jog_axis_btns.items():
            for btn in buttons:
                assert haz.isAncestorOf(btn), f"jog {axis} button outside hazard"
    finally:
        _dispose(panel)


def test_display_widgets_stay_outside_the_hazard_surface():
    """Danger topology (display vs trigger): the position readout labels and
    the status chips DISPLAY state — they do not command — so they stay OUTSIDE
    the hazard wrap. Same for the scan-integration helpers (copy/emit, no
    motion)."""
    panel = _panel()
    try:
        haz = panel._hazard
        # Position readout values + captions.
        for lbl in (panel._lbl_x, panel._lbl_y, panel._lbl_z):
            assert not haz.isAncestorOf(lbl), "a position readout leaked into hazard"
        # Status chips.
        for chip in (panel._chip_homed, panel._chip_motion, panel._chip_limits,
                     panel._chip_switches, panel._chip_last):
            assert not haz.isAncestorOf(chip), "a status chip leaked into hazard"
        # Scan-integration helpers (no motion) + the connection test button.
        for label in ("Use current position", "Set as scan start",
                      "Test connection"):
            assert not haz.isAncestorOf(_button(panel, label)), \
                f"{label!r} is display/helper — must stay outside hazard"
    finally:
        _dispose(panel)


def test_hazard_surface_never_registers_and_stays_opaque_through_the_glass_switch():
    """Consequence rule (kit §4.6): a HazardSurface is opaque at EVERY tier —
    never in the registry, and flipping the panel-glass switch must never touch
    its pinned instance fill or add a glass property."""
    panel = _panel()
    try:
        registered = {id(p) for p in panel_kit.registered_glass_panes()}
        assert id(panel._hazard) not in registered

        p = palette(panel._theme_mode)
        before = panel._hazard.styleSheet()
        assert f"background: {p['panel']}" in before

        panel_kit.set_panel_glass(True)
        after = panel._hazard.styleSheet()
        assert after == before, "HazardSurface fill must not react to the glass switch"
        assert panel._hazard.property("glassPane") in (None, "")
        assert panel._hazard.property("glassCard") in (None, "")
        # The shelf still never went glass either.
        assert panel._shelf.property("glassPane") in (None, "")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Frame contract — the live stage view + splitter are untouched                 #
# --------------------------------------------------------------------------- #

def test_frame_contract_stage_view_and_splitter_intact():
    """The kit wrap is container-only: the live stage view is still a real
    descendant (never inside the hazard — it is a display, not a control), the
    shelf is its splitter sibling, and set_motor still re-pulls limits."""
    from PySide6.QtWidgets import QSplitter

    panel = _panel()
    try:
        assert panel.isAncestorOf(panel._stage_view)
        assert not panel._hazard.isAncestorOf(panel._stage_view)
        split = panel.findChild(QSplitter)
        assert split is not None
        assert split.isAncestorOf(panel._shelf)
        assert split.isAncestorOf(panel._stage_view)
        # A hot-swap still redraws the envelope (frame-contract plumbing intact).
        panel.set_motor(SimulatedMotorStage())
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, re-resolves stripe/hatch/fill        #
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


def test_shutdown_is_clean_and_idempotent():
    panel = _panel()
    panel.shutdown()
    panel.shutdown()   # idempotent — must not raise
    panel.deleteLater()


# --------------------------------------------------------------------------- #
# The render — both themes, TOKEN tier                                          #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_motor_panel_both_themes(mode):
    app = _app()
    apply_theme(app, mode)
    panel = _panel()
    try:
        panel.refresh_theme(mode)

        panel.resize(1000, max(640, panel.sizeHint().height()))
        panel.show()
        app.processEvents()

        img = panel.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"motor_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests
