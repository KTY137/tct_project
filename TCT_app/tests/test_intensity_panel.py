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
import pytest
from PySide6.QtWidgets import QApplication

from analysis.laser_normalization import normalise
from analysis.waveform_analysis import correct_baseline as _ana_correct_baseline
from devices.intensity_base import correct_baseline as _dev_correct_baseline
from devices.intensity_scope_ch import ScopeChannelMonitor
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


# --------------------------------------------------------------------------- #
# Reference-channel baseline subtraction (Beat D4).                            #
#                                                                             #
# The reference path in ScopeChannelMonitor used to compute amplitude/charge  #
# on the RAW trace: a DC offset on the reference channel biased every saved   #
# dut_charge_norm. These tests pin the fix (shared baseline formula) and the  #
# regression (norm invariant under a ref DC offset).                          #
# --------------------------------------------------------------------------- #

class _StubScope:
    """Minimal scope returning a fixed reference pulse plus a DC offset."""
    connected = True

    def __init__(self, offset_V: float = 0.0) -> None:
        self._t = np.linspace(-20e-9, 180e-9, 500)
        self._offset = offset_V

    def read_channel(self, channel: int):
        pulse = -0.1 * np.exp(-0.5 * ((self._t - 60e-9) / 8e-9) ** 2)
        return self._t, pulse + self._offset


def test_ref_amplitude_and_charge_are_baseline_corrected():
    """A DC offset on the reference channel must not change the reported
    amplitude or charge (read() and the get_* helpers all share the fix)."""
    mon0 = ScopeChannelMonitor(_StubScope(offset_V=0.0))
    mon_off = ScopeChannelMonitor(_StubScope(offset_V=0.20))   # +200 mV DC
    r0, r_off = mon0.read(), mon_off.read()
    assert r_off.amplitude_V == pytest.approx(r0.amplitude_V, rel=1e-9)
    assert r_off.charge_pC == pytest.approx(r0.charge_pC, rel=1e-9)
    assert mon_off.get_amplitude() == pytest.approx(mon0.get_amplitude(), rel=1e-9)
    assert mon_off.get_charge() == pytest.approx(mon0.get_charge(), rel=1e-9)
    # read() still returns the RAW trace (offset visible), only the metrics are
    # corrected — the panel plots what the scope actually saw.
    assert float(np.mean(r_off.waveform_V[:20])) == pytest.approx(0.20, abs=1e-9)


def test_ref_charge_would_differ_without_correction():
    """Guard against a degenerate pass: the uncorrected integral of the offset
    trace really is different, so the invariance above is the correction at
    work rather than a coincidental zero."""
    scope = _StubScope(offset_V=0.20)
    t, v = scope.read_channel(1)
    win = (t >= 20e-9) & (t <= 150e-9)
    raw_pC = float(np.trapz(v[win], t[win]) / 50.0 * 1e12)
    corrected_pC = ScopeChannelMonitor(scope).get_charge()
    assert raw_pC != pytest.approx(corrected_pC, rel=1e-3)


def test_device_baseline_mirror_matches_analysis():
    """The devices-layer baseline mirror is identical to the analysis canonical
    (duplicated only because devices/ may not import analysis/ — the three-layer
    law; test_layer_contracts enforces the ban, this pins the mirror equal)."""
    rng = np.random.default_rng(1)
    v = rng.normal(0.0, 1.0, 500) + 0.42
    for n in (5, 20, 50):
        dc, db, dr = _dev_correct_baseline(v, n)
        ac, ab, ar = _ana_correct_baseline(v, n)
        np.testing.assert_allclose(dc, ac)
        assert db == pytest.approx(ab)
        assert dr == pytest.approx(ar)


def test_simulated_monitor_default_offset_is_nonzero():
    """The simulated reference offset defaults nonzero so the bug class stays
    permanently exercised by the suite."""
    assert SimulatedIntensityMonitor()._baseline_offset_V != 0.0


def test_dut_charge_norm_invariant_under_injected_ref_offset():
    """THE regression: dut_charge_norm = Q_dut / Q_ref must not move when the
    simulated reference channel injects a DC offset. Before the fix the offset
    was integrated into Q_ref and biased every saved dut_charge_norm.

    Deterministic: drift/amplitude-noise off, and numpy seeded identically
    before each read so the two monitors draw the SAME waveform noise — the
    only difference is the injected DC offset, which the fix removes."""
    dut_charge_pC = 3.0
    common = dict(noise_frac=0.0, drift_rate_per_s=0.0)
    ref_clean = SimulatedIntensityMonitor(baseline_offset_V=0.0, **common)
    ref_offset = SimulatedIntensityMonitor(baseline_offset_V=0.05, **common)

    np.random.seed(0)
    q_ref_clean = ref_clean.get_charge()
    np.random.seed(0)
    q_ref_offset = ref_offset.get_charge()

    assert q_ref_offset == pytest.approx(q_ref_clean, rel=1e-6)
    assert normalise(dut_charge_pC, q_ref_offset) == pytest.approx(
        normalise(dut_charge_pC, q_ref_clean), rel=1e-6)
