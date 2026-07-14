"""LASER panel migrated onto the round-03 glass kit (panel wave beat), plus the
2026-07-15 HAZARD reclassification (lab-safety beat, Kaya-approved).

Mirrors ``tests/test_pilot_bias_render.py`` (the pilot) and
``tests/test_wave_calibration_render.py`` (the hazard precedent). The panel is
a HAZARD panel: the wavegen's "Output on" button (``armedBtn``) is the REAL
PDL 800 trigger path (wavegen output → laser trigger input = emission), so the
emission-arming cluster sits on an opaque ``HazardSurface`` and arming
confirms through the injected ``DangerGate`` (see the gate tests in
``tests/test_laser_panel_output_state.py``).

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen,
simulated ``WaveformGenerator`` only — never connected):

  * the panel is one ``GlassPane`` shelf (``#shelfPane``) carrying a
    ``panel_header`` chrome head, the status-chip row, the manual-laser
    honesty banner, the wavegen hero card and the PDL metadata card;
  * register decision: ONLY the PDL metadata card opts into glass (pure
    bookkeeping chrome — the reclassification ruling KEEPS it, its content is
    metadata, nothing emission-related).  The shelf itself, the wavegen card
    (hosts the "Output on" ARMED trigger button, objectName ``armedBtn``) and
    the manual-laser banner (hazard-ink amber, Völundr G1) are all excluded —
    same shape ``tests/test_panel_glass_rollout.py`` already pins for this
    panel, cross-checked here as the wave's own render test;
  * the emission-arming cluster (Output on/off) is a PURE PARENT-FRAME WRAP
    inside an opaque ``HazardSurface`` carrying the ``armed`` stripe — opaque
    at every tier, including with the panel-glass switch flipped ON, and never
    registered;
  * numeric/text inputs (the wavegen spins, the PDL wavelength/power/
    attenuation/notes fields) recess into an opaque ``Well`` (§4.4); the
    selection combos (rep. mode, pulse spec, output load) are NOT wells —
    they stay direct form-row widgets;
  * a live light -> dark -> light switch re-resolves the panel's cached
    theme tokens (``_restyle_theme_tokens``: axis rails + the banner's amber
    ink + the hazard surface's stripe/fill) without a crash and renders a
    non-null frame in both themes.

``tests/test_laser_panel_output_state.py`` (now also the gate-behaviour
authority) and ``tests/test_laser_panel_worker.py`` cover the
output-chip/worker-thread/gate behaviour; this file proves the structure the
glass re-skin + hazard wrap produced.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from devices.laser_manual import LaserManualMetadata
from devices.waveform_generator import WaveformGenerator
from gui import panel_kit
from gui.laser_panel import LaserPanel
from gui.panel_kit import GlassPane, HazardSurface, Well
from gui.style import apply_theme, palette

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "wave_laser"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel(wfg: WaveformGenerator | None = None) -> LaserPanel:
    return LaserPanel(LaserManualMetadata(), wfg or WaveformGenerator(simulation=True))


def _dispose(panel: LaserPanel) -> None:
    shutdown = getattr(panel, "shutdown", None)
    if shutdown is not None:
        shutdown()
    panel.deleteLater()


# --------------------------------------------------------------------------- #
# Structure — one shelf, register decisions, nothing detached                 #
# --------------------------------------------------------------------------- #

def test_panel_is_one_glass_pane_shelf():
    _app()
    panel = _panel()
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        assert panel.isAncestorOf(panel._shelf)
        # Every original surface still lives on the shelf (nothing detached).
        for card in (panel._banner_card, panel._card_wfg, panel._card_pdl):
            assert panel._shelf.isAncestorOf(card)
    finally:
        _dispose(panel)


def test_only_the_pdl_card_registers_for_glass():
    """The register decision on a HAZARD panel: the shelf's body directly hosts
    an ARMED control (the wavegen's "Output on") and a hazard-ink honesty
    banner, so the shelf and both of those cards are excluded — only the
    pure-chrome PDL metadata card opts in (the reclassification ruling KEEPS
    it).  Mirrors
    ``test_panel_glass_rollout.test_hazard_and_data_panes_are_never_registered``
    / ``test_wired_panels_register_their_chrome_panes`` for this same panel."""
    _app()
    panel = _panel()
    try:
        panel_kit.set_panel_glass(True)
        ours = [p for p in panel_kit.registered_glass_panes()
                if panel is p or panel.isAncestorOf(p)]
        assert ours == [panel._card_pdl], (
            f"expected only the PDL metadata card to register, got {ours}")
        assert panel._card_pdl.property("glassPane") == "true"

        # The exclusions, with their reasons made explicit and load-bearing:
        assert panel._btn_on.objectName() == "armedBtn"
        assert panel._card_wfg.isAncestorOf(panel._btn_on)
        assert panel._banner_card.property("bannerKind") == "laserManual"
        for denied, why in (
            (panel._shelf, "hosts an armed control + a hazard banner descendant"),
            (panel._card_wfg, "hosts the Output-on ARMED trigger button"),
            (panel._banner_card, "hazard-ink amber honesty surface (Völundr G1)"),
        ):
            assert denied not in ours, f"{denied} must not register: {why}"
            assert not denied.property("glassPane"), f"{denied} must not go glass: {why}"
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_emission_cluster_wrapped_in_a_hazard_surface_with_armed_stripe():
    """HAZARD reclassification: the Output on/off cluster is a PURE PARENT-FRAME
    WRAP inside exactly one ``HazardSurface`` carrying the ``armed`` stripe —
    the buttons keep their identity, only the container changed."""
    _app()
    panel = _panel()
    try:
        hazards = panel.findChildren(HazardSurface)
        assert len(hazards) == 1
        haz = hazards[0]
        assert haz is panel._hazard
        assert haz.objectName() == "hazardSurface"
        assert haz.stripe_kind() == "armed"
        # Both output buttons live under the hazard surface.
        assert haz.isAncestorOf(panel._btn_on)
        assert haz.isAncestorOf(panel._btn_off)
        assert panel._btn_on.objectName() == "armedBtn"
        # The hazard surface itself is nested inside the wavegen hero card.
        assert panel._card_wfg.isAncestorOf(haz)
    finally:
        _dispose(panel)


def test_hazard_surface_never_registers_and_stays_opaque_through_the_glass_switch():
    """Consequence rule (kit §4.6): a HazardSurface is opaque at EVERY tier —
    never in the registry, and flipping the panel-glass switch must never touch
    its pinned instance fill or add a glass property."""
    _app()
    panel = _panel()
    try:
        panel_kit.set_panel_glass(True)
        registered = {id(p) for p in panel_kit.registered_glass_panes()}
        assert id(panel._hazard) not in registered

        p = palette(panel._theme_mode)
        before = panel._hazard.styleSheet()
        assert f"background: {p['panel']}" in before
        assert not panel._hazard.property("glassPane")

        # Toggling the switch OFF then ON must not disturb the pinned fill.
        panel_kit.set_panel_glass(False)
        panel_kit.set_panel_glass(True)
        assert panel._hazard.styleSheet() == before
        assert not panel._hazard.property("glassPane")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_numeric_text_inputs_live_in_wells():
    _app()
    panel = _panel()
    try:
        for widget in (
            panel._ed_wavelength, panel._ed_power, panel._ed_atten, panel._ed_notes,
            panel._spin_freq, panel._spin_width, panel._spin_duty,
            panel._spin_ampl, panel._spin_offset,
        ):
            parent = widget.parentWidget()
            assert isinstance(parent, Well), (
                f"{widget.objectName() or widget} is not in a Well (§4.4)")
        # Selection combos are NOT typed values — they stay direct form-row
        # widgets, per the copy-handoff's "numeric/text inputs" scope.
        for combo in (panel._ed_rep_mode, panel._pulse_mode, panel._load_combo):
            assert not isinstance(combo.parentWidget(), Well), (
                f"{combo.objectName() or combo} is a selection, not a well")
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, both themes render a real frame    #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light():
    _app()
    panel = _panel()
    try:
        for mode in ("dark", "light", "dark"):
            panel.refresh_theme(mode)
            assert panel._theme_mode == mode
    finally:
        _dispose(panel)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_laser_panel_both_themes(mode):
    app = _app()
    apply_theme(app, mode)
    panel = _panel()
    try:
        panel.refresh_theme(mode)

        panel.resize(560, max(760, panel.sizeHint().height()))
        panel.show()
        app.processEvents()

        img = panel.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"laser_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests
