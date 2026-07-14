"""PLANNER_PANEL migrated onto the round-03 glass kit (panel wave beat 12/12).

Mirrors ``tests/test_wave_calibration_render.py`` / ``test_wave_motor_render``
(the hazard precedents), adapted to what this panel is: the Scan Routine
Planner — a HAZARD panel whose Start ramps HV and drives the stage. Its danger
zone (the ``ArmLatch`` danger well + the ``#dangerBtn`` Abort) now sits on one
opaque ``HazardSurface`` in the "Before you run" aside, while the whole panel is
wrapped in one ``GlassPane`` shelf that opts NOTHING into the panel-glass
switch. The ONE rollout-vetted opt-in — the "Add blocks" palette (pure
draggable chrome) — keeps its individual registration, byte-identical.

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen, no
device I/O — this panel never talks to hardware, hardware-safety rule 1):

  * the panel is now one ``GlassPane`` shelf (``#shelfPane``); the shelf opts
    NOTHING into the panel-glass switch (``register=False`` — content shell);
  * the rollout decision is preserved: the "Add blocks" palette is STILL
    registered (pinned by tests/test_panel_glass_rollout.py:252) and is the
    ONLY registered pane under this panel — registry ABSENCE is asserted for
    the shelf and the hazard surface (not a trivially-true set_panel_glass
    equality, Mary nit waves 5/7/10);
  * the ArmLatch danger well AND the #dangerBtn Abort are a PURE PARENT-FRAME
    WRAP inside exactly one opaque ``HazardSurface`` carrying the ``armed``
    (motion-class) stripe — opaque at every tier, including with the panel-
    glass switch flipped ON, and never registered; their relative placement
    (latch above, Abort below) is preserved;
  * Abort's enabled-state discipline is UNCHANGED by the wrap: it is driven
    ONLY by ``set_running()`` (disabled at rest, enabled during a run), it is
    in no bulk disable set, and the hazard surface parent is never disabled;
  * a live light -> dark -> light switch re-resolves the hazard surface's
    stripe/hatch/fill without a crash;
  * ``shutdown()`` is clean and idempotent (the estimate worker thread joins).

``tests/test_panel_glass_rollout.py`` (the census / rollout authority) and
``tests/test_planner_panel.py`` stay green — this file only proves the glass
re-skin left the structure and the danger wiring intact.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gui import panel_kit
from gui.arm_latch import ArmLatch
from gui.panel_kit import GlassPane, HazardSurface
from gui.planner_panel import PlannerPanel
from gui.style import apply_theme, palette

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "wave_planner"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel() -> PlannerPanel:
    _app()
    return PlannerPanel()


def _dispose(panel: PlannerPanel) -> None:
    panel.shutdown()
    panel.deleteLater()


def _planner_registered() -> list:
    """Registered glass panes that are this panel's descendants (or itself)."""
    return panel_kit.registered_glass_panes()


# --------------------------------------------------------------------------- #
# Structure — one shelf (register=False)                                       #
# --------------------------------------------------------------------------- #

def test_panel_is_one_glass_pane_shelf():
    panel = _panel()
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        assert panel.isAncestorOf(panel._shelf)
    finally:
        _dispose(panel)


def test_shelf_never_registers_but_the_palette_stays_registered():
    """The rollout decision is preserved: the "Add blocks" palette is STILL the
    ONLY pane under this panel that opts into glass; the shelf and the hazard
    surface never do (registry ABSENCE, not a set_panel_glass equality)."""
    panel = _panel()
    try:
        registered = {
            id(p) for p in panel_kit.registered_glass_panes()
            if panel is p or panel.isAncestorOf(p)
        }
        # The palette is NOT registered: it hosts a QListWidget, and the Z4
        # census disqualifies list/table views by type (Mary's wave-boundary
        # rider; Adam's ruling 2026-07-14 — rule uniformity over one cosmetic
        # pane). Nothing under the planner registers for glass.
        assert id(panel._palette_card) not in registered
        assert registered == set()
        # The shelf is a content shell — it must NOT register.
        assert id(panel._shelf) not in registered
        assert panel._shelf.property("glassPane") in (None, "")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Hazard wrap — ArmLatch + Abort, opaque, never registered                     #
