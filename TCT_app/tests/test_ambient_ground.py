"""THE GROUND BAND, PINNED BY RENDERING — round-03 kit §1.1.

Baldr's correction pass proved the kit's "GROUND_TINT_ALPHA_MAX = 0.07 ⇒
ΔL* ≤ 4.0" arithmetic UNPROVEN — and it is in fact FALSE on the dark canvas
(the accent at the full 0.07 budget measures ΔL* 4.45; the top-left corner
stack ~5.5). gui/style.py therefore CLAMPS the wash by measurement. This file
is the independent check the brief demanded: it renders the ACTUAL shipped
wash pixmap offscreen, composites it over the live canvas token, and measures
the real ΔL* band with its own vectorised colour math (numpy — none of
style.py's L* helpers are reused, so a bug there cannot vouch for itself).

If the wash ever exceeds the band: clamp the wash, never this test.

Also covered: the alpha budget on the real artifact (kit §1.1's summed-alpha
law), the size-bucket × theme × DPR pixmap cache (the "zero cost at 15-30 Hz"
discipline — the paint path is a cached blit, never procedural), and the
AmbientGround widget's contract (layer 0 under every sibling, input-
transparent, tier-wired through gui/glass_env's ONE ladder, FLAT paints
nothing, no effects, no timers).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from gui import style
from gui.glass_env import GlassTier
from gui.panel_kit import AmbientGround

GROUND_BAND_MAX = 4.0                      # kit §1.1 — the law


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# Independent, vectorised L* measurement                                      #
# --------------------------------------------------------------------------- #

def _image_lstar(img: QImage) -> np.ndarray:
    """Per-pixel CIE L* of an opaque QImage, vectorised."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8)
    px = buf.reshape(h, img.bytesPerLine() // 4, 4)[:, :w, :]
    # ARGB32 on little-endian is B,G,R,A in memory.
    b, g, r = (px[..., 0].astype(np.float64), px[..., 1].astype(np.float64),
               px[..., 2].astype(np.float64))

    def lin(c):
        c = c / 255.0
        return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

    y = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    knee = (6 / 29) ** 3
    return np.where(y > knee, 116.0 * np.cbrt(y) - 16.0, y * (29 / 3) ** 3)


def _composited_band(mode: str, w: int = 640, h: int = 400) -> tuple[float, float]:
    """(max ΔL*, canvas L*) of the SHIPPED wash pixmap composited over the
    live canvas token — the exact stack AmbientGround paints."""
    p = style.palette(mode)
    pm = style.ground_pixmap(w, h, mode, 1.0)
    base = QImage(pm.width(), pm.height(), QImage.Format.Format_ARGB32)
    base.fill(QColor(p["canvas"]))
    painter = QPainter(base)
    painter.drawPixmap(0, 0, pm)
    painter.end()
    lstars = _image_lstar(base)
    canvas = QColor(p["canvas"])
    c = canvas.getRgb()[:3]

    def lin1(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    y = 0.2126 * lin1(c[0]) + 0.7152 * lin1(c[1]) + 0.0722 * lin1(c[2])
    canvas_l = 116.0 * y ** (1 / 3) - 16.0 if y > (6 / 29) ** 3 else y * (29 / 3) ** 3
    return float(np.abs(lstars - canvas_l).max()), float(canvas_l)


# --------------------------------------------------------------------------- #
# 1. The band law, measured on the real artifact                              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_ground_band_law_holds_for_the_shipped_wash(mode):
    """No pixel of the ground may deviate from `canvas` by more than ΔL* 4.0
    (kit §1.1) — measured on the real render, not derived from the alpha
    budget (which Baldr proved insufficient on its own)."""
    band, _canvas_l = _composited_band(mode)
    assert band <= GROUND_BAND_MAX, (
        f"[{mode}] rendered ground band ΔL* {band:.2f} exceeds the §1.1 law — "
        f"clamp the WASH in gui/style.py, never this test")


@pytest.mark.parametrize("mode,floor", [("dark", 2.0), ("light", 0.8)])
def test_the_wash_actually_exists(mode, floor):
    """A clamp that collapses the wash to nothing would also 'pass' the band
    law — pin that the ambience is real (dark ships near the band; light is
    quieter by arithmetic, kit §2.1's own admission)."""
    band, _ = _composited_band(mode)
    assert band >= floor, f"[{mode}] wash band ΔL* {band:.2f} — ground is gone"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_wash_alpha_budget_on_the_real_artifact(mode):
    """kit §1.1's other half: the SUMMED wash alpha at any single pixel stays
    inside GROUND_TINT_ALPHA_MAX (before the measured clamp shrinks it
    further). Measured on the shipped pixmap's own alpha channel."""
    pm = style.ground_pixmap(512, 320, mode, 1.0)
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    buf = np.frombuffer(img.constBits(), dtype=np.uint8)
    alpha = buf.reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), 3]
    budget = round(style.GROUND_TINT_ALPHA_MAX * 255) + 1   # +1: 8-bit rounding
    assert int(alpha.max()) <= budget, (
        f"[{mode}] wash alpha peaks at {int(alpha.max())}/255 — over the "
        f"summed budget {budget}/255")


def test_the_dark_wash_is_clamped_below_the_naive_budget():
    """The Baldr finding, pinned: the naive 0.07 budget over the dark canvas
    breaks the band, so the shipped dark wash must carry a measured clamp
    scale < 1.0. If a future palette makes the full budget legal, this test
    documents that the clamp has (legitimately) become a no-op — update it
    with the new measurement."""
    assert style._ground_clamp_scale("dark") < 1.0
    assert style._ground_clamp_scale("light") == 1.0


# --------------------------------------------------------------------------- #
# 2. The cache — the 15-30 Hz discipline                                      #
# --------------------------------------------------------------------------- #

def test_pixmap_is_cached_per_size_bucket_theme_and_dpr():
    _app()
    a = style.ground_pixmap(500, 300, "dark", 1.0)
    b = style.ground_pixmap(510, 310, "dark", 1.0)   # same 256-px bucket
    assert a is b, "same bucket must be a cache hit (zero re-render)"
    c = style.ground_pixmap(500, 300, "light", 1.0)
    assert c is not a
    d = style.ground_pixmap(500, 300, "dark", 2.0)
    assert d is not a
    assert d.devicePixelRatio() == pytest.approx(2.0)
    # Bucketing: ceil to the next _GROUND_BUCKET_PX step, never below one step.
    assert a.width() == 512 and a.height() == 512
    tiny = style.ground_pixmap(40, 20, "dark", 1.0)
    assert tiny.width() == style._GROUND_BUCKET_PX


def test_ground_never_uses_a_semantic_token():
    """kit §1.2: the ground is tinted only with `accent` and neutrals. The
    wash render must not change when a (non-safety) semantic-adjacent token
    can't be probed — so pin it structurally: the cache key and clamp key use
    only canvas + accent."""
    p = style.palette("dark")
    style.ground_pixmap(300, 200, "dark", 1.0)
    keys = [k for k in style._ground_pixmaps if k[2] == "dark"]
    assert keys, "expected a cached dark ground entry"
    for key in keys:
        assert p["canvas"] in key and p["accent"] in key
        for tok in ("danger", "armed", "good", "sim", "warn", "crit", "error"):
            assert p[tok] not in key


# --------------------------------------------------------------------------- #
# 3. The AmbientGround widget contract                                        #
# --------------------------------------------------------------------------- #

def _host(mode: str = "dark") -> tuple[QWidget, AmbientGround]:
    _app()
    p = style.palette(mode)
    host = QWidget()
    host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    host.setStyleSheet(f"background: {p['canvas']};")
    host.resize(320, 240)
    ground = AmbientGround(host, theme_mode=mode)
    host.show()
    return host, ground


def test_ground_widget_is_layer0_input_transparent_and_effect_free():
    host, ground = _host()
    try:
        assert ground.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert ground.graphicsEffect() is None            # hard rule 3
        assert not ground.findChildren(QTimer)            # never animates (§1.2)
        assert ground.geometry() == host.rect()
        host.resize(500, 400)
        _app().processEvents()
        assert ground.geometry() == host.rect()           # tracks the canvas
    finally:
        host.deleteLater()


def test_ground_widget_stays_under_late_built_siblings():
    """A sibling panel built AFTER the ground must paint on top of it —
    childAt() must find the sibling, and a grab over the sibling's rect must
    show the sibling's fill, not the wash."""
    host, ground = _host()
    try:
        p = style.palette("dark")
        panel = QWidget(host)
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setStyleSheet(f"background: {p['raised']};")
        panel.setGeometry(0, 0, 320, 240)
        panel.show()
        _app().processEvents()
        img = host.grab().toImage()
        got = img.pixelColor(10, 10).name().lower()
        assert got == p["raised"].lower(), (
            f"sibling not on top of the ground wash: {got}")
        # Input transparency: hit-testing lands on the sibling, never the wash.
        assert host.childAt(10, 10) is panel
    finally:
        host.deleteLater()


def test_flat_tier_paints_nothing_and_token_paints_the_wash():
    """The FLAT form is NOTHING (the plain canvas token shows); TOKEN and up
    paint the wash. Tier vocabulary is gui/glass_env.GlassTier — never a
    parallel ladder — and garbage coerces DOWN to the contract's safe floor."""
    host, ground = _host()
    try:
        p = style.palette("dark")
        canvas = p["canvas"].lower()

        img_token = host.grab().toImage()
        assert img_token.pixelColor(5, 5).name().lower() != canvas, (
            "TOKEN tier should show the wash over the canvas")

        ground.set_tier(GlassTier.FLAT)
        img_flat = host.grab().toImage()
        assert img_flat.pixelColor(5, 5).name().lower() == canvas, (
            "FLAT form must be the plain opaque canvas — nothing painted")

        ground.set_tier("garbage")                       # fail-safe: DOWN
        assert ground.tier() == GlassTier.TOKEN
        ground.set_tier(GlassTier.SCENE)                 # any tier >= TOKEN paints
        img_scene = host.grab().toImage()
        assert img_scene.pixelColor(5, 5).name().lower() != canvas
    finally:
        host.deleteLater()


def test_ground_refresh_theme_switches_the_wash():
    host, ground = _host("dark")
    try:
        img_dark = host.grab().toImage().pixelColor(5, 5).name()
        ground.refresh_theme("light")
        # (host canvas stylesheet still dark — only the wash changes here;
        # the composition root restyles the canvas in the same pass.)
        img_light = host.grab().toImage().pixelColor(5, 5).name()
        assert img_dark != img_light
        assert ground._theme_mode == "light"
    finally:
        host.deleteLater()
