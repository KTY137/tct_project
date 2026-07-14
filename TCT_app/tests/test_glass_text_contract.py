"""Which ink tokens are CLEARED for text on a registered glass pane — and the
proof that the laser safety banner is not sitting on one.

BACKGROUND. ``docs/design/glass_council/baldr.md`` §1.2 established a "scrim
floor": the panel-glass and canvas alphas ship with a clamped legal range
(``MIN_PANEL_GLASS_ALPHA`` / ``MIN_BACKDROP_CANVAS_ALPHA``) chosen so that text
on a glass pane stays legible over ANY desktop. But that contract only ever
verified ONE token — ``muted`` (its published 4.90/5.16 numbers reproduce
exactly; see ``test_baldr_scrim_floor_numbers_reproduce``). ``faint``, the token
that carried exactly the small caption/hint text that lands on glass cards, was
never measured at that corner. It is ~2.0:1 there.

So the contract had a hole, and this file closes it: it names the tokens that
are cleared for text on glass, measures them at the code's own legal alpha
FLOORS (not at the shipped defaults — the floors are what a slider or a
hand-edited settings file can actually reach) against the WORST case desktop
(pure white AND pure black), and pins that every other ink is NOT cleared.

The compositing stack under a glass pane, worst case:

    desktop  ->  window canvas fill  rgba(bg,    canvas_alpha)
             ->  pane fill           rgba(panel, panel_glass_alpha)

OWNED-GLASS EXTENSION (Kaya, 2026-07-14: "ja drop die regel wir sind designer
und designen geile Sachen"). The unknown-desktop premise above died with the
owned-glass ratification (23aea87): the ground beneath every in-scene pane is
now the app's own band-clamped ambient wash (ΔL* <= 4.0, kit §1.1, pinned by
tests/test_ambient_ground.py), NOT a wallpaper. Machine-measured against THAT
ground (scripts/kit_contrast_check.py, arbitrated 28e6dec), every semantic
state ink clears WCAG AA at the shipped glass alphas — so the whitelist now
carries them, certified below against the same owned-glass ground the material
contract pins, with a DERIVED alpha floor so the whitelist can never outrun the
alphas that keep it legible. The pure-white/black desktop check is kept only as
a belt-and-suspenders floor for the neutral inks (text/muted), which stay legal
over ANY conceivable ground.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui.style import (
    DARK,
    GLASS_CARD_ALPHA_DARK,
    GLASS_CARD_ALPHA_LIGHT,
    LIGHT,
    MIN_BACKDROP_CANVAS_ALPHA,
    MIN_PANEL_GLASS_ALPHA,
    PANEL_GLASS_ALPHA,
    _blend,
)
from tests.test_material_contract import worst_legal_ground
from tests.test_palette_contrast import AA_TEXT, contrast

# ── THE GLASS INK WHITELIST ────────────────────────────────────────────────
# Which ink tokens a registered glass surface may render TEXT in. Two tiers,
# because they are certified against two different grounds.
#
# NEUTRAL inks (`text`/`muted`) are legal over ANY conceivable ground — even
# the now-retired unknown-desktop premise this file was born under. `text` is
# the body ink; `muted` is the quiet-caption ink Baldr certified. They are the
# belt-and-suspenders floor, still measured against a pure-white AND pure-black
# desktop below.
GLASS_NEUTRAL_TEXT_TOKENS = ("text", "muted")

# SEMANTIC state inks are legal on OWN-ground glass (Kaya, 2026-07-14, ratified:
# "ja drop die regel wir sind designer und designen geile Sachen"). The
# owned-glass ratification (23aea87) retired the unknown desktop; the ground is
# now the app's band-clamped ambient wash (ΔL* <= 4.0), against which every
# semantic ink was machine-measured to clear WCAG AA at the shipped alphas
# (scripts/kit_contrast_check.py, arbitrated 28e6dec). These are the kit's §6
# canonical five; `danger`/`armed` are byte-aliases of `crit`/`warn` and are
# legal by the same measurement.
GLASS_SEMANTIC_TEXT_TOKENS = ("good", "warn", "crit", "accent", "sim")

# The full whitelist a registered glass pane may render text in.
GLASS_SAFE_TEXT_TOKENS = GLASS_NEUTRAL_TEXT_TOKENS + GLASS_SEMANTIC_TEXT_TOKENS

# Tokens that STAY off glass: the hazard FILL + its label ink (they belong on an
# OPAQUE hazard surface, never composited against any ground) and `faint`
# (retired for text everywhere — it fails AA on every surface). See
# test_hazard_fill_and_faint_stay_off_glass.
GLASS_FORBIDDEN_TEXT_TOKENS = ("danger_fill", "on_danger", "on_armed", "faint")

# Every desktop wallpaper is somewhere between these two (the retired premise;
# still the ground for the neutral belt-and-suspenders check below).
WORST_CASE_DESKTOPS = ("#FFFFFF", "#000000")


def glass_backdrop(palette: dict, desktop: str,
                   canvas_alpha: float = MIN_BACKDROP_CANVAS_ALPHA,
                   panel_alpha: float = MIN_PANEL_GLASS_ALPHA) -> str:
    """The effective pixel behind text on a registered glass pane.

    Round-03 kit: the pane fill is the `card` rung (kit §2.1 — gui/style.py's
    glassPane rules paint ``_rgba(p['card'], alpha)`` since the card-token
    beat), so THAT is what this model composites. Light card == panel byte
    for byte, so Baldr's published light-theme numbers reproduce unchanged."""
    canvas = _blend(palette["bg"], desktop, canvas_alpha)
    return _blend(palette["card"], canvas, panel_alpha)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("desktop", WORST_CASE_DESKTOPS)