# --------------------------------------------------------------------------- #

def test_arm_latch_and_abort_wrapped_in_one_armed_hazard_surface():
    """The ArmLatch danger well AND the #dangerBtn Abort are a PURE PARENT-
    FRAME WRAP: both descendants of exactly one HazardSurface carrying the
    ``armed`` stripe, with the latch placed above the Abort."""
    panel = _panel()
    try:
        hazards = panel.findChildren(HazardSurface)
        assert len(hazards) == 1
        haz = hazards[0]
        assert haz is panel._hazard
        assert haz.objectName() == "hazardSurface"
        assert haz.stripe_kind() == "armed"

        # Both danger controls live under the one hazard surface.
        assert isinstance(panel._latch, ArmLatch)
        assert haz.isAncestorOf(panel._latch)
        assert haz.isAncestorOf(panel._btn_abort)
        assert panel._btn_abort.objectName() == "dangerBtn"

        # Relative placement preserved: latch above Abort in the hazard body.
        body = haz.body
        assert body.indexOf(panel._latch) < body.indexOf(panel._btn_abort)
    finally:
        _dispose(panel)


def test_hazard_surface_never_registers_and_stays_opaque_through_the_glass_switch():
    """Consequence rule (kit §4.6): a HazardSurface is opaque at EVERY tier —
    it is never in the registry, and flipping the panel-glass switch must never
    touch its pinned instance fill or add a glass property."""
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
        # Registry absence still holds with the switch ON.
        assert id(panel._hazard) not in {id(x) for x in panel_kit.registered_glass_panes()}
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_register_glass_pane_refuses_the_hazard_surface_outright():
    """Belt: even an explicit attempt to register the hazard surface is refused
    at construction time (kit consequence rule §4.6)."""
    panel = _panel()
    try:
        with pytest.raises(ValueError):
            panel_kit.register_glass_pane(panel._hazard)
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Abort enable-state discipline — UNCHANGED by the wrap                        #
# --------------------------------------------------------------------------- #

def test_abort_enable_state_is_driven_only_by_set_running_not_the_wrap():
    """The motor STOP-inside analysis (f86675d): wrapping Abort in the
    HazardSurface must not change its enabled-state behaviour. Abort is
    disabled at rest, enabled ONLY while running, and the hazard parent is
    never disabled (so no cascade sweeps Abort into a disabled state)."""
    panel = _panel()
    try:
        # At rest: Abort disabled (init), hazard surface enabled.
        assert panel._btn_abort.isEnabled() is False
        assert panel._hazard.isEnabled() is True

        # A run enables ONLY Abort among the danger controls.
        panel.set_running(True)
        assert panel._btn_abort.isEnabled() is True
        assert panel._hazard.isEnabled() is True   # parent never disabled

        # Run ends: Abort goes back to disabled — the same rule as before.
        panel.set_running(False)
        assert panel._btn_abort.isEnabled() is False
        assert panel._hazard.isEnabled() is True
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light re-resolves the hazard surface                #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light_round_trip():
    panel = _panel()
    try:
        for mode in ("light", "dark", "light"):
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
    panel.shutdown()   # idempotent — must not raise (the estimate thread joins)
    panel.deleteLater()


# --------------------------------------------------------------------------- #
# The render — both themes, TOKEN tier                                         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_planner_panel_both_themes(mode):
    app = _app()
    apply_theme(app, mode)
    panel = _panel()
    try:
        panel.refresh_theme(mode)

        panel.resize(960, max(640, panel.sizeHint().height()))
        panel.show()
        app.processEvents()

        img = panel.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"planner_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests
