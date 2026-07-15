"""kit_contrast_check.py — machine re-derivation of every number
docs/design/iterations/glasshell-cockpit/round-03/kit.md publishes.

DEV TOOL. Never imported by the app (not referenced from ``gui/`` or
``controller/``; safe to delete without touching a single import).

WHY THIS EXISTS
----------------
Round-03's kit (``kit.md`` / ``kit.html``) was forged 2026-07-14 and bakes its
own numbers as literal hex constants in ``kit.html``'s CSS custom properties
and its JS ``TOKENS`` object — a *snapshot*, not a live read. This script is
the machine that snapshot should have been: it imports ``gui.style`` and
reads ``palette("dark")`` / ``palette("light")`` **at run time**, so its
numbers can never go stale the way a hand-copied hex can (see the ``good``/
``sim`` findings below — two hex constants baked into ``kit.html`` do not
match what ``gui.style`` actually computes for those same tokens today).

RULE: every colour used below is read from ``gui.style`` (``palette()``,
``style._blend``, ``style.PLOT_BG``, the ``MIN_*_ALPHA`` floors). The only
literals in this file are the kit's own PROPOSED-but-unshipped design
constants (the ``KIT_*`` block below) — each one is named, commented with
its exact kit.md citation, and is not a colour.

THE MODEL (mirrors kit.md's own prose, not a re-invention)
------------------------------------------------------------
1. WCAG 2.2 relative luminance / contrast ratio — the standard formula.
2. THE GROUND BAND LAW (kit.md §1.1): "no pixel of the ground may deviate
   from canvas by more than ΔL* 4.0". The worst legal ground is therefore
   the canvas's own L*, shifted by the full ΔL* 4.0 band in whichever
   direction hurts contrast most for that theme (dark: lighter is worse;
   light: darker is worse — kit.html's own JS comment, ``worstGround()``),
   converted back through L*→Y→sRGB to a neutral GRAY pixel (not a
   per-channel nudge — that shortcut is what ``kit.html``'s own
   ``worstGround()`` does, and it is a coarser approximation than the
   proper CIE L* round-trip this script performs).
3. Surface compositing (kit.md §2.1 "paint one rung up, at your rung's
   alpha") is plain sRGB alpha blending — literally ``gui.style._blend``,
   imported and called directly, never re-derived, so this script tracks
   the shipped rounding behaviour (``round()``) byte for byte.
4. FLAT/TOKEN tier = the opaque token itself. SCENE tier = the surface's
   glass fill blended over the worst legal ground at the surface's alpha.

Run: ``python TCT_app/scripts/kit_contrast_check.py`` (from anywhere —
sys.path is bootstrapped below). No Qt display required.

Also runs the ring-contrast standing check (Baldr BLOCKER-2 / docs/
DECISIONS.md 2026-07-15 "Post-attack-pass rulings" ruling 3):
``--ring-context {own-fill,surround,both}`` (default ``both``) — see that
check's own module comment below for what each mode measures.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# TCT_app/ on sys.path so `from gui import style` resolves regardless of cwd
# (same bootstrap idiom as scripts/glass_probe.py).
# ---------------------------------------------------------------------------
_SCRIPTS = Path(__file__).resolve().parent
_TCT_APP = _SCRIPTS.parent
for _p in (str(_TCT_APP),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gui import style  # noqa: E402
from gui.style import _blend as blend_hex  # noqa: E402  — the SHIPPED sRGB blend, not a copy
from gui.style import MIN_PANEL_GLASS_ALPHA  # noqa: E402  — the REAL, enforced clamp floor
from gui.style import PLOT_BG  # noqa: E402  — the island rung's opaque token

# ---------------------------------------------------------------------------
# WCAG 2.2 contrast primitives — no hardcoded colour anywhere in this block.
# ---------------------------------------------------------------------------


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def srgb_to_linear(c8: int) -> float:
    c = c8 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb_unit(lin: float) -> float:
    lin = min(max(lin, 0.0), 1.0)
    return lin * 12.92 if lin <= 0.0031308 else 1.055 * (lin ** (1 / 2.4)) - 0.055


def linear_to_srgb8(lin: float) -> int:
    return round(min(max(linear_to_srgb_unit(lin), 0.0), 1.0) * 255)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return (0.2126 * srgb_to_linear(r) + 0.7152 * srgb_to_linear(g)
            + 0.0722 * srgb_to_linear(b))


def contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    l1, l2 = relative_luminance(rgb1), relative_luminance(rgb2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def contrast_hex(hex1: str, hex2: str) -> float:
    return contrast_ratio(hex_to_rgb(hex1), hex_to_rgb(hex2))


# ---------------------------------------------------------------------------
# CIE L* <-> Y (relative luminance), D65, Yn = 1 — the same normalisation
# WCAG's own relative-luminance formula already uses (white = 1.0), so this
# round-trips through the SAME Y the contrast formula above computes; no
# separate "brightness" model is introduced.
# ---------------------------------------------------------------------------
_LSTAR_Y_KNEE = (6 / 29) ** 3          # ≈ 0.008856
_LSTAR_L_KNEE = 8.0                    # y_to_lstar(_LSTAR_Y_KNEE) == 8.0 exactly


def y_to_lstar(y: float) -> float:
    if y > _LSTAR_Y_KNEE:
        return 116 * (y ** (1 / 3)) - 16
    return y * (29 / 3) ** 3


def lstar_to_y(lstar: float) -> float:
    if lstar > _LSTAR_L_KNEE:
        return ((lstar + 16) / 116) ** 3
    return lstar / 903.3


def lstar_of_hex(h: str) -> float:
    return y_to_lstar(relative_luminance(hex_to_rgb(h)))


# ---------------------------------------------------------------------------
# THE KIT'S OWN PROPOSED CONSTANTS — not colours, not in style.py. Each is
# cited to its exact kit.md location so nobody mistakes these for shipped
# tokens. Everything colour-shaped below still comes from palette()/_blend.
# ---------------------------------------------------------------------------
KIT_GROUND_BAND_DELTA_L = 4.0        # kit.md §1.1 "GROUND BAND LAW"
KIT_GLASS_SHELF_ALPHA = 0.55         # kit.md §8 GLASS_SHELF_ALPHA
KIT_GLASS_CARD_ALPHA_DARK = 0.62     # kit.md §8 GLASS_CARD_ALPHA (dark)
KIT_GLASS_CARD_ALPHA_LIGHT = 0.86    # kit.md §8 GLASS_CARD_ALPHA (light)
KIT_CARD_BLEND_DARK = 0.60           # kit.md §2 "card = _blend(raised,panel,.60)"
KIT_SHELF_BLEND_DARK = 0.30          # kit.md §2 "shelf = _blend(card,panel,.30)" (dark)
KIT_SHELF_BLEND_LIGHT = 0.50         # kit.md §2 "_blend(panel,canvas,.50)" (light)

# Semantic inks the kit's §6 tables walk, in kit.md's own order. "faint" is
# included and always marked exempt (repo law: never text).
INK_ORDER = ["text", "muted", "good", "warn", "crit", "accent", "sim", "faint"]


# ---------------------------------------------------------------------------
# Worst legal ground (kit.md §1.1) — the ΔL*4.0 band edge, converted back to
# a neutral gray pixel through the full L*->Y->sRGB round trip (NOT
# kit.html's own coarser "+-9 sRGB units per channel" shortcut).
# ---------------------------------------------------------------------------
def worst_ground(mode: str, band: float = KIT_GROUND_BAND_DELTA_L):
    """Returns (hex, rgb, canvas_lstar, worst_lstar) for *mode*'s worst
    legal ground. Direction matches kit.html's own worstGround() comment:
    dark -> lighter ground is worse; light -> darker ground is worse."""
    p = style.palette(mode)
    canvas_rgb = hex_to_rgb(p["canvas"])
    canvas_l = y_to_lstar(relative_luminance(canvas_rgb))
    direction = 1.0 if mode == "dark" else -1.0
    worst_l = max(0.0, min(100.0, canvas_l + direction * band))
    g = linear_to_srgb8(lstar_to_y(worst_l))
    return rgb_to_hex((g, g, g)), (g, g, g), canvas_l, worst_l


# ---------------------------------------------------------------------------
# The proposed `card` / `shelf` tokens — and their LIVE fallbacks.
#
# Light's "card" is NOT actually a new token: kit.md §2 says card = panel in
# light, byte for byte. Only DARK's card (_blend(raised,panel,.60)) is a
# genuinely new, unratified value. Everywhere the kit's own formulas need
# "card" as an ingredient (the shelf's SCENE glass wash, the shelf's own
# FLAT/TOKEN derivation) this module computes BOTH the PROPOSED-card version
# and a LIVE-FALLBACK version substituting the nearest real rung — `raised`
# in dark (kit.md's own "one rung up" language), `panel` in light (which is
# what card already equals there, so light never actually needs a fallback).
# ---------------------------------------------------------------------------
def kit_card_token(mode: str) -> tuple[str, bool]:
    """(hex, is_proposed). is_proposed=True only for dark."""
    p = style.palette(mode)
    if mode == "dark":
        return blend_hex(p["raised"], p["panel"], KIT_CARD_BLEND_DARK), True
    return p["panel"], False


def kit_card_fallback(mode: str) -> str:
    """The live token substituted for `card` wherever the kit's own formula
    needs an ingredient that does not exist in the tree yet."""
    p = style.palette(mode)
    return p["raised"] if mode == "dark" else p["panel"]


def kit_shelf_token(mode: str, card_hex: str) -> str:
    p = style.palette(mode)
    if mode == "dark":
        return blend_hex(card_hex, p["panel"], KIT_SHELF_BLEND_DARK)
    return blend_hex(p["panel"], p["canvas"], KIT_SHELF_BLEND_LIGHT)


# ---------------------------------------------------------------------------
# SCENE-tier surface composites (kit.md §2.1's own resolution rules).
# Note: the CARD's own SCENE fill never uses "card" as an ingredient — it is
# raised(dark)/panel(light) blended directly onto the ground. Only the
# SHELF's SCENE fill washes with "card". This matches kit.html's `surface()`
# JS function exactly.
# ---------------------------------------------------------------------------
def scene_card_rgb(mode: str, ground_hex: str) -> tuple[int, int, int]:
    p = style.palette(mode)
    if mode == "light":
        return hex_to_rgb(blend_hex(p["panel"], ground_hex, KIT_GLASS_CARD_ALPHA_LIGHT))
    return hex_to_rgb(blend_hex(p["raised"], ground_hex, KIT_GLASS_CARD_ALPHA_DARK))


def scene_shelf_rgb(ground_hex: str, card_ingredient_hex: str) -> tuple[int, int, int]:
    return hex_to_rgb(blend_hex(card_ingredient_hex, ground_hex, KIT_GLASS_SHELF_ALPHA))


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------
def _fmt(ratio: float) -> str:
    return f"{ratio:5.2f}"


def _pass(ratio: float, threshold: float = 4.5) -> str:
    """4.5 (WCAG AA text) by default — every EXISTING call site below keeps
    passing zero args, so their pass/fail behaviour is untouched. The ring
    checks (Baldr BLOCKER-2 / docs/DECISIONS.md 2026-07-15 "Post-attack-pass
    rulings" ruling 3) pass NON_TEXT_PASS_THRESHOLD (3.0, the WCAG non-text
    UI-component floor) explicitly instead."""
    return "PASS" if ratio >= threshold else "FAIL"


# WCAG 2.2 non-text/UI-component contrast floor (SC 1.4.11) — the ring is
# not text, so 4.5 (the text floor `_pass()` defaults to) is the wrong bar.
NON_TEXT_PASS_THRESHOLD = 3.0


def print_ink_table(mode: str, surface_rgb: tuple[int, int, int], surface_name: str,
                     legal_inks: set[str] | None = None) -> None:
    p = style.palette(mode)
    for ink in INK_ORDER:
        rgb = hex_to_rgb(p[ink])
        ratio = contrast_ratio(rgb, surface_rgb)
        legal = legal_inks is None or ink in legal_inks
        tag = "exempt (never text)" if ink == "faint" else (_pass(ratio) if legal else "n/a (illegal pair)")
        print(f"    {ink:<7} on {surface_name:<10} {_fmt(ratio)} : 1   {tag}")


def alpha_floor_scan(mode: str, surface: str, ink_key: str, card_ingredient_hex: str,
                      ground_hex: str, floor_alpha: float, ceiling_alpha: float,
                      step: float = 0.01) -> tuple[float | None, float, float]:
    """Scans legal alpha in [floor_alpha, ceiling_alpha] for *surface*
    ("card" or "shelf") and returns (min_alpha_that_clears_4_5 or None,
    ratio_at_floor, ratio_at_ceiling). Contrast is monotonic in alpha for a
    fixed fill/ground pair, so the scan just needs to find the crossing --
    but it scans explicitly (not just the two endpoints) so a non-monotonic
    surprise would be visible, never assumed away."""
    p = style.palette(mode)
    ink_rgb = hex_to_rgb(p[ink_key])
    n_steps = max(1, round((ceiling_alpha - floor_alpha) / step))
    min_pass_alpha = None
    ratio_floor = ratio_ceiling = None
    for i in range(n_steps + 1):
        a = floor_alpha + (ceiling_alpha - floor_alpha) * i / n_steps
        if surface == "shelf":
            fill_hex = card_ingredient_hex
        else:
            fill_hex = p["panel"] if mode == "light" else p["raised"]
        composite = hex_to_rgb(blend_hex(fill_hex, ground_hex, a))
        ratio = contrast_ratio(ink_rgb, composite)
        if i == 0:
            ratio_floor = ratio
        if i == n_steps:
            ratio_ceiling = ratio
        if ratio >= 4.5 and min_pass_alpha is None:
            min_pass_alpha = a
    return min_pass_alpha, ratio_floor, ratio_ceiling


SEMANTIC_INKS = ["good", "warn", "crit", "accent", "sim"]


# ---------------------------------------------------------------------------
# Ring-contrast standing check (Baldr BLOCKER-2, attack_baldr.md finding #2 /
# docs/DECISIONS.md 2026-07-15 "Post-attack-pass rulings" ruling 3).
#
# candidate_lantern.md §5 claims the focus ring is "≥3:1 non-text contrast on
# every rung — audited". Nothing in this file, before this addition, ever
# produced that audit: the ink tables above only ever measured TEXT (4.5:1
# floor) on `card`/`shelf`. The ring is (a) not text — the non-text 3:1 floor
# applies, not 4.5 — and (b) needs checking against every rung's SURROUND
# (the containing pane it sits on), AND against a component's OWN FILL
# (accent-filled buttons, StatusPill variants) — a pairing the surround-only
# model structurally cannot see (an accent ring on an accent-toned fill is
# the failure Baldr's audit actually measured: ~1.0-1.4:1, functionally
# invisible).
#
# Ring colour is `accent` (candidate_lantern.md §5: "the 2 px ring itself"),
# read live from palette() — never hand-copied.
#
# The ring OFFSET convention (does the ring sit on the component's own fill,
# or is it drawn outward onto the surrounding pane per the existing QSS
# precedent, `outline-offset: 1px`?) is still being decided in Brokkr's
# parallel spec revision — so which pairing is the one that matters is
# itself an open question. --ring-context parameterizes it instead of
# hard-coding an answer: `own-fill`, `surround`, or `both` (default). The
# SURROUND checks reuse the existing PASS/FAIL convention (now at the 3.0
# non-text floor). The OWN-FILL checks are REPORT-ONLY regardless of the
# flag — do not hard-fail the run on them yet — until the offset convention
# lands; the numbers are printed either way so nobody has to re-derive them
# once it does.
# ---------------------------------------------------------------------------
RING_INK_KEY = "accent"

# Own-fill tokens to check the ring against — Baldr's own missing-check spec
# item 3: "every interactive component's own fill token (`accent`,
# `accent_strong`, `tint`, `pressed`) read from `style.palette()` by name,
# not hand-copied". `danger_fill`/hazard fills are deliberately excluded —
# ruling 4 keeps the ring on hazard rungs but hazard fills are never
# accent-toned, so they are not the same-hue-on-same-hue failure mode this
# check targets.
RING_OWN_FILL_TOKENS = ["accent", "accent_strong", "tint", "pressed"]


def ring_vs_surround(mode: str, gh: str, card_hex: str, card_scene_rgb: tuple[int, int, int],
                      shelf_hex: str, shelf_scene_rgb: tuple[int, int, int]) -> None:
    """Ring vs every rung's SCENE+TOKEN composite: card, shelf, tile
    (=`raised`), well, island (=PLOT_BG), hazard (=`panel`) — today only
    card/shelf were modelled at all (as TEXT, via the ink tables above);
    tile/well/island/hazard were never modelled by this script for any
    purpose. `card`/`shelf` are real glass surfaces so both their SCENE
    (composited over the worst legal ground) and TOKEN (opaque) tiers are
    checked, matching this file's own tier-invariance convention above;
    tile/well/island/hazard are already opaque tokens, so TOKEN only."""
    p = style.palette(mode)
    ring_rgb = hex_to_rgb(p[RING_INK_KEY])

    print(f"\n  Ring ({RING_INK_KEY}) vs SURROUND — every rung's SCENE+TOKEN "
          f"composite (floor {NON_TEXT_PASS_THRESHOLD}:1 non-text, SC 1.4.11):")
    rungs: list[tuple[str, tuple[int, int, int] | None, tuple[int, int, int]]] = [
        ("card", card_scene_rgb, hex_to_rgb(card_hex)),
        ("shelf", shelf_scene_rgb, hex_to_rgb(shelf_hex)),
        ("tile (raised)", None, hex_to_rgb(p["raised"])),
        ("well", None, hex_to_rgb(p["well"])),
        ("island (PLOT_BG)", None, hex_to_rgb(PLOT_BG)),
        ("hazard (panel, dead material)", None, hex_to_rgb(p["panel"])),
    ]
    for rung_name, scene_rgb, token_rgb in rungs:
        if scene_rgb is not None:
            ratio_scene = contrast_ratio(ring_rgb, scene_rgb)
            print(f"    {rung_name:<30} SCENE  {_fmt(ratio_scene)} : 1   "
                  f"{_pass(ratio_scene, NON_TEXT_PASS_THRESHOLD)}")
        ratio_token = contrast_ratio(ring_rgb, token_rgb)
        print(f"    {rung_name:<30} TOKEN  {_fmt(ratio_token)} : 1   "
              f"{_pass(ratio_token, NON_TEXT_PASS_THRESHOLD)}")


def ring_vs_own_fill(mode: str) -> None:
    """Ring vs an interactive component's OWN resting/hover/pressed fill —
    the pairing `ring_vs_surround` structurally cannot see, and the one
    Baldr's audit found actually fails (accent-on-accent ~1.0-1.4:1). Report
    numbers unconditionally; never gate ship on them here (see module note
    above) — the ring-offset convention decides whether this pairing is even
    reachable in the shipped `BorderImage`, and that convention has not
    landed yet."""
    p = style.palette(mode)
    ring_rgb = hex_to_rgb(p[RING_INK_KEY])

    print(f"\n  Ring ({RING_INK_KEY}) vs OWN FILL — component's own resting/hover/"
          f"pressed token (REPORT-ONLY: ring-offset convention pending, "
          f"docs/DECISIONS.md 2026-07-15 ruling 3):")
    for token_name in RING_OWN_FILL_TOKENS:
        token_hex = p.get(token_name)
        if not token_hex:
            print(f"    {token_name:<14} — not in palette({mode}), skipped")
            continue
        ratio = contrast_ratio(ring_rgb, hex_to_rgb(token_hex))
        print(f"    {token_name:<14} {_fmt(ratio)} : 1   "
              f"{_pass(ratio, NON_TEXT_PASS_THRESHOLD)}  (report-only)")


def ring_contrast_scan(mode: str, ring_context: str, gh: str, card_hex: str,
                        card_scene_rgb: tuple[int, int, int], shelf_hex: str,
                        shelf_scene_rgb: tuple[int, int, int]) -> None:
    """Dispatches to `ring_vs_surround`/`ring_vs_own_fill` per
    *ring_context* ("own-fill" | "surround" | "both")."""
    if ring_context in ("surround", "both"):
        ring_vs_surround(mode, gh, card_hex, card_scene_rgb, shelf_hex, shelf_scene_rgb)
    if ring_context in ("own-fill", "both"):
        ring_vs_own_fill(mode)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(
        "kit_contrast_check.py — live re-derivation of kit.md's numbers, "
        "plus the ring-contrast standing check (Baldr BLOCKER-2)."
    ))
    parser.add_argument(
        "--ring-context", choices=["own-fill", "surround", "both"], default="both",
        help=(
            "Which ring-contrast pairing(s) to report. 'surround' = ring vs "
            "every rung's own SCENE+TOKEN composite (pass/fail at the 3:1 "
            "non-text floor). 'own-fill' = ring vs an interactive "
            "component's own accent-toned fill token — report-only, the "
            "ring-offset convention has not landed yet. Default: both."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    print("=" * 78)
    print("kit_contrast_check.py — live re-derivation of kit.md's numbers")
    print(f"gui.style module: {style.__file__}")
    print(f"ring-context: {args.ring_context}")
    print("=" * 78)

    for mode in ("dark", "light"):
        p = style.palette(mode)
        gh, grgb, canvas_l, worst_l = worst_ground(mode)
        print(f"\n### {mode.upper()} — worst legal ground (kit.md §1.1) ###")
        print(f"  canvas = {p['canvas']}  L*={canvas_l:.2f}")
        print(f"  worst ground = {gh}  L*={worst_l:.2f}  (band {KIT_GROUND_BAND_DELTA_L:+.1f} in the "
              f"{'lighter' if mode == 'dark' else 'darker'} direction)")

        card_hex, card_is_proposed = kit_card_token(mode)
        card_fallback_hex = kit_card_fallback(mode)
        shelf_hex_proposed = kit_shelf_token(mode, card_hex)
        shelf_hex_fallback = kit_shelf_token(mode, card_fallback_hex)

        print(f"\n  card  (FLAT/TOKEN) = {card_hex}"
              + ("  *** PROPOSED — not in gui.style, needs Kaya's nod ***" if card_is_proposed else "  (= panel, real token, no proposal needed)"))
        if card_is_proposed:
            print(f"  card  live fallback = {card_fallback_hex}  (= 'raised', the nearest real rung)")
        print(f"  shelf (FLAT/TOKEN) using {'PROPOSED' if card_is_proposed else 'real'} card = {shelf_hex_proposed}")
        if card_is_proposed:
            print(f"  shelf (FLAT/TOKEN) using live-fallback card = {shelf_hex_fallback}")

        # ---- §2.1 tier-invariance: SCENE composite vs FLAT/TOKEN target ----
        card_scene_rgb = scene_card_rgb(mode, gh)
        shelf_scene_rgb_proposed = scene_shelf_rgb(gh, card_hex)
        shelf_scene_rgb_fallback = scene_shelf_rgb(gh, card_fallback_hex)
        card_scene_l = y_to_lstar(relative_luminance(card_scene_rgb))
        card_token_l = lstar_of_hex(card_hex)
        shelf_scene_l = y_to_lstar(relative_luminance(shelf_scene_rgb_proposed))
        shelf_token_l = lstar_of_hex(shelf_hex_proposed)

        print(f"\n  §2.1 tier-invariance:")
        print(f"    card  SCENE composite = {rgb_to_hex(card_scene_rgb)}  L*={card_scene_l:.2f}"
              f"   (token target {card_hex} L*={card_token_l:.2f}, dL*={abs(card_scene_l - card_token_l):.2f})")
        print(f"    shelf SCENE composite (proposed card) = {rgb_to_hex(shelf_scene_rgb_proposed)}"
              f"  L*={shelf_scene_l:.2f}   (token target {shelf_hex_proposed} L*={shelf_token_l:.2f},"
              f" dL*={abs(shelf_scene_l - shelf_token_l):.2f})")
        if card_is_proposed:
            shelf_scene_l_fb = y_to_lstar(relative_luminance(shelf_scene_rgb_fallback))
            shelf_token_l_fb = lstar_of_hex(shelf_hex_fallback)
            print(f"    shelf SCENE composite (live-fallback card) = {rgb_to_hex(shelf_scene_rgb_fallback)}"
                  f"  L*={shelf_scene_l_fb:.2f}   (fallback token target {shelf_hex_fallback}"
                  f" L*={shelf_token_l_fb:.2f}, dL*={abs(shelf_scene_l_fb - shelf_token_l_fb):.2f})")

        # ---- §6.1/§6.2 — ink on CARD, SCENE and FLAT/TOKEN ----
        print(f"\n  §6.{'1' if mode == 'dark' else '2'} {mode.upper()} — ink on CARD")
        print("  -- SCENE (glass composite over worst legal ground) --")
        print_ink_table(mode, card_scene_rgb, "card/SCENE")
        print("  -- FLAT/TOKEN (opaque proposed-card token) --")
        print_ink_table(mode, hex_to_rgb(card_hex), "card/TOKEN")
        if card_is_proposed:
            print("  -- FLAT/TOKEN, LIVE FALLBACK (opaque 'raised' instead of unratified card) --")
            print_ink_table(mode, hex_to_rgb(card_fallback_hex), "card/FALLBK")

        # on_danger on danger_fill — opaque, both tiers, per kit.md §6.1/6.2
        od_ratio = contrast_hex(p["on_danger"], p["danger_fill"])
        print(f"    on_danger on danger_fill              {_fmt(od_ratio)} : 1   {_pass(od_ratio)}  (opaque always)")

        # ---- §6.3 — the shelf (text/muted only, both tiers) ----
        print(f"\n  §6.3 {mode.upper()} — the shelf (chrome + labels only: text/muted legal)")
        print("  -- SCENE (proposed-card wash) --")
        print_ink_table(mode, shelf_scene_rgb_proposed, "shelf/SCENE", legal_inks={"text", "muted"})
        if card_is_proposed:
            print("  -- SCENE, LIVE FALLBACK (raised wash instead of unratified card) --")
            print_ink_table(mode, shelf_scene_rgb_fallback, "shelf/FALLBK", legal_inks={"text", "muted"})
        print("  -- FLAT/TOKEN (opaque shelf token, proposed-card derived) --")
        print_ink_table(mode, hex_to_rgb(shelf_hex_proposed), "shelf/TOKEN", legal_inks={"text", "muted"})

        # ---- §4.4 well-ink law (opaque, unaffected by tier) ----
        print(f"\n  §4.4 {mode.upper()} — semantic ink AS TEXT on `well` (forbidden pair, law check)")
        well_rgb = hex_to_rgb(p["well"])
        for ink in SEMANTIC_INKS:
            ratio = contrast_ratio(hex_to_rgb(p[ink]), well_rgb)
            print(f"    {ink:<7} on well   {_fmt(ratio)} : 1   {_pass(ratio)}  (illegal regardless of pass/fail — §4.4)")

        # ---- per-surface minimum-alpha floors ----
        # Two checkpoints matter: alpha=0 (pure ground, no fill at all — the
        # theoretical worst case, useful for margin analysis / "does a floor
        # even bind") and MIN_PANEL_GLASS_ALPHA (0.50 — the REAL enforced
        # clamp: no settings file can push a registered glass pane below it).
        print(f"\n  Per-surface minimum-alpha floor scan (semantic inks, worst legal ground):")
        print(f"  (legal clamp floor MIN_PANEL_GLASS_ALPHA = {MIN_PANEL_GLASS_ALPHA})")
        for surface, ceil_a in (
            ("card", KIT_GLASS_CARD_ALPHA_LIGHT if mode == "light" else KIT_GLASS_CARD_ALPHA_DARK),
            ("shelf", KIT_GLASS_SHELF_ALPHA),
        ):
            for ink in SEMANTIC_INKS:
                min_a, r_zero, r_ceil = alpha_floor_scan(mode, surface, ink, card_hex, gh, 0.0, ceil_a)
                _, r_floor, _ = alpha_floor_scan(mode, surface, ink, card_hex,
                                                  gh, MIN_PANEL_GLASS_ALPHA, MIN_PANEL_GLASS_ALPHA)
                if min_a is None:
                    verdict = f"NEVER clears 4.5:1 in [0,{ceil_a}] (worst {min(r_zero, r_ceil):.2f})"
                elif min_a <= 0.0 + 1e-9:
                    verdict = "no floor binds — clears 4.5:1 even at alpha=0"
                else:
                    verdict = f"needs alpha >= {min_a:.2f} to clear 4.5:1"
                print(f"    {surface:<5} {ink:<7} alpha=0: {r_zero:5.2f}  "
                      f"alpha={MIN_PANEL_GLASS_ALPHA}(clamp): {r_floor:5.2f}  "
                      f"alpha={ceil_a}(shipped): {r_ceil:5.2f}   {verdict}")

        # ---- ring-contrast standing check (Baldr BLOCKER-2 / ruling 3) ----
        ring_contrast_scan(mode, args.ring_context, gh, card_hex, card_scene_rgb,
                            shelf_hex_proposed, shelf_scene_rgb_proposed)

    # ---- kit.html baked-token audit: do its CSS/JS constants match live? ----
    # These are kit.html's CURRENT baked constants (corrected 2026-07-14 as
    # part of this same pass — see kit.md's top-of-file note). Kept as a
    # literal snapshot here on purpose: this audit exists to catch the NEXT
    # drift between kit.html's hand-baked tokens and the live tree, the same
    # way it caught good/sim this time.
    print("\n" + "=" * 78)
    print("kit.html baked-token audit — do its literal hex constants match")
    print("what gui.style computes for the SAME tokens today?")
    print("=" * 78)
    KIT_HTML_LIGHT_BAKED = {
        "good": "#0f7655", "warn": "#915b00", "crit": "#ad343a",
        "accent": "#2563c9", "sim": "#08727e", "muted": "#525D72",
        "text": "#131A28", "canvas": "#E6EBF3", "panel": "#FFFFFF",
    }
    p_light = style.palette("light")
    for ink, baked in KIT_HTML_LIGHT_BAKED.items():
        live = p_light.get(ink, "?")
        same = live.lower() == baked.lower()
        print(f"  light.{ink:<7} kit.html bakes {baked}   live palette() = {live}   "
              f"{'OK' if same else '*** MISMATCH ***'}")


if __name__ == "__main__":
    main()