@pytest.mark.parametrize("token", GLASS_NEUTRAL_TEXT_TOKENS)
def test_glass_safe_ink_clears_aa_at_the_legal_alpha_floors(mode, desktop, token):
    """The NEUTRAL belt-and-suspenders: text/muted clear AA even under the
    retired unknown-desktop premise, at the FLOORS (not the shipped alphas) —
    a user can drag the sliders there, and a hand-edited settings file is
    clamped to exactly this. Semantic inks are certified separately, against
    the owned-glass ground (see the OWNED-GLASS section below)."""
    p = LIGHT if mode == "light" else DARK
    bg = glass_backdrop(p, desktop)
    got = contrast(p[token], bg)
    assert got >= AA_TEXT, (
        f"[{mode}] `{token}` on a glass pane over a {desktop} desktop at the "
        f"legal alpha floors (canvas={MIN_BACKDROP_CANVAS_ALPHA}, "
        f"panel={MIN_PANEL_GLASS_ALPHA}) = {got:.2f}:1 — below AA. Either raise "
        f"the floor or drop the token from GLASS_SAFE_TEXT_TOKENS.")


def test_semantic_ink_is_now_legal_on_own_ground_glass():
    """The law change (Kaya, 2026-07-14): semantic STATE words may live on a
    registered glass surface. This INVERTS the pre-owned-glass rule that kept
    them off glass however good their contrast was — that rule encoded the
    unknown-desktop belief, and the belief died (23aea87). The whitelist now
    carries the kit's §6 canonical five; the certification is the owned-glass
    floor section below, not this membership check."""
    for token in GLASS_SEMANTIC_TEXT_TOKENS:
        assert token in GLASS_SAFE_TEXT_TOKENS, token
    # danger/armed are byte-aliases of crit/warn — legal by the same measurement.
    assert LIGHT["danger"] == LIGHT["crit"] and DARK["danger"] == DARK["crit"]
    assert LIGHT["armed"] == LIGHT["warn"] and DARK["armed"] == DARK["warn"]


def test_hazard_fill_and_faint_stay_off_glass():
    """What did NOT move. The hazard FILL and its label ink belong on an OPAQUE
    hazard surface (they are never composited against a ground); `faint` is
    retired for text everywhere. None may enter the glass whitelist — the
    extension is semantic STATE ink, not "anything goes"."""
    for token in GLASS_FORBIDDEN_TEXT_TOKENS:
        assert token not in GLASS_SAFE_TEXT_TOKENS, token


# --------------------------------------------------------------------------- #
# OWNED-GLASS SEMANTIC INK — certified against the band-clamped ambient ground #
# --------------------------------------------------------------------------- #
# The compositing model here is the SAME one scripts/kit_contrast_check.py runs
# and tests/test_material_contract.py pins: a glass surface paints "one rung up
# at its rung's alpha" over the WORST LEGAL GROUND — the canvas L* shifted by
# the full ΔL* 4.0 band edge (kit §1.1). ``worst_legal_ground`` is imported from
# the material contract so both files measure against byte-identical ground.

# The shipped alphas a registered glass surface can paint at:
#   card — the SCENE glass-card fill (fixed, kit §2.1): raised@0.62 dark /
#          panel@0.86 light.
#   pane — the glass-pane tint: `card` at the tunable pane alpha; the LOWEST it
#          can legally reach is MIN_PANEL_GLASS_ALPHA (0.50 clamp floor, below).
_GLASS_SURFACE_ALPHAS = {
    ("card", "dark"): GLASS_CARD_ALPHA_DARK,
    ("card", "light"): GLASS_CARD_ALPHA_LIGHT,
    ("pane", "dark"): PANEL_GLASS_ALPHA,
    ("pane", "light"): PANEL_GLASS_ALPHA,
}

