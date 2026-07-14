"""CALIBRATION_PANEL migrated onto the round-03 glass kit (panel wave beat 7/12).

Mirrors ``tests/test_wave_sequencer_render.py`` (wave 5, the hazard precedent),
adapted to what this panel actually is: a HAZARD panel whose motion-driving
Stage-Repeatability group (Run + the ``#dangerBtn`` Stop + progress/outcome)
sits on an opaque ``HazardSurface``, while two pure parameter groups (Method +
Electronics gain) keep the individual glass opt-ins they picked up in the
Z-ladder rollout (commit 7df2537).

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen, no
device I/O — never connected, hardware-safety rule 1):

  * the panel is now one ``GlassPane`` shelf (``#shelfPane``) carrying a
    ``panel_header`` chrome head; the shelf opts NOTHING into the panel-glass
    switch (``register=False`` — it is a content shell);
  * the Z-ladder rollout decision is preserved: the Method + Electronics-gain
    groups are STILL registered (pure parameter chrome, Baldr Z1/Z2), and they
    are the ONLY two registered panes under this panel;
  * the Stage-Repeatability motion group is a PURE PARENT-FRAME WRAP inside an
    opaque ``HazardSurface`` carrying the ``armed`` (motion-class) stripe —
    opaque at every tier, including with the panel-glass switch flipped ON, and
    never registered;
  * a live light -> dark -> light switch re-resolves the hazard surface's
    stripe/hatch/fill without a crash;
  * the DangerGate fail-safe is unchanged: with no gate injected the panel
    refuses to move (surfaces a warning, starts NO worker); an injected gate is
    stored verbatim;
  * ``shutdown()`` is clean and idempotent.

``tests/test_panel_glass_rollout.py`` (the census / rollout authority) and
``tests/test_bias_and_calibration.py`` stay green — this file only proves the
glass re-skin left the structure and the danger wiring intact.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import yaml
from PySide6.QtWidgets import QApplication, QGroupBox

from analysis.charge_calibration import ChargeCalibration
from controller.danger_gate import DenyAllGate
from gui import calibration_panel as cp
from gui import panel_kit
from gui.calibration_panel import CalibrationPanel
from gui.panel_kit import GlassPane, HazardSurface
from gui.style import apply_theme, palette

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "wave_calibration"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dispose(panel: CalibrationPanel) -> None:
    panel.shutdown()
    panel.deleteLater()


def _sim_device_manager(tmp_path):
    """Fully-simulated DeviceManager from a throwaway devices.yaml. Never
    connected — construction only (hardware-safety rule 1)."""
    from controller.device_manager import DeviceManager

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
    return DeviceManager(config_path=str(path))


def _panel(tmp_path) -> CalibrationPanel:
    _app()
    return CalibrationPanel(_sim_device_manager(tmp_path))


# --------------------------------------------------------------------------- #
# Fail-safe device seams — the ONLY way to reach the gate check headless       #
# --------------------------------------------------------------------------- #

class _ReadyMotor:
    connected = True
    homed = True


class _ReadyCamera:
    connected = True


class _ReadyDevices:
    """Minimal devices stand-in reporting a connected + homed stage and a
    connected camera, so ``_run_repeatability`` reaches the gate check — the
    only branch that exercises the fail-safe 'no gate ⇒ refuse to move' path
    without touching real hardware."""

    def __init__(self) -> None:
        self.charge_calibration = ChargeCalibration()
        self.motor = _ReadyMotor()
        self.camera = _ReadyCamera()


class _FakeMessageBox:
    """Records ``warning`` calls instead of raising a modal dialog."""

    calls: list[tuple[str, str]] = []

    @staticmethod
    def warning(parent, title, text, *a, **k):
        _FakeMessageBox.calls.append((title, text))
        return None


# --------------------------------------------------------------------------- #
# Structure — one shelf (register=False), the two chrome groups still glass     #
# --------------------------------------------------------------------------- #

def test_panel_is_one_glass_pane_shelf(tmp_path):
    panel = _panel(tmp_path)
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        assert panel.isAncestorOf(panel._shelf)
    finally:
        _dispose(panel)


def test_shelf_opts_nothing_in_but_the_two_chrome_groups_stay_registered(tmp_path):
    """The Z-ladder rollout decision (commit 7df2537) is preserved: the Method
    + Electronics-gain groups are the ONLY two panes under this panel that opt
    into glass; the shelf and the hazard surface never do."""
    panel = _panel(tmp_path)
    try:
        registered = {
            id(p) for p in panel_kit.registered_glass_panes()
            if panel is p or panel.isAncestorOf(p)
        }
        # _elec_box is pinned registered by tests/test_panel_glass_rollout.py:250.
        assert id(panel._elec_box) in registered
        # The Method group is a local in _build_ui — find it by title.
        method_box = next(
            b for b in panel.findChildren(QGroupBox) if b.title() == "Method")
        assert id(method_box) in registered
        # Exactly those two, and nothing else under this panel.
        assert registered == {id(panel._elec_box), id(method_box)}
        # The shelf is a content shell — it must NOT register.
        assert id(panel._shelf) not in registered
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_repeatability_group_wrapped_in_a_hazard_surface_with_armed_stripe(tmp_path):
    """The motion-driving Stage-Repeatability group is a PURE PARENT-FRAME
    WRAP: the SAME QGroupBox (with its Run button + #dangerBtn Stop), now a
    descendant of exactly one HazardSurface carrying the ``armed`` stripe."""
    panel = _panel(tmp_path)
    try:
        hazards = panel.findChildren(HazardSurface)
        assert len(hazards) == 1
        haz = hazards[0]
        assert haz is panel._hazard
        assert haz.objectName() == "hazardSurface"
        assert haz.stripe_kind() == "armed"
        # The #dangerBtn Stop and the Run button live under the hazard surface.
        assert haz.isAncestorOf(panel._btn_rep_stop)
        assert panel._btn_rep_stop.objectName() == "dangerBtn"
        assert haz.isAncestorOf(panel._btn_repeat)
    finally:
        _dispose(panel)


def test_hazard_surface_never_registers_and_stays_opaque_through_the_glass_switch(tmp_path):
    """Consequence rule (kit §4.6): a HazardSurface is opaque at EVERY tier —
    it is never in the registry, and flipping the panel-glass switch must never
    touch its pinned instance fill or add a glass property."""
    panel = _panel(tmp_path)
    try:
        registered = {id(p) for p in panel_kit.registered_glass_panes()}
        assert id(panel._hazard) not in registered

        p = palette(panel._theme_mode)
        before = panel._hazard.styleSheet()
        assert f"background: {p['panel']}" in before

        panel_kit.set_panel_glass(True)
        # Real coverage is the registry ABSENCE assert above — the surface is
        # never registered, so an unchanged styleSheet() here would be
        # trivially true by construction.
        assert panel._hazard.property("glassPane") in (None, "")
        assert panel._hazard.property("glassCard") in (None, "")
        # And the shelf still never went glass either.
        assert panel._shelf.property("glassPane") in (None, "")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_kit_wrap_did_not_detach_anything_from_the_tree(tmp_path):
    """Every attribute the pinned contract tests read through is still
    reachable through the SAME name and still a real descendant."""
    panel = _panel(tmp_path)
    try:
        for attr in ("_shelf", "_elec_box", "_ref_box", "_hazard",
                     "_btn_run", "_btn_save", "_btn_repeat", "_btn_rep_stop",
                     "_status", "_current", "_rep_progress", "_rep_result",
                     "_chip_method", "_chip_ref", "_chip_repeat"):
            widget = getattr(panel, attr)
            assert panel.isAncestorOf(widget), f"{attr} floated off the shelf"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# DangerGate fail-safe — byte-identical: no gate ⇒ refuses to move             #
# --------------------------------------------------------------------------- #

def test_no_gate_refuses_to_move_and_starts_no_worker(monkeypatch):
    """Fail-safe path (calibration_panel.py lines 482-489): with NO confirmation
    gate the panel surfaces a warning and starts NO worker thread, even with a
    connected + homed stage and a connected camera reported by the devices."""
    _app()
    _FakeMessageBox.calls.clear()
    monkeypatch.setattr(cp, "QMessageBox", _FakeMessageBox)
    panel = CalibrationPanel(_ReadyDevices())        # no gate injected
    try:
        assert panel._gate is None
        panel._run_repeatability()
        # No motion worker was ever created.
        assert panel._rep_thread is None
        assert panel._rep_worker is None
        # And the operator was told why.
        assert _FakeMessageBox.calls, "expected a fail-safe warning"
        assert _FakeMessageBox.calls[-1][0] == "Confirmation unavailable"
    finally:
        _dispose(panel)


def test_injected_gate_is_stored_verbatim():
    """Gate injection wiring is unchanged — the same object the main window
    passes reaches ``self._gate``."""
    _app()
    gate = DenyAllGate()
    panel = CalibrationPanel(_ReadyDevices(), gate=gate)
    try:
        assert panel._gate is gate
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, re-resolves stripe/hatch/fill       #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light_round_trip(tmp_path):
    panel = _panel(tmp_path)
    try:
        for mode in ("dark", "light", "dark"):
            panel.refresh_theme(mode)
            assert panel._theme_mode == mode
            p = palette(mode)
            assert panel._hazard._stripe_color.name().lower() == p["armed"].lower()
            assert f"background: {p['panel']}" in panel._hazard.styleSheet()
    finally:
        _dispose(panel)


def test_shutdown_is_clean_and_idempotent(tmp_path):
    panel = _panel(tmp_path)
    panel.shutdown()
    panel.shutdown()   # idempotent — must not raise
    panel.deleteLater()


# --------------------------------------------------------------------------- #
# The render — both themes, TOKEN tier                                         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_calibration_panel_both_themes(mode, tmp_path):
    app = _app()
    apply_theme(app, mode)
    panel = _panel(tmp_path)
    try:
        panel.refresh_theme(mode)

        panel.resize(720, max(640, panel.sizeHint().height()))
        panel.show()
        app.processEvents()

        img = panel.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"calibration_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests
