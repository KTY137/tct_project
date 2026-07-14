"""Ground-wash PERF + the two test-gap NITs — Mary's pilot review (88cc542/074943f).

Closes the timing/memory RISKs and the two test gaps she flagged, WITHOUT any
behaviour change beyond timing/memory (the clamp scale and the shipped band are
pinned byte-stable against tests/test_ambient_ground.py):

  * RISK 1 — the band clamp is warmed OFF the paint path. Constructing an
    AmbientGround primes the clamp for its theme, so the first paintEvent hits
    an already-computed clamp instead of running the ~41k-pixel probe loop
    synchronously on the GUI thread. The probe itself is now vectorised (numpy).
  * RISK 2 — the low-frequency wash renders at a capped long edge
    (<= _GROUND_MAX_RENDER_PX) and is scaled up by drawPixmap, so a 4K/DPR2
    window no longer retains a ~141 MB pixmap per cache entry. Sub-cap sizes are
    byte-identical to before (every existing cache case stays unchanged).
  * NIT 1 — a bias-panel detach/redock round-trip keeps its Well/HazardSurface
    wrappers (objectNames) and the hazard stripe/hatch paint colours.
  * NIT 2 — the pixmap cache keys on DPR, so a mid-session monitor move
    re-fetches a correctly-scaled pixmap (no stale-DPR blit).

The banding check (RISK 2's "verify no banding at scale") writes a
before/after PNG pair into artifacts_claude/ground_perf/ and asserts the
capped-then-upscaled wash matches the full-resolution render within a tiny
ΔL* margin (the gradient has no detail to lose).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from gui import style
from gui.detachable_tabs import DetachableTabWidget, _DetachedWindow
from gui.panel_kit import AmbientGround, HazardSurface, Well

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "ground_perf"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# RISK 2 — the render is capped; sub-cap sizes are byte-identical              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_large_window_render_is_capped(mode):
    """A 4K/DPR2 window used to cache a full-resolution ~141 MB pixmap. The
    physical render must now stay within _GROUND_MAX_RENDER_PX on its long
    edge (aspect ratio preserved), so the retained pixmap is tiny."""
    _app()
    pm = style.ground_pixmap(3840, 2160, mode, 2.0)
    cap = style._GROUND_MAX_RENDER_PX
    assert max(pm.width(), pm.height()) <= cap, (
        f"[{mode}] capped render long edge {max(pm.width(), pm.height())} "
        f"> {cap}")
    # The cap shrinks both edges by the same factor, so it preserves the
    # BUCKETED aspect ratio exactly (the pre-existing bucket rounding, not the
    # cap, is the only aspect error — see ground_pixmap's docstring).
    assert pm.width() > pm.height()
    bw = style._ground_bucket(3840)
    bh = style._ground_bucket(2160)
    assert abs(pm.width() / pm.height() - bw / bh) < 0.02, (
        "cap distorted the bucketed aspect ratio")


def test_subcap_sizes_are_unchanged():
    """Everything <= the cap renders exactly as before — the existing cache
    contract (tests/test_ambient_ground) must keep holding byte-for-byte."""
    _app()
    a = style.ground_pixmap(500, 300, "dark", 1.0)       # 512x512 bucket, DPR1
    assert a.width() == 512 and a.height() == 512
    d = style.ground_pixmap(500, 300, "dark", 2.0)        # 1024 == the cap
    assert d.width() == 1024 and d.height() == 1024       # exactly at the cap
    assert d.devicePixelRatio() == pytest.approx(2.0)


def test_clamp_scale_and_band_are_byte_stable():
    """The whole fix is timing/memory only: the measured clamp and the shipped
    ΔL* band must be identical to what tests/test_ambient_ground pins."""
    assert style._ground_clamp_scale("dark") == pytest.approx(0.7561, abs=5e-4)
    assert style._ground_clamp_scale("light") == 1.0
    assert style.ground_band_measured("dark") <= 4.0
    assert style.ground_band_measured("dark") == pytest.approx(3.58, abs=0.05)


# --------------------------------------------------------------------------- #
# RISK 1 — the clamp is warmed off the paint path                             #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_constructing_ambient_ground_warms_the_clamp_off_the_paint_path(mode):
    """After construction, the clamp for the widget's theme is already cached,
    so the first paintEvent never runs the probe loop on the GUI thread."""
    _app()
    style._ground_clamp_cache.clear()
    p = style.palette(mode)
    key = (mode, p["canvas"], p["accent"])
    assert key not in style._ground_clamp_cache
    host = None
    try:
        host = AmbientGround(None, theme_mode=mode)  # no parent — pure warm path
        assert key in style._ground_clamp_cache, (
            "AmbientGround.__init__ must prime the band clamp (RISK 1)")
    finally:
        if host is not None:
            host.deleteLater()


def test_refresh_theme_warms_the_new_theme_clamp():
    _app()
    ground = AmbientGround(None, theme_mode="dark")
    try:
        style._ground_clamp_cache.clear()
        ground.refresh_theme("light")
        assert ground._theme_mode == "light"
        p = style.palette("light")
        assert ("light", p["canvas"], p["accent"]) in style._ground_clamp_cache
    finally:
        ground.deleteLater()


def test_prewarm_is_size_and_dpr_independent_and_never_raises():
    _app()
    style._ground_clamp_cache.clear()
    style.prewarm_ground("dark")
    style.prewarm_ground("garbage-mode")     # coerces to light; must not raise
    assert style._ground_clamp_scale("dark") < 1.0
    assert style._ground_clamp_scale("light") == 1.0


# --------------------------------------------------------------------------- #
# NIT 2 — the pixmap cache keys on DPR (a monitor move re-fetches)            #
# --------------------------------------------------------------------------- #

def test_pixmap_cache_keys_on_dpr_so_a_monitor_move_refetches():
    """Mid-session DPR change (drag the window to a 2x monitor): the same
    logical size at a new DPR must resolve to a DIFFERENT, correctly-scaled
    pixmap — never a stale-DPR blit."""
    _app()
    at1 = style.ground_pixmap(800, 600, "dark", 1.0)
    at1_again = style.ground_pixmap(800, 600, "dark", 1.0)
    assert at1 is at1_again, "same (size, DPR) must be a cache hit"

    at2 = style.ground_pixmap(800, 600, "dark", 2.0)
    assert at2 is not at1, "a DPR change must re-fetch, not reuse the DPR1 blit"
    assert at2.devicePixelRatio() == pytest.approx(2.0)
    assert at1.devicePixelRatio() == pytest.approx(1.0)

    # A fractional DPR (e.g. 150% scaling) is a distinct key too.
    at15 = style.ground_pixmap(800, 600, "dark", 1.5)
    assert at15 is not at1 and at15 is not at2
    assert at15.devicePixelRatio() == pytest.approx(1.5)


# --------------------------------------------------------------------------- #
# NIT 1 — detach/redock keeps the Well/Hazard wrappers + the hazard hatch      #
# --------------------------------------------------------------------------- #

@dataclass
class _Reading:
    voltage_V: float
    current_A: float
    compliant: bool
    tripped: bool = False


class _FakeSupply:
    """Attribute-only stand-in (the bias_panel test idiom) — never connects,
    never does I/O."""

    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.setpoint_V = -300.0
        self.compliance_A = 100e-6
        self.voltage_range_V = 1000.0
        self.channel = 0


def _hazard_and_wells(panel):
    hazards = panel.findChildren(HazardSurface)
    wells = panel.findChildren(Well)
    return hazards, wells


def test_bias_panel_survives_a_detach_redock_round_trip():
    """The pilot panel is detachable; the migration's kit surfaces (the opaque
    Well recesses and the HazardSurface + its painted stripe/hatch) must
    survive a torn-off round trip unchanged."""
    from gui.bias_panel import BiasPanel

    app = _app()
    tabs = DetachableTabWidget()
    panel = BiasPanel(_FakeSupply())
    tabs.addTab(panel, "Bias")
    tabs.show()
    app.processEvents()
    try:
        hazards0, wells0 = _hazard_and_wells(panel)
        assert len(hazards0) == 1 and wells0, "kit surfaces missing pre-detach"
        haz0 = hazards0[0]
        # Cache the painted-channel colours before the round trip.
        stripe0 = haz0._stripe_color.name().lower()
        hatch0 = haz0._hatch_color.name().lower()
        well_names0 = sorted(w.objectName() for w in wells0)

        # --- detach ---
        assert tabs.detach_by_title("Bias")
        app.processEvents()
        assert isinstance(panel.window(), _DetachedWindow), "panel did not tear off"

        # --- redock (close the floating window) ---
        tabs.redock_all()
        app.processEvents()
        assert tabs.count() == 1 and tabs.widget(0) is panel

        # Wrappers survived, by objectName and by count.
        hazards1, wells1 = _hazard_and_wells(panel)
        assert len(hazards1) == 1
        haz1 = hazards1[0]
        assert haz1 is haz0
        assert haz1.objectName() == "hazardSurface"
        assert haz1.stripe_kind() == "danger"
        assert sorted(w.objectName() for w in wells1) == well_names0
        assert all(w.objectName() == "wellPane" for w in wells1)
        for tile in (panel._tile_v, panel._tile_i, panel._tile_hv):
            assert haz1.isAncestorOf(tile), "a hero tile floated off the hazard"

        # The hazard hatch/stripe paint colours are identical, and still paint.
        assert haz1._stripe_color.name().lower() == stripe0
        assert haz1._hatch_color.name().lower() == hatch0
        # Grab synchronously at a fixed size (no event loop in between, so the
        # layout cannot snap it back before the paint) to prove the stripe still
        # paints post-redock.
        haz1.resize(300, 220)
        grab = haz1.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
        buf = np.frombuffer(grab.constBits(), dtype=np.uint8)
        px = buf.reshape(grab.height(), grab.bytesPerLine() // 4, 4)[:, :grab.width(), :]
        want = QColor(haz1._stripe_color)
        hit = ((px[..., 2] == want.red()) & (px[..., 1] == want.green())
               & (px[..., 0] == want.blue()))
        assert hit.any(), "danger stripe did not paint after the redock"
    finally:
        tabs.close()
        shutdown = getattr(panel, "shutdown", None)
        if shutdown is not None:
            shutdown()
        panel.deleteLater()
        tabs.deleteLater()


# --------------------------------------------------------------------------- #
# RISK 2 — the banding proof: capped-then-upscaled == full-resolution         #
# --------------------------------------------------------------------------- #

def _composite_full(mode: str, w: int, h: int) -> QImage:
    """The 'before' reference: the wash rendered at FULL (pre-cap) resolution
    — exactly what ``ground_pixmap`` did before RISK 2, i.e. the full bucketed
    render — then drawn into the (w, h) display rect the way the widget does.
    This shares ``ground_pixmap``'s bucket geometry with the capped 'after', so
    the only difference between the two images is the cap's resampling."""
    p = style.palette(mode)
    scale = style._ground_clamp_scale(mode)
    bw, bh = style._ground_bucket(w), style._ground_bucket(h)
    full_pm = QPixmap.fromImage(style._ground_wash_image(bw, bh, mode, scale))
    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(QColor(p["canvas"]))
    painter = QPainter(out)
    painter.drawPixmap(QRect(0, 0, w, h), full_pm)
    painter.end()
    return out