# Stated engineering margin above the DERIVED semantic floor.
SEMANTIC_FLOOR_BUFFER = 0.10


def _glass_fill(mode: str, surface: str) -> str:
    """The opaque fill a glass surface paints "one rung up" before its alpha."""
    p = LIGHT if mode == "light" else DARK
    if surface == "card":
        return p["raised"] if mode == "dark" else p["panel"]
    return p["card"]                          # the pane tint washes `card`


def _min_alpha_clearing_aa(mode: str, surface: str, token: str,
                            step: float = 0.005) -> float | None:
    """The smallest surface alpha at which *token* clears AA on *surface* over
    the worst legal ground — found by an explicit scan (never assumed
    monotonic), the same method kit_contrast_check.alpha_floor_scan uses."""
    p = LIGHT if mode == "light" else DARK
    ground = worst_legal_ground(mode)
    fill = _glass_fill(mode, surface)
    n = round(1.0 / step)
    for i in range(n + 1):
        a = i / n
        if contrast(p[token], _blend(fill, ground, a)) >= AA_TEXT:
            return a
    return None


def _semantic_glass_floor() -> tuple[float, str, str, str]:
    """DERIVE (never hardcode) the binding semantic floor: the HIGHEST minimum
    alpha any semantic ink needs to clear AA on any glass surface, over the
    worst legal ground. Returns (alpha, mode, token, surface) — the binding
    pair, so a failure can name it. Recomputes from the live palette, so it can
    never rot to a stale magic number."""
    binding = (0.0, "-", "-", "-")
    for mode in ("dark", "light"):
        for surface in ("card", "pane"):
            for token in GLASS_SEMANTIC_TEXT_TOKENS:
                a = _min_alpha_clearing_aa(mode, surface, token)
                assert a is not None, (
                    f"[{mode}] `{token}` never clears AA on the glass {surface} "
                    f"even at full opacity — it cannot be on the whitelist")
                if a > binding[0]:
                    binding = (a, mode, token, surface)
    return binding


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("token", GLASS_SEMANTIC_TEXT_TOKENS)
def test_semantic_ink_clears_aa_on_the_shipped_glass(mode, token):
    """Every whitelisted semantic ink clears AA on the ACTUAL shipped glass
    composites (card AND pane), over the worst legal ground — the honest
    certification that each whitelist entry is legible at what ships, not only
    at some floor."""
    p = LIGHT if mode == "light" else DARK
    ground = worst_legal_ground(mode)
    for surface in ("card", "pane"):
        alpha = _GLASS_SURFACE_ALPHAS[(surface, mode)]
        bg = _blend(_glass_fill(mode, surface), ground, alpha)
        got = contrast(p[token], bg)
        assert got >= AA_TEXT, (
            f"[{mode}] `{token}` on the shipped glass {surface} (alpha {alpha}) "
            f"= {got:.2f}:1 — below AA")


def test_shipped_glass_alphas_stay_above_the_semantic_floor():
    """THE floor pin. Every alpha a registered glass surface can legally paint
    at must stay >= the DERIVED semantic floor + buffer. A future alpha tweak
    below it fails here, naming the binding token pair — so the whitelist can
    never quietly outrun the alphas that make it legible.

    The worst legal SHIPPED alpha is MIN_PANEL_GLASS_ALPHA: a slider / hand-
    edited settings file can drag the pane tint down to exactly the clamp
    floor, so it is measured alongside the fixed card/pane defaults."""
    floor_a, mode, token, surface = _semantic_glass_floor()
    required = floor_a + SEMANTIC_FLOOR_BUFFER
    shipped = dict(_GLASS_SURFACE_ALPHAS)
    shipped[("pane", "clamp-floor")] = MIN_PANEL_GLASS_ALPHA
    offenders = {k: a for k, a in shipped.items() if a < required}
    assert not offenders, (
        f"semantic ink binds on glass at alpha >= {floor_a:.3f} (the binding "
        f"pair is {mode} `{token}` on the glass {surface}); with the "
        f"{SEMANTIC_FLOOR_BUFFER:.2f} buffer every legal glass alpha must be "
        f">= {required:.3f}. Below the floor: {offenders}. Raise the alpha, or "
        f"drop the token(s) from GLASS_SEMANTIC_TEXT_TOKENS.")


