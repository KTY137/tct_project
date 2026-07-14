"""The PILOT panel — bias migrated onto the round-03 glass kit.

This is the beat that the whole panel wave is judged by (a hazard surface, HV,
detachable, live readouts).  It pins the migration's structure and, as a side
effect of the RENDERED-PIXEL idiom (`test_material_contract.py`, never a mock),
writes the offscreen PNGs Kaya judges the pilot by into
``artifacts_claude/pilot_bias/`` (both themes, TOKEN tier — glass-off is what
ships today).

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen,
simulated backends only):

  * the hero trio now sits on an OPAQUE ``HazardSurface`` (the stone in the
    glass room) whose ``#hazardSurface`` fill is the ``panel`` token and whose
    danger stripe resolves to the ``danger`` token, in BOTH themes;
  * every numeric input lives in an opaque ``Well`` (§4.4: "a value being typed
    is never on glass"), while the kill switch keeps its ``killSwitchBtn``
    identity and its energy-escalating chrome (the ceremony is untouched);
  * the panel opts NOTHING into the panel-glass switch (cross-checked here and
    pinned harder in ``test_panel_glass_rollout.test_bias_panel_opts_nothing_in``);
  * a live light↔dark switch re-resolves the hazard surface without a crash.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gui import panel_kit
from gui.bias_panel import BiasPanel
from gui.panel_kit import HazardSurface, Well
from gui.style import apply_theme, palette

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "pilot_bias"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dispose(panel) -> None:
    shutdown = getattr(panel, "shutdown", None)
    if shutdown is not None:
        shutdown()
    panel.deleteLater()


@dataclass
class _Reading:
    voltage_V: float
    current_A: float
    compliant: bool
    tripped: bool = False


class _FakeSupply:
    """Attribute-only stand-in (same idiom as the other bias_panel tests) so
    ``set_reading`` can be driven synchronously; never connects, never does I/O."""

    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.setpoint_V = -300.0
        self.compliance_A = 100e-6
        self.voltage_range_V = 1000.0
        self.channel = 0


# --------------------------------------------------------------------------- #
# Structure — the kit surfaces landed, and the hazard is a stone               #
# --------------------------------------------------------------------------- #

def test_hero_trio_is_wrapped_in_a_hazard_surface():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        # The trio's three tiles are descendants of exactly one HazardSurface.
        hazards = panel.findChildren(HazardSurface)
        assert len(hazards) == 1
        haz = hazards[0]
        for tile in (panel._tile_v, panel._tile_i, panel._tile_hv):
            assert haz.isAncestorOf(tile), "a hero tile floated off the hazard surface"
        assert haz.objectName() == "hazardSurface"
        assert haz.stripe_kind() == "danger"
    finally:
        _dispose(panel)


def test_numeric_inputs_live_in_wells():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        for spin in (panel._spin_comp, panel._spin_volt, panel._spin_step,
                     panel._spin_delay):
            parent = spin.parentWidget()
            assert isinstance(parent, Well), (
                f"{spin.objectName() or spin} is not in a Well (§4.4)")
    finally:
        _dispose(panel)


def test_kill_switch_ceremony_survives_the_migration():
    """The hazard boundary (Loki rider 5): the migration is a re-skin, so the
    kill switch keeps its identity and its energy-escalating chrome."""
    _app()
    supply = _FakeSupply(connected=True)
    panel = BiasPanel(supply)
    try:
        assert panel._btn_off.objectName() == "killSwitchBtn"
        panel.set_reading(_Reading(-300.0, 5e-6, False))
        assert panel._tile_hv.value() == "SETTLED"
        assert panel._btn_off.property("state") == "danger"   # red arrives with volts
    finally:
        _dispose(panel)


def test_pilot_bias_opts_nothing_into_glass():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        panel_kit.set_panel_glass(True)
        bias_panes = [p for p in panel_kit.registered_glass_panes()
                      if panel is p or panel.isAncestorOf(p)]
        assert bias_panes == [], "the HV safety dashboard must opt NOTHING into glass"
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


# --------------------------------------------------------------------------- #
# The render — both themes, TOKEN tier, into artifacts_claude/pilot_bias/      #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_bias_panel_both_themes(mode):
    """RENDERED-PIXEL smoke test (required for every panel change) that also
    saves the pilot PNG.  Drives the panel to a live-at-setpoint state so the
    render shows the hazard surface in its energised form (SETTLED + red kill
    switch) — the exact frame the pilot has to earn."""
    app = _app()
    apply_theme(app, mode)
    panel = BiasPanel(_FakeSupply(connected=True))
    try:
        panel.refresh_theme(mode)
        panel.set_reading(_Reading(-300.0, 45e-6, False))

        # The hazard surface renders its opaque token fill and danger stripe in
        # this theme — the two channels that must never depend on the tier.
        p = palette(mode)
        haz = panel.findChildren(HazardSurface)[0]
        assert f"background: {p['panel']}" in haz.styleSheet()
        assert haz._stripe_color.name().lower() == p["danger"].lower()

        # A representative DOCKED width (the bias tab is wide in a maximised
        # window).  On a very narrow torn-off panel the hero values ellipsize —
        # the trio now sits two card-paddings deep (shelf + hazard) — which is
        # MetricTile's fit-not-bleed behaviour, reported as a niggle.
        panel.resize(620, max(760, panel.sizeHint().height()))
        panel.show()
        app.processEvents()

        img = panel.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"bias_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests
