"""Render proof for the glass-ink-law extension (Kaya, 2026-07-14):
semantic STATE words on a REGISTERED glass card, over the WORST legal
owned-glass ground, in both themes — with the measured WCAG ratios printed.

This is a throwaway artifact generator (never imported by the app). It builds a
real ``gui.panel_kit.Card``, registers it as glass (``role="card"``), turns the
panel-glass switch ON, and paints it over a background filled with the worst
legal ground (the ΔL* 4.0 band edge, kit §1.1) — i.e. the exact
``QFrame#cardPane[glassCard="true"]`` composite the app ships. Semantic state
words are drawn in their semantic ink on that surface.

The printed contrast is analytic (``_blend(fill, ground, alpha)`` — byte-for-
byte what Qt alpha-composites, and what tests/test_material_contract.py pins),
cross-checked against a sampled pixel from the actual offscreen render.

Run (from anywhere):
    QT_QPA_PLATFORM=offscreen python artifacts_claude/semantic_ink_on_glass/\
        render_semantic_ink_on_glass.py
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_TCT_APP = _HERE.parents[2] / "TCT_app"   # repo/artifacts_claude/<dir>/ -> repo/TCT_app
if str(_TCT_APP) not in sys.path:
    sys.path.insert(0, str(_TCT_APP))

from PySide6.QtCore import Qt                                       # noqa: E402
from PySide6.QtWidgets import (                                     # noqa: E402
    QApplication, QHBoxLayout, QLabel, QWidget,
)

from gui import panel_kit, style                                   # noqa: E402
from gui.style import _blend, palette                              # noqa: E402

# --- WCAG + CIE L* (local, independent — mirrors the test model) ----------- #


def _lin(c8: int) -> float:
    c = c8 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


_KNEE = (6 / 29) ** 3


def _lstar(h: str) -> float:
    y = _lum(h)
    return 116 * y ** (1 / 3) - 16 if y > _KNEE else y * (29 / 3) ** 3


def _lstar_to_y(l: float) -> float:
    return ((l + 16) / 116) ** 3 if l > 8.0 else l / 903.3


def _y_to_srgb8(y: float) -> int:
    y = min(max(y, 0.0), 1.0)
    c = y * 12.92 if y <= 0.0031308 else 1.055 * y ** (1 / 2.4) - 0.055
    return round(min(max(c, 0.0), 1.0) * 255)


def worst_legal_ground(mode: str) -> str:
    """kit §1.1: canvas L* shifted by the full ΔL* 4.0 band edge in the hurting
    direction (dark: lighter; light: darker), as a neutral gray — identical to
    tests/test_material_contract.worst_legal_ground / kit_contrast_check."""
    cl = _lstar(palette(mode)["canvas"])
    wl = min(100.0, max(0.0, cl + (4.0 if mode == "dark" else -4.0)))
    g = _y_to_srgb8(_lstar_to_y(wl))
    return f"#{g:02x}{g:02x}{g:02x}"


# --- The demo state words, each in its semantic ink -------------------------- #
STATE_WORDS = [
    ("good", "LOCKED"),
    ("warn", "ARMED"),
    ("crit", "FAULT"),
    ("accent", "LIVE"),
    ("sim", "SIMULATED"),
]


def _card_fill(mode: str) -> tuple[str, float, str]:
    """(fill token hex, alpha, human label) for the SCENE glass card."""
    p = palette(mode)
    if mode == "dark":
        return p["raised"], style.GLASS_CARD_ALPHA_DARK, "raised @ 0.62"
    return p["panel"], style.GLASS_CARD_ALPHA_LIGHT, "panel @ 0.86"


def render(mode: str) -> Path:
    app = QApplication.instance() or QApplication([])
    style.apply_theme(app, mode)
    p = palette(mode)
    ground = worst_legal_ground(mode)
    fill_hex, alpha, fill_label = _card_fill(mode)
    composite = _blend(fill_hex, ground, alpha)   # what the QSS actually paints

    host = QWidget()
    host.setObjectName("groundHost")
    host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    # The host IS the worst legal ground the card composites over.
    host.setStyleSheet(f"QWidget#groundHost {{ background: {ground}; }}")
    host.resize(760, 260)

    card = panel_kit.Card("SYSTEM  ·  OWN-GROUND GLASS",
                          "semantic state words on a registered glass card",
                          parent=host)
    card.setGeometry(40, 40, 680, 180)

    row = QHBoxLayout()
    row.setSpacing(18)
    for token, word in STATE_WORDS:
        lbl = QLabel(word)
        lbl.setStyleSheet(
            f"color: {p[token]}; font-weight: 700; font-size: 20px; "
            f"background: transparent;")
        row.addWidget(lbl)
    row.addStretch(1)
    card.add_layout(row)

    panel_kit.register_glass_pane(card, role="card")
    panel_kit.set_panel_glass(True)
    style.repolish(card)

    host.show()
    app.processEvents()

    img = host.grab().toImage()
    # Sample a bare card-fill pixel (bottom padding, below the label row).
    sx = card.x() + card.width() // 2
    sy = card.y() + card.height() - 6
    sc = img.pixelColor(sx, sy)
    sampled = sc.name().lower()
    cc = sc.getRgb()[:3]
    ec = tuple(int(composite.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    # Analytic composite is authoritative (it is byte-for-byte what the QSS
    # paints); the render sample only sanity-checks it, so tolerate 8-bit
    # rounding at the sampled coordinate.
    matches = all(abs(a - b) <= 1 for a, b in zip(cc, ec))

    out = _HERE.parent / f"semantic_ink_on_glass_{mode}.png"
    img.save(str(out))

    lines = [
        f"=== {mode.upper()} theme ===",
        f"  canvas                 = {p['canvas']}  (L* {_lstar(p['canvas']):.2f})",
        f"  worst legal ground     = {ground}  (canvas L* {'+' if mode=='dark' else '-'}4.0 dL band edge)",
        f"  glass card fill        = {fill_label}  -> token {fill_hex}",
        f"  composite (rgba/ground)= {composite}   sampled render px = {sampled}  "
        f"({'OK match (<=1 LSB)' if matches else 'MISMATCH'})",
        "  semantic ink on the glass card:",
    ]
    for token, word in STATE_WORDS:
        r = contrast(p[token], composite)
        lines.append(
            f"    {token:<7} {p[token]}  '{word:<9}'  {r:5.2f}:1  "
            f"{'PASS' if r >= 4.5 else 'FAIL'}")
    lines.append(f"  saved: {out.name}")
    print("\n".join(lines))
    print()
    return out


def main() -> None:
    print("=" * 72)
    print("Semantic ink on OWNED-GLASS card — render proof (Kaya 2026-07-14)")
    print("model: glass card fill (one rung up @ card alpha) over the worst")
    print("legal ambient ground (kit 1.1 dL* 4.0 band edge). AA floor = 4.5:1")
    print("NOTE: under offscreen QPA the system font DB is empty, so the PNG")
    print("glyphs render as .notdef boxes — the INK COLOUR of each box is exact")
    print("(it is the semantic token on the real glass composite), and the")
    print("printed ratios are the authoritative certification.")
    print("=" * 72)
    for mode in ("dark", "light"):
        render(mode)


if __name__ == "__main__":
    main()
