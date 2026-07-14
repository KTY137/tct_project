"""LASER panel migrated onto the round-03 glass kit (panel wave beat).

Mirrors ``tests/test_pilot_bias_render.py`` (the pilot) and
``tests/test_wave_stage_view_render.py`` minimally, adapted to what this
panel actually is: the census classed it **non-hazard** — the wavegen is the
real (software-controlled) trigger control, the PDL 800 head is a
metadata-only honesty banner (law 7, no software emission switch).

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen,
simulated ``WaveformGenerator`` only — never connected):

  * the panel is now one ``GlassPane`` shelf (``#shelfPane``) carrying a
    ``panel_header`` chrome head, the status-chip row, the manual-laser
    honesty banner, the wavegen hero card and the PDL metadata card;
  * register decision: ONLY the PDL metadata card opts into glass (pure
    bookkeeping chrome).  The shelf itself, the wavegen card (hosts the
    "Output on" ARMED trigger button, objectName ``armedBtn``) and the
    manual-laser banner (hazard-ink amber, Völundr G1) are all excluded —
    same shape ``tests/test_panel_glass_rollout.py`` already pins for this
    panel, cross-checked here as the wave's own render test;
  * numeric/text inputs (the wavegen spins, the PDL wavelength/power/
    attenuation/notes fields) recess into an opaque ``Well`` (§4.4); the
    selection combos (rep. mode, pulse spec, output load) are NOT wells —
    they stay direct form-row widgets;
  * a live light -> dark -> light switch re-resolves the panel's cached
    theme tokens (``_restyle_theme_tokens``: axis rails + the banner's amber
    ink) without a crash and renders a non-null frame in both themes.

``tests/test_laser_panel_output_state.py`` and
``tests/test_laser_panel_worker.py`` are READ-ONLY and stay green untouched —
they are the authority on the output-chip/worker-thread behaviour; this file
only proves the glass re-skin did not disturb the structure/behaviour they
walk through.
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
from gui.panel_kit import GlassPane, Well
from gui.style import apply_theme

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
    """The register decision: non-hazard census, but the shelf's body directly
    hosts an ARMED control (the wavegen's "Output on") and a hazard-ink
    honesty banner, so the shelf and both of those cards are excluded — only
    the pure-chrome PDL metadata card opts in.  Mirrors
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