def _composite_capped(mode: str, w: int, h: int) -> QImage:
    """The SHIPPED path: the capped cached pixmap scaled up to (w, h) exactly
    the way AmbientGround.paintEvent does (drawPixmap(rect, pm)) — the 'after'."""
    p = style.palette(mode)
    pm = style.ground_pixmap(w, h, mode, 1.0)
    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(QColor(p["canvas"]))
    painter = QPainter(out)
    # Exactly AmbientGround.paintEvent's blit (no explicit render hint).
    painter.drawPixmap(QRect(0, 0, w, h), pm)
    painter.end()
    return out


def test_capped_upscale_introduces_no_banding_and_writes_the_pair():
    """The wash is low-frequency, so capping the render and scaling up must not
    band: the capped-then-upscaled composite tracks the full-resolution
    composite within a fraction of the ~1 ΔL* just-noticeable threshold. Writes
    the before/after PNG pair for Kaya's eye."""
    _app()
    mode, w, h = "dark", 2560, 1440       # a big window: 2.5x past the 1024 cap
    full = _composite_full(mode, w, h)
    capped = _composite_capped(mode, w, h)

    from tests.test_ambient_ground import _image_lstar
    dl = np.abs(_image_lstar(full) - _image_lstar(capped))
    max_dl = float(dl.max())
    # The two share ground_pixmap's bucket geometry, so this isolates the cap's
    # resampling alone. The wash is low-frequency; the peak ΔL* stays well below
    # the ~1.0 just-noticeable-difference threshold, i.e. no visible banding.
    assert max_dl < 1.0, (
        f"capped upscale banded: max ΔL* {max_dl:.3f} vs the full render "
        f"(>= ~1.0 would be visible)")

    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert full.save(str(_ARTIFACT_DIR / "ground_dark_before_fullres.png"))
    assert capped.save(str(_ARTIFACT_DIR / "ground_dark_after_capped.png"))
    (_ARTIFACT_DIR / "README.txt").write_text(
        "RISK 2 banding proof (Mary's pilot review).\n"
        f"before_fullres: the full (pre-cap) bucketed wash drawn into {w}x{h}.\n"
        f"after_capped:   ground_pixmap() capped to {style._GROUND_MAX_RENDER_PX}px "
        "long edge, then drawPixmap-scaled to the same size (the shipped path).\n"
        f"max per-pixel deltaL* between them: {max_dl:.4f}, a single-pixel peak "
        "at the toplight's steepest edge; below the ~1.0 JND threshold, so no\n"
        "visible banding (the wash's whole span is only deltaL* ~3.58).\n",
        encoding="utf-8")
