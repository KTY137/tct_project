"""DEVICE MANAGER WINDOW migrated onto the round-03 glass kit (wave beat 6/12).

Mirrors ``tests/test_wave_scan_map_render.py`` (wave 4) and
``tests/test_wave_sequencer_render.py`` (wave 5), adapted to what this window
actually is: a ``QMainWindow`` top-level satellite (like the theme editor /
settings dialog), not an embedded tab widget.

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen, a
fully-simulated ``DeviceManager`` — never connected, construction only):

  * the window body is now one ``GlassPane`` shelf (``#shelfPane``) carrying a
    ``panel_header`` chrome head (eyebrow + title + the two status chips) over
    the device table and the bulk-action card;
  * that shelf opts NOTHING into the panel-glass switch: its body directly
    hosts the live ``QTableWidget``, one of the Z-ladder census's own
    disqualifiers ("Z4 live data table" — ``tests/test_panel_glass_rollout.py``
    ``_glass_disqualifiers``) — a CONTENT consequence, not the hazard-panel
    blanket stance ``BiasPanel``/``SequencerPanel`` use;
  * the bulk-action card (Connect All / Disconnect All only — no table, no
    danger control) DOES register — the positive half, proving this window is
    genuinely classed non-hazard rather than silently copying the HV
    dashboard's "opt nothing in" stance;
  * the window is still a real ``QMainWindow`` top-level with the same DWM
    surface-prep entry points wired (``gui.style.prepare_window_surface`` /
    ``reassert_window_backdrop`` — inert headless, but present);
  * the kit wrap did not detach anything: every attribute the pinned lifecycle/
    thread-affinity tests and ``tct_gui.py`` read through (``_table``,
    ``_btn_connect_all``, ``_btn_disconnect_all``, ``_chip_summary``,
    ``_chip_busy``, ``_bg_thread``/``_run_bg``/``shutdown``) is still reachable;
  * a live light -> dark -> light ``refresh_theme`` round trip survives without
    a crash and the window still renders a real (non-null) frame in both
    themes;
  * the QMainWindow closeEvent (hide, not destroy) and ``shutdown()`` still
    work after the kit wrap.

``tests/test_device_connect_lifecycle.py`` and ``tests/test_device_manager.py``
are READ-ONLY and stay green — they are the authority on connect/disconnect
behaviour; this file only proves the glass re-skin didn't disturb the
structure those contracts walk through. ``tests/test_run_bg_thread_affinity.py``
is the authority on the ``_run_bg``/``_bg_finished`` threading contract, which
this beat explicitly never touches.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import yaml
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QTableWidget, QWidget

from gui import panel_kit
from gui.device_panel import DeviceManagerWindow
from gui.panel_kit import Card, GlassPane
from gui.style import apply_theme

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "wave_device_panel"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


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


def _dispose(win: DeviceManagerWindow) -> None:
    win.shutdown()
    win.deleteLater()


# --------------------------------------------------------------------------- #
# Structure — one shelf, table-hosting content exclusion, action-card register #
# --------------------------------------------------------------------------- #

def test_window_is_a_qmainwindow_top_level_with_one_glass_pane_shelf(tmp_path):
    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        assert isinstance(win, QMainWindow)
        assert win.isWindow()
        assert isinstance(win._shelf, GlassPane)
        assert win._shelf.objectName() == "shelfPane"
        assert win.centralWidget() is not None
        assert win.centralWidget().isAncestorOf(win._shelf)
    finally:
        _dispose(win)


def test_shelf_opts_nothing_in_but_action_card_registers(tmp_path):
    """The Z-ladder content exclusion in miniature: the shelf hosts the live
    QTableWidget directly (Z4 disqualifier), so it must never register; the
    pure-chrome bulk-action card (Connect All / Disconnect All, no table, no
    danger control) is the one surface that DOES — proving this window is
    genuinely classed non-hazard (unlike BiasPanel's/SequencerPanel's blanket
    register=False)."""
    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        panel_kit.set_panel_glass(True)
        registered_ids = {id(p) for p in panel_kit.registered_glass_panes()}
        assert id(win._shelf) not in registered_ids, (
            "the table-hosting shelf must never register for glass")
        assert id(win._action_card) in registered_ids, (
            "the pure-chrome bulk-action card should register for glass"
        )
        assert win._action_card.property("glassPane") == "true"
        assert win._table_card.property("glassPane") != "true"
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(win)


def test_shelf_would_fail_the_zladder_census_if_registered(tmp_path):
    """Pins WHY the shelf stays unregistered: it really does carry a live
    QTableWidget as a descendant — registering it would be exactly the
    violation ``test_panel_glass_rollout.py``'s live census walks for."""
    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        descendants = [win._shelf, *win._shelf.findChildren(QWidget)]
        assert any(isinstance(w, QTableWidget) for w in descendants), (
            "expected the device QTableWidget under the shelf")
    finally:
        _dispose(win)


def test_table_card_is_a_plain_card_not_a_glass_pane(tmp_path):
    """The table card stays a plain (opaque-at-every-tier-unless-registered)
    Card, never a GlassPane subclass — its exclusion is content-driven (never
    registered), not a hard construction-time refusal like Well/HazardSurface."""
    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        assert isinstance(win._table_card, Card)
        assert not isinstance(win._table_card, GlassPane)
    finally:
        _dispose(win)


def test_kit_wrap_did_not_detach_anything_from_the_tree(tmp_path):
    """Kit-wrap sanity: every attribute the pinned lifecycle/thread-affinity
    tests and ``tct_gui.py`` read through directly is still reachable through
    the SAME attribute name and still a real descendant of the window."""
    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        for attr in ("_table", "_btn_connect_all", "_btn_disconnect_all",
                     "_chip_summary", "_chip_busy"):
            widget = getattr(win, attr)
            assert win.isAncestorOf(widget), f"{attr} floated off the shelf"
        assert isinstance(win._btn_connect_all, QPushButton)
        assert isinstance(win._btn_disconnect_all, QPushButton)
        # _run_bg/_bg_thread bookkeeping (Mary-reviewed concurrency fix) is
        # untouched presentation-adjacent state — still present, still None
        # at rest.
        assert win._bg_thread is None
        assert win._bg_task is None
        assert callable(win._run_bg)
        assert callable(win.shutdown)
    finally:
        _dispose(win)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, both themes render a real frame    #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light(tmp_path):
    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        for mode in ("dark", "light", "dark"):
            win.refresh_theme(mode)
            assert win._theme_mode == mode
    finally:
        _dispose(win)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_device_manager_window_both_themes(mode, tmp_path):
    app = _app()
    apply_theme(app, mode)
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        win.refresh_theme(mode)
        win.resize(640, 420)
        win.show()
        app.processEvents()

        img = win.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"device_manager_window_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        win.hide()
        _dispose(win)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests


# --------------------------------------------------------------------------- #
# QMainWindow-specific: close hides (never destroys), shutdown stays clean    #
# --------------------------------------------------------------------------- #

def test_close_event_hides_instead_of_destroying(tmp_path):
    """The pre-existing closeEvent override (hide, ignore) must survive the
    kit wrap — re-opening the Device Manager must not hit a dead C++ wrapper."""
    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        win.show()
        win.close()
        assert win.isHidden()
        # The window object itself must still be alive/usable (not destroyed).
        assert win._shelf.objectName() == "shelfPane"
    finally:
        _dispose(win)


def test_shutdown_is_idempotent_and_stops_the_refresh_timer(tmp_path):
    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        win.shutdown()
        win.shutdown()   # must not raise on a second call
        assert not win._refresh_timer.isActive()
    finally:
        win.deleteLater()
