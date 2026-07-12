"""Headless tests for the Reference Monitor panel (``gui/intensity_panel.py``),
cockpit v5 batch A: 2 tiles + one chip + waveform hero (design system §7).

Follows the existing gui test idiom: ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()`` helper, no pytest-qt, simulated backend only.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import dataclass

import numpy as np
from PySide6.QtWidgets import QApplication

from devices.intensity_simulated import SimulatedIntensityMonitor
from gui.intensity_panel import IntensityPanel
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@dataclass
class _Reading:
    amplitude_V: float = 0.05
    charge_pC: float = 1.234
    saturated: bool = False
    time_s: object = None
    waveform_V: object = None


def _panel() -> IntensityPanel:
    return IntensityPanel(SimulatedIntensityMonitor())


# --------------------------------------------------------------------------- #
# Construction + teardown                                                     #
# --------------------------------------------------------------------------- #

def test_construct_headless_no_hardware_and_shutdown():
    _app()
    panel = _panel()
    try:
        # Two tiles + one chip (§7) — both tiles honestly stale at start.
        assert len(panel._metrics.tiles()) == 2
        assert panel._tile_amp.is_stale()
        assert panel._tile_stab.is_stale()
        assert panel._chip_live.text() == "Monitor offline"
    finally:
        panel.shutdown()


def test_theme_switch_smoke():
    app = _app()
    apply_theme(app, "light")
    panel = _panel()
    try:
        apply_theme(app, "dark")
        assert not panel.grab().isNull()
        apply_theme(app, "light")
        assert not panel.grab().isNull()
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Reading -> tiles/chip                                                       #
# --------------------------------------------------------------------------- #

def test_reading_populates_amplitude_tile_with_charge_caption():
    _app()
    panel = _panel()
    try:
        panel._on_reading(_Reading(amplitude_V=0.05, charge_pC=1.234))
        assert panel._tile_amp.value() == "50.00 mV"
        assert not panel._tile_amp.is_stale()
        assert "1.234 pC" in panel._tile_amp._caption.text()
        assert panel._chip_live.text() == "Monitor live"
    finally:
        panel.shutdown()


def test_saturation_escalates_the_single_chip_to_warn():
    _app()
    panel = _panel()
    try:
        panel._on_reading(_Reading(saturated=True))
        assert panel._chip_live.text() == "Saturated"
        assert panel._chip_live.property("state") == "warn"
        panel._on_reading(_Reading(saturated=False))
        assert panel._chip_live.text() == "Monitor live"
    finally:
        panel.shutdown()


def test_offline_reading_goes_stale_not_frozen():
    _app()
    panel = _panel()
    try:
        panel._on_reading(_Reading())
        assert not panel._tile_amp.is_stale()
        panel._on_reading(None)
        # Law 4: value kept, ink stale, caption says why.
        assert panel._tile_amp.is_stale()
        assert "offline" in panel._tile_amp._caption.text()
        assert panel._chip_live.property("state") == "disconnected"
    finally:
        panel.shutdown()


def test_waveform_updates_curve():
    _app()
    panel = _panel()
    try:
        t = np.linspace(0, 1e-6, 32)
        v = np.sin(t * 1e7)
        panel._on_reading(_Reading(time_s=t, waveform_V=v))
        x, y = panel._curve.getData()
        assert len(x) == 32
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Stability check -> tile                                                     #
# --------------------------------------------------------------------------- #

def test_stability_check_lands_in_tile():
    _app()
    panel = _panel()
    try:
        panel._monitor.connect()   # simulated backend only
        panel._check_stability()
        assert panel._tile_stab.value().endswith("%")
        assert not panel._tile_stab.is_stale()
        assert "shots" in panel._tile_stab._caption.text()
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Hot-path rule 3 — no QGraphicsEffect on the waveform plot                   #
# --------------------------------------------------------------------------- #

def test_no_graphics_effect_on_waveform():
    _app()
    panel = _panel()
    try:
        assert panel._figure.graphicsEffect() is None
        assert panel._plot.graphicsEffect() is None
    finally:
        panel.shutdown()
