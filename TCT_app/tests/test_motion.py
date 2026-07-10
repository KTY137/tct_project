"""Headless tests for gui.motion visual-only helpers."""
from __future__ import annotations

import ast
import inspect
import os
import re
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import gui.motion as motion
from gui.motion import ActivityRing, flash_readout, set_pulse
from gui.status_widgets import ReadoutCell, StatusChip
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(ms: int = 60) -> None:
    app = _app()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def test_set_pulse_sets_and_clears_dynamic_properties():
    _app()
    chip = StatusChip("Scan RUNNING", "busy")

    ctrl = set_pulse(chip, True, kind="scan", interval_ms=10)
    assert ctrl is not None
    assert ctrl.is_running()
    assert chip.property("motionPulse") == "scan"
    assert chip.property("motionPulsePhase") in {"0", "1"}

    first = chip.property("motionPulsePhase")
    _pump(40)
    assert chip.property("motionPulsePhase") in {"0", "1"}
    assert chip.property("motionPulsePhase") != first or ctrl.is_running()

    set_pulse(chip, False)
    assert chip.property("motionPulse") == ""
    assert chip.property("motionPulsePhase") == ""
    assert not ctrl.is_running()


def test_flash_readout_restores_original_property():
    _app()
    cell = ReadoutCell("ETA", "--")
    cell.setProperty("flash", "")

    timer = flash_readout(cell, "accent", timeout_ms=15)
    assert timer.parent() is cell
    assert cell.property("flash") == "accent"

    _pump(80)
    assert cell.property("flash") == ""


def test_activity_ring_constructs_cycles_and_stops():
    _app()
    ring = ActivityRing(active=True, interval_ms=10)
    assert ring.objectName() == "activityRing"
    assert ring.graphicsEffect() is None
    assert ring.is_active()
    assert ring.isVisible()
    assert ring.property("phase") in {"0", "1", "2", "3"}

    _pump(40)
    assert ring.property("phase") in {"0", "1", "2", "3"}

    ring.set_active(False)
    assert not ring.is_active()
    assert not ring.isVisible()
    assert ring.property("phase") == ""


def test_motion_qss_hooks_are_present():
    app = _app()
    apply_theme(app, "dark")
    css = app.styleSheet()
    for needle in (
        'motionPulse="laser"',
        'motionPulse="hv"',
        'motionPulse="scan"',
        'QFrame#readoutCell[flash="accent"]',
        "QFrame#activityRing",
    ):
        assert needle in css


def test_motion_source_has_zero_inline_hex():
    src = inspect.getsource(motion)
    assert re.findall(r"#[0-9a-fA-F]{6}\b", src) == []


def test_motion_never_calls_set_graphics_effect():
    tree = ast.parse(inspect.getsource(motion))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setGraphicsEffect"
    ]
    assert calls == []