def test_semantic_floor_reproduces_the_arbitrated_measurement():
    """Anchors the DERIVATION (not the guard) to the arbitrated number: the
    machine ruled the light-glass floor at alpha >= 0.24, `good` binding
    (28e6dec — "semantic ink on light glass needs alpha >= 0.24; `good`
    binds"). If the derivation ever wanders far from that, the MODEL changed
    and this fails deliberately, instead of the guard silently trusting a
    broken model. dark clears at every alpha, so the binding is always light."""
    floor_a, mode, token, _surface = _semantic_glass_floor()
    assert mode == "light" and token == "good", (floor_a, mode, token)
    assert 0.22 <= floor_a <= 0.26, floor_a


def test_faint_is_the_hole_baldr_never_measured():
    """`faint` is excluded for the OTHER reason: it genuinely fails. Pins the
    actual number from the audit — ~2.0-2.1:1 on worst-case glass, i.e. the
    caption ink had less than half the legibility it needed. If a future pass
    darkens `faint` until it passes, this fails and the author must decide
    deliberately whether the token still has a role or has become `muted`."""
    for mode, p in (("light", LIGHT), ("dark", DARK)):
        assert "faint" not in GLASS_SAFE_TEXT_TOKENS
        worst = min(contrast(p["faint"], glass_backdrop(p, desk))
                    for desk in WORST_CASE_DESKTOPS)
        assert worst < AA_TEXT, f"[{mode}] faint now clears {worst:.2f}:1"
    light_worst = min(contrast(LIGHT["faint"], glass_backdrop(LIGHT, desk))
                      for desk in WORST_CASE_DESKTOPS)
    assert 1.9 <= light_worst <= 2.2, light_worst


def test_baldr_scrim_floor_numbers_reproduce():
    """Baldr §1.2 published 4.90 at the floors and 5.16 at the shipped alphas
    for `muted`. Reproducing them is what makes it safe to say the REST of that
    contract was never checked — the method was right, the coverage was not."""
    from gui.style import BACKDROP_CANVAS_ALPHA, PANEL_GLASS_ALPHA

    floor = min(contrast(LIGHT["muted"], glass_backdrop(LIGHT, desk))
                for desk in WORST_CASE_DESKTOPS)
    shipped = min(
        contrast(LIGHT["muted"],
                 glass_backdrop(LIGHT, desk, BACKDROP_CANVAS_ALPHA, PANEL_GLASS_ALPHA))
        for desk in WORST_CASE_DESKTOPS)
    assert round(floor, 2) == 4.91, floor        # published 4.90 (rounding)
    assert round(shipped, 2) == 5.16, shipped    # published 5.16 — exact


# --------------------------------------------------------------------------- #
# Hazard surfaces are OPAQUE at every tier (ratified) — the laser banner
# --------------------------------------------------------------------------- #

def _laser_panel():
    from PySide6.QtWidgets import QApplication

    from devices.laser_manual import LaserManualMetadata
    from devices.waveform_generator import WaveformGenerator
    from gui.laser_panel import LaserPanel

    QApplication.instance() or QApplication([])
    return LaserPanel(LaserManualMetadata(), WaveformGenerator(simulation=True))


def test_laser_safety_banner_is_never_a_glass_pane():
    """The manual-laser honesty banner ("emission unknown to software — verify
    at the head") is a HAZARD surface. By ratified law it is opaque at every
    glass tier, so it must never be in the panel-glass registry — not even
    when the experimental switch is ON."""
    from gui.panel_kit import registered_glass_panes, set_panel_glass

    panel = _laser_panel()
    try:
        set_panel_glass(True)
        try:
            assert panel._banner_card not in registered_glass_panes()
            assert not panel._banner_card.property("glassPane")
            # ... and its own stylesheet pins an OPAQUE fill, so even a future
            # accidental registration cannot composite it against the desktop
            # (a widget's own sheet outranks the app-wide glassPane rule).
            from gui.style import palette
            for mode in ("light", "dark"):
                panel.refresh_theme(mode)
                sheet = panel._banner_card.styleSheet()
                assert f"background: {palette(mode)['panel']}" in sheet, sheet
        finally:
            set_panel_glass(False)
    finally:
        panel.shutdown()


def test_laser_safety_banner_ink_clears_aa_in_both_themes():
    """The banner text itself — measured on the surface it actually paints on
    (an opaque panel), in both themes. It used to be 4.07:1 in light."""
    from gui.style import palette

    panel = _laser_panel()
    try:
        for mode in ("light", "dark"):
            panel.refresh_theme(mode)
            p = palette(mode)
            assert p["warn"] in panel._lbl_banner.styleSheet()
            got = contrast(p["warn"], p["panel"])
            assert got >= AA_TEXT, f"[{mode}] banner ink {got:.2f}:1"
    finally:
        panel.shutdown()
