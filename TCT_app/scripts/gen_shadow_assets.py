"""gen_shadow_assets.py — bake the LANTERN kit's pre-rendered assets.

DEV TOOL (same class as scripts/kit_contrast_check.py — never imported by the
app). Bakes, from ``gui/style.py`` tokens ONLY (never hand-picked hex):

* the 9-patch **shadow ladder** (kit_spec_v1.md §2.5 / round-03 kit.md §3.1):
  ``shadow_{contact,card,pane,float}_{dark,light}.png`` — pre-rendered
  ``BorderImage`` sources; **no live drop-shadow effect anywhere**. Layer
  recipe is the ratified ladder:

      contact : 0 1px 2px  A
      card    : 0 1px 2px  A,  0 8px 24px B
      pane    : 0 12px 40px C
      float   : 0 32px 80px D

  ink = ``palette(mode)["shadow_ink"]`` (dark #000 / light = text hue),
  alphas = ``SHADOW_{A..D}_{DARK,LIGHT}``. The interior of the casting rect
  is punched out so a translucent (glass) fill never double-darkens over its
  own shadow.

* the **focus halo** (kit_spec_v1.md §4.1): an 8 px outer glow in the theme's
  ``accent`` hue, alpha-NORMALISED to peak 1.0 at bake time — QML drives the
  live ``Theme.focusHaloAlpha`` (0.35 dark / 0.25 light) as Item opacity, so
  a theme flip needs no rebake. Interior punched (the halo may never fall on
  the target's own fill — and never on an island: dead-zone law §4.4).

* the **ground wash sprites** (kit_spec_v1.md §5.3): radial accent blobs with
  the peak tint BAKED IN so ``LivingGround``'s washes run at constant
  opacity 1.0 (band law: washes move position, never alpha). The budget
  split is asserted here at bake time:

      2 * WASH_PEAK_ALPHA + SWEEP_PEAK_ALPHA <= GROUND_TINT_ALPHA_MAX

Outputs (all under ``gui/qml/kit/``):
  ``assets/*.png``            — the baked images
  ``assets/manifest.json``    — every token value + geometry used, for the
                                drift-guard test (tests/test_qml_kit_surface.py
                                fails if style.py moved under the bake)
  ``KitAssets.qml``           — GENERATED singleton with the 9-patch pads/
                                borders + the tint-budget split the QML reads

Run:  python TCT_app/scripts/gen_shadow_assets.py   (offscreen-safe, no Qt
display, no hardware; deterministic for fixed style tokens).
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

# --------------------------------------------------------------------------- #
# TCT_app/ on sys.path so `from gui import style` resolves regardless of cwd   #
# (same bootstrap idiom as scripts/kit_contrast_check.py).                     #
# --------------------------------------------------------------------------- #
_SCRIPTS = Path(__file__).resolve().parent
_TCT_APP = _SCRIPTS.parent
if str(_TCT_APP) not in sys.path:
    sys.path.insert(0, str(_TCT_APP))

from gui.style import (  # noqa: E402
    FOCUS_HALO_ALPHA_DARK, FOCUS_HALO_ALPHA_LIGHT, FOCUS_RING_OFFSET_PX,
    GROUND_TINT_ALPHA_MAX, RADIUS, SHADOW_A_DARK, SHADOW_A_LIGHT,
    SHADOW_B_DARK, SHADOW_B_LIGHT, SHADOW_C_DARK, SHADOW_C_LIGHT,
    SHADOW_D_DARK, SHADOW_D_LIGHT, palette,
)

KIT_DIR = _TCT_APP / "gui" / "qml" / "kit"
ASSETS_DIR = KIT_DIR / "assets"

# --------------------------------------------------------------------------- #
# The ratified numbers (each cited; none invented here)                        #
# --------------------------------------------------------------------------- #

# round-03 kit.md §3.1 / kit_spec_v1.md §2.5 — (dy, blur, alpha-key) layers.
SHADOW_LEVELS: dict[str, dict] = {
    "contact": {"radius": RADIUS["md"],    "layers": [(1, 2, "a")]},
    "card":    {"radius": RADIUS["xl"],    "layers": [(1, 2, "a"), (8, 24, "b")]},
    "pane":    {"radius": RADIUS["shelf"], "layers": [(12, 40, "c")]},
    "float":   {"radius": RADIUS["xl"],    "layers": [(32, 80, "d")]},
}

SHADOW_ALPHAS = {
    "dark":  {"a": SHADOW_A_DARK, "b": SHADOW_B_DARK,
              "c": SHADOW_C_DARK, "d": SHADOW_D_DARK},
    "light": {"a": SHADOW_A_LIGHT, "b": SHADOW_B_LIGHT,
              "c": SHADOW_C_LIGHT, "d": SHADOW_D_LIGHT},
}

# kit_spec_v1.md §4.1 — spec-fixed focus geometry (2 px ring, 8 px halo).
FOCUS_RING_WIDTH_PX = 2
FOCUS_HALO_PX = 8

# Living-ground tint-budget split (kit_spec_v1.md §5.3). The generator OWNS
# this split; the law it must satisfy comes from gui/style.py.
WASH_PEAK_ALPHA = 0.03
SWEEP_PEAK_ALPHA = 0.01

STRETCH_STRIP_PX = 8       # 9-patch centre strip (stretchable region)


# --------------------------------------------------------------------------- #
# Raster primitives (numpy only — no PIL, no scipy)                            #
# --------------------------------------------------------------------------- #

def _rounded_rect_mask(size_w: int, size_h: int, x0: float, y0: float,
                       w: float, h: float, r: float) -> np.ndarray:
    """Antialiased coverage mask (float 0..1) of a rounded rect via its SDF."""
    yy, xx = np.mgrid[0:size_h, 0:size_w].astype(float)
    xx += 0.5
    yy += 0.5
    cx0, cy0 = x0 + r, y0 + r
    cx1, cy1 = x0 + w - r, y0 + h - r
    qx = np.maximum(np.maximum(cx0 - xx, xx - cx1), 0.0)
    qy = np.maximum(np.maximum(cy0 - yy, yy - cy1), 0.0)
    dist = np.hypot(qx, qy) - r
    return np.clip(0.5 - dist, 0.0, 1.0)


def _gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur (CSS box-shadow convention: blur radius = 2σ)."""
    if sigma <= 0:
        return a
    radius = max(1, int(math.ceil(3.0 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=float)
    k = np.exp(-(x * x) / (2.0 * sigma * sigma))
    k /= k.sum()
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        ap = np.pad(a, pad, mode="constant")
        out = np.zeros_like(a)
        for i, kv in enumerate(k):
            sl: list = [slice(None), slice(None)]
            sl[axis] = slice(i, i + a.shape[axis])
            out += kv * ap[tuple(sl)]
        a = out
    return a


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _save_png(path: Path, rgb: tuple[int, int, int], alpha: np.ndarray) -> None:
    from PySide6.QtGui import QImage

    h, w = alpha.shape
    buf = np.zeros((h, w, 4), np.uint8)
    buf[..., 0] = rgb[0]
    buf[..., 1] = rgb[1]
    buf[..., 2] = rgb[2]
    buf[..., 3] = np.clip(np.round(alpha * 255.0), 0, 255).astype(np.uint8)
    data = buf.tobytes()
    img = QImage(data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
    if not img.save(str(path)):
        raise RuntimeError(f"could not write {path}")


# --------------------------------------------------------------------------- #
# Bakes                                                                        #
# --------------------------------------------------------------------------- #

def shadow_pad(level: str) -> int:
    return max(dy + blur for (dy, blur, _k) in SHADOW_LEVELS[level]["layers"]) + 2


def shadow_border(level: str) -> int:
    return shadow_pad(level) + SHADOW_LEVELS[level]["radius"] + 2


def bake_shadow(mode: str, level: str) -> Path:
    spec = SHADOW_LEVELS[level]
    r = spec["radius"]
    pad = shadow_pad(level)
    core = 2 * r + STRETCH_STRIP_PX
    size = core + 2 * pad
    mask0 = _rounded_rect_mask(size, size, pad, pad, core, core, r)
    total = np.zeros((size, size), float)
    for (dy, blur, key) in spec["layers"]:
        layer = _rounded_rect_mask(size, size, pad, pad + dy, core, core, r)
        layer = _gaussian_blur(layer, blur / 2.0)
        layer *= SHADOW_ALPHAS[mode][key]
        total = total + layer * (1.0 - total)     # same-ink alpha compositing
    total *= (1.0 - mask0)                        # punch out the casting rect
    ink = _hex_to_rgb(palette(mode)["shadow_ink"])
    out = ASSETS_DIR / f"shadow_{level}_{mode}.png"
    _save_png(out, ink, total)
    return out


def halo_pad() -> int:
    return FOCUS_RING_OFFSET_PX + FOCUS_RING_WIDTH_PX + FOCUS_HALO_PX + 2


def halo_border() -> int:
    return halo_pad() + RADIUS["md"] + 2


def bake_halo(mode: str) -> Path:
    r_base = RADIUS["md"]                      # nominal corner (BorderImage
    ring_out = FOCUS_RING_OFFSET_PX + FOCUS_RING_WIDTH_PX  # 9-patch stretches
    pad = halo_pad()
    core = 2 * r_base + STRETCH_STRIP_PX
    size = core + 2 * pad
    # The glow starts at the ring's OUTER boundary (fill + offset + ring).
    inner = _rounded_rect_mask(size, size, pad - ring_out, pad - ring_out,
                               core + 2 * ring_out, core + 2 * ring_out,
                               r_base + ring_out)
    glow = _gaussian_blur(inner, FOCUS_HALO_PX / 2.0)
    glow *= (1.0 - inner)                      # outer glow only
    peak = float(glow.max())
    if peak > 0:
        glow /= peak                           # normalised: QML applies
    accent = _hex_to_rgb(palette(mode)["accent"])   # Theme.focusHaloAlpha live
    out = ASSETS_DIR / f"focus_halo_{mode}.png"
    _save_png(out, accent, glow)
    return out


def bake_wash(mode: str) -> Path:
    size = 256
    margin = 8.0
    yy, xx = np.mgrid[0:size, 0:size].astype(float)
    cx = cy = size / 2.0 - 0.5
    d = np.hypot(xx - cx, yy - cy)
    R = size / 2.0 - margin
    t = np.clip(1.0 - (d / R) ** 2, 0.0, 1.0) ** 2      # smooth radial falloff
    alpha = WASH_PEAK_ALPHA * t
    accent = _hex_to_rgb(palette(mode)["accent"])       # NO semantic tint, ever
    out = ASSETS_DIR / f"ground_wash_{mode}.png"
    _save_png(out, accent, alpha)
    return out


# --------------------------------------------------------------------------- #
# Generated outputs                                                            #
# --------------------------------------------------------------------------- #

def write_kit_assets_qml() -> Path:
    pads = {lvl: shadow_pad(lvl) for lvl in SHADOW_LEVELS}
    borders = {lvl: shadow_border(lvl) for lvl in SHADOW_LEVELS}
    body = f"""// GENERATED by scripts/gen_shadow_assets.py — DO NOT EDIT.
// Regenerate after any gui/style.py shadow/accent/budget token change:
//   python scripts/gen_shadow_assets.py
// (tests/test_qml_kit_surface.py's manifest drift-guard fails loudly if the
// baked assets no longer match the live tokens.)
//
// 9-patch geometry contract: every shadow asset represents [fill rect
// expanded by shadowPad] — a BorderImage anchors.fill's the fill item with
// anchors.margins: -shadowPad[level] and border: shadowBorder[level]. The
// halo asset uses haloPad/haloBorder the same way. washPeakAlpha /
// sweepPeakAlpha are the living-ground tint-budget split baked into the
// wash sprites (band law, kit_spec_v1.md §5.3).
pragma Singleton
import QtQuick

QtObject {{
    readonly property real washPeakAlpha: {WASH_PEAK_ALPHA}
    readonly property real sweepPeakAlpha: {SWEEP_PEAK_ALPHA}
    readonly property var shadowPad: ({{
        "contact": {pads['contact']}, "card": {pads['card']},
        "pane": {pads['pane']}, "float": {pads['float']}
    }})
    readonly property var shadowBorder: ({{
        "contact": {borders['contact']}, "card": {borders['card']},
        "pane": {borders['pane']}, "float": {borders['float']}
    }})
    readonly property int haloPad: {halo_pad()}
    readonly property int haloBorder: {halo_border()}
}}
"""
    out = KIT_DIR / "KitAssets.qml"
    out.write_text(body, encoding="utf-8")
    return out


def write_manifest() -> Path:
    manifest = {
        "generator": "scripts/gen_shadow_assets.py",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "budget": {
            "wash_peak_alpha": WASH_PEAK_ALPHA,
            "sweep_peak_alpha": SWEEP_PEAK_ALPHA,
            "ground_tint_alpha_max": GROUND_TINT_ALPHA_MAX,
        },
        "geometry": {
            "shadow_pad": {lvl: shadow_pad(lvl) for lvl in SHADOW_LEVELS},
            "shadow_border": {lvl: shadow_border(lvl) for lvl in SHADOW_LEVELS},
            "shadow_radius": {lvl: SHADOW_LEVELS[lvl]["radius"]
                              for lvl in SHADOW_LEVELS},
            "halo_pad": halo_pad(),
            "halo_border": halo_border(),
            "focus_ring_offset_px": FOCUS_RING_OFFSET_PX,
            "focus_ring_width_px": FOCUS_RING_WIDTH_PX,
            "focus_halo_px": FOCUS_HALO_PX,
            "stretch_strip_px": STRETCH_STRIP_PX,
        },
        "shadow_layers": {lvl: [list(layer) for layer in
                                SHADOW_LEVELS[lvl]["layers"]]
                          for lvl in SHADOW_LEVELS},
        "tokens": {
            mode: {
                "shadow_ink": palette(mode)["shadow_ink"],
                "accent": palette(mode)["accent"],
                **{f"shadow_{k}": v for k, v in SHADOW_ALPHAS[mode].items()},
                "focus_halo_alpha": (FOCUS_HALO_ALPHA_DARK if mode == "dark"
                                     else FOCUS_HALO_ALPHA_LIGHT),
            }
            for mode in ("dark", "light")
        },
    }
    out = ASSETS_DIR / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    budget = 2 * WASH_PEAK_ALPHA + SWEEP_PEAK_ALPHA
    assert budget <= GROUND_TINT_ALPHA_MAX + 1e-9, (
        f"band law violated at bake time: 2*{WASH_PEAK_ALPHA} + "
        f"{SWEEP_PEAK_ALPHA} = {budget} > GROUND_TINT_ALPHA_MAX "
        f"{GROUND_TINT_ALPHA_MAX}")

    # QImage wants a QGuiApplication on some platforms; offscreen, no display.
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    assert app is not None

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for mode in ("dark", "light"):
        for level in SHADOW_LEVELS:
            written.append(bake_shadow(mode, level))
        written.append(bake_halo(mode))
        written.append(bake_wash(mode))
    written.append(write_kit_assets_qml())
    written.append(write_manifest())

    print(f"gen_shadow_assets: tint budget 2*{WASH_PEAK_ALPHA} + "
          f"{SWEEP_PEAK_ALPHA} = {budget:.3f} <= "
          f"GROUND_TINT_ALPHA_MAX {GROUND_TINT_ALPHA_MAX}  OK")
    for p in written:
        print(f"  wrote {p.relative_to(_TCT_APP)}")
    print(f"gen_shadow_assets: {len(written)} files OK")


if __name__ == "__main__":
    main()
