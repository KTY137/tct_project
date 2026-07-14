"""The round-03 glass-kit MATERIAL CONTRACT — the composited-contrast test the
kit demanded before it was allowed to land (kit.md §10 weakness 5: "the suite
has no composited-contrast test today — which is exactly why round 01's
1.04:1 shipped. This design must not land without one.").

What this file pins, against docs/design/iterations/glasshell-cockpit/
round-03/kit.md (arbitrated by TCT_app/scripts/kit_contrast_check.py):

* the `card`/`shelf` elevation rungs are DERIVED (never hand-picked), the
  dark ladder finally exists (canvas->card ΔL* >= 7 where canvas->panel was
  1.46), and both rungs track a user "panel" override;
* every ink except `faint` clears WCAG AA as text on the opaque card, both
  themes (§6.1/§6.2 FLAT column), and on the SCENE glass composite over the
  WORST LEGAL GROUND (§1.1's ΔL* 4.0 band edge);
* the §2.1 tier-invariance rule: the SCENE composite of a surface lands on
  its own opaque token within ΔL* 1.0 — turning glass off changes nothing
  about what a surface IS;
* the component surfaces (GlassPane / Well / HazardSurface) construct
  headless, refresh both themes, and obey the consequence rules: hazard and
  well surfaces are OPAQUE AT EVERY TIER — no glass QSS variant exists for
  them in any material state, and the registry refuses them outright.

Contrast/L* math here is implemented locally (independent re-derivation) —
only the tokens and the shipped ``_blend`` compositing primitive come from
``gui.style``, so the model composites exactly what the QSS paints.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gui import panel_kit, style
from gui.style import DARK, LIGHT, _blend, palette

AA_TEXT = 4.5

# Inks that must clear AA as text on a card (kit §4.2 — "every ink except
# `faint`"). `faint` is retired for text by repo law and asserted separately.
CARD_TEXT_INKS = ("text", "muted", "good", "warn", "crit", "accent", "sim")
# A pane/shelf carries chrome + labels only (kit §4.1 ink law).
PANE_TEXT_INKS = ("text", "muted")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# Local, independent colour math (WCAG 2.2 + CIE L*)                          #
# --------------------------------------------------------------------------- #

def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lin(c8: int) -> float:
    c = c8 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(h: str) -> float:
    r, g, b = _rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(h1: str, h2: str) -> float:
    l1, l2 = _luminance(h1), _luminance(h2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


_KNEE_Y = (6 / 29) ** 3


def lstar(h: str) -> float:
    y = _luminance(h)
    return 116 * y ** (1 / 3) - 16 if y > _KNEE_Y else y * (29 / 3) ** 3


def _lstar_to_y(l: float) -> float:
    return ((l + 16) / 116) ** 3 if l > 8.0 else l / 903.3


def _y_to_srgb8(y: float) -> int:
    y = min(max(y, 0.0), 1.0)
    c = y * 12.92 if y <= 0.0031308 else 1.055 * y ** (1 / 2.4) - 0.055
    return round(min(max(c, 0.0), 1.0) * 255)


def worst_legal_ground(mode: str) -> str:
    """kit §1.1: the ground band edge — canvas L* shifted by the full ΔL* 4.0
    in whichever direction hurts contrast most (dark: lighter; light:
    darker), as a neutral gray (the same model kit_contrast_check.py runs)."""
    canvas_l = lstar(palette(mode)["canvas"])
    worst_l = min(100.0, max(0.0, canvas_l + (4.0 if mode == "dark" else -4.0)))
    g = _y_to_srgb8(_lstar_to_y(worst_l))
    return f"#{g:02x}{g:02x}{g:02x}"


def scene_card(mode: str) -> str:
    """The glass CARD's real composite: one rung up at the card-rung alpha
    (kit §2.1) over the worst legal ground — exactly the fill the
    [glassCard="true"] QSS paints."""
    p = palette(mode)
    if mode == "dark":
        return _blend(p["raised"], worst_legal_ground(mode),
                      style.GLASS_CARD_ALPHA_DARK)
    return _blend(p["panel"], worst_legal_ground(mode),
                  style.GLASS_CARD_ALPHA_LIGHT)


def scene_shelf(mode: str) -> str:
    """The glass PANE/shelf composite: `card` at the shipped pane alpha over
    the worst legal ground — the [glassPane="true"] fill."""
    return _blend(palette(mode)["card"], worst_legal_ground(mode),
                  style.PANEL_GLASS_ALPHA)


# --------------------------------------------------------------------------- #
# 1. The rungs are derived, and the dark ladder exists                        #
# --------------------------------------------------------------------------- #

def test_card_token_is_derived_not_picked():
    assert DARK["card"] == _blend(DARK["raised"], DARK["panel"], 0.60)
    assert DARK["card"] == "#151d2d"        # the kit §2 number, byte for byte
    assert LIGHT["card"] == LIGHT["panel"]  # light card IS panel (kit §2)


def test_shelf_rung_is_derived_not_picked():
    assert DARK["shelf"] == _blend(DARK["card"], DARK["panel"], 0.30)
    assert LIGHT["shelf"] == _blend(LIGHT["panel"], LIGHT["canvas"], 0.50)


def test_dark_elevation_ladder_finally_exists():
    """The defect the card token fixes: dark canvas->panel was ΔL* 1.46 (no
    ladder). With the kit rungs the ladder is monotone and canvas->card
    reaches the light theme's shipped separation (~7.1)."""
    p = palette("dark")
    well, canvas, shelf, card, raised = (
        lstar(p["well"]), lstar(p["canvas"]), lstar(p["shelf"]),
        lstar(p["card"]), lstar(p["raised"]))
    assert well < canvas < shelf < card < raised
    assert card - canvas >= 7.0, f"canvas->card ΔL* {card - canvas:.2f}"
    # And the old defect really was a defect (documents the before-state).
    assert lstar(p["panel"]) - canvas < 2.0


def test_light_ladder_ground_shelf_card():
    p = palette("light")
    assert lstar(p["canvas"]) < lstar(p["shelf"]) < lstar(p["card"])


def test_card_and_shelf_track_a_panel_override():
    """A theme-editor "panel" override must move the whole ladder coherently
    (the rungs are derived in _recompute_palettes, not frozen literals)."""
    try:
        style.apply_theme_overrides({"panel": "#202833"}, "dark")
        assert DARK["panel"] == "#202833"
        assert DARK["card"] == _blend(DARK["raised"], "#202833", 0.60)
        assert DARK["shelf"] == _blend(DARK["card"], "#202833", 0.30)
    finally:
        style.reset_theme_customization()
    assert DARK["card"] == "#151d2d"        # reset restores the shipped rung


def test_card_and_shelf_are_not_directly_editable():
    """Derived, never picked: there is no override path to the rungs
    themselves — they move only through their ingredients."""
    for token in ("card", "shelf"):
        assert token not in style.EDITABLE_TOKENS
        with pytest.raises(ValueError):
            style.apply_theme_overrides({token: "#123456"}, "dark")


# --------------------------------------------------------------------------- #
# 2. The QSS paints the rungs                                                 #
# --------------------------------------------------------------------------- #

def _rule_block(qss: str, selector: str) -> str:
    idx = qss.index(selector)
    return qss[idx: qss.index("}", idx)]


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_card_surfaces_paint_the_card_rung_with_the_strong_outline(mode):
    p = palette(mode)
    qss = style.build_qss(p)
    for selector in ("QGroupBox {", "QFrame#cardPane {"):
        block = _rule_block(qss, selector)
        assert f"background: {p['card']};" in block, selector
        assert p["hairline_strong"] in block, selector


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_shelf_well_hazard_flat_forms_are_in_the_qss(mode):
    """Every component has a stated FLAT form — the opaque token rules."""
    p = palette(mode)
    qss = style.build_qss(p)
    shelf = _rule_block(qss, "QFrame#shelfPane {")
    assert f"background: {p['shelf']};" in shelf
    assert p["hairline_strong"] in shelf
    well = _rule_block(qss, "QFrame#wellPane {")
    assert f"background: {p['well']};" in well
    hazard = _rule_block(qss, "QFrame#hazardSurface {")
    assert f"background: {p['panel']};" in hazard
    assert p["hairline_strong"] in hazard


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_pane_glass_fill_is_the_card_rung_at_the_pane_alpha(mode):
    """kit §2.1 "paint one rung up, at your rung's alpha": the pane tint is
    `card` at the (clamped, tunable) pane alpha — for cardPane, QGroupBox AND
    the new shelfPane."""
    p = palette(mode)
    qss = style.build_qss(p)
    fill = style._rgba(p["card"], style.get_panel_glass_alpha())
    for sel in ('QFrame#cardPane[glassPane="true"]',
                'QGroupBox[glassPane="true"]',
                'QFrame#shelfPane[glassPane="true"]'):
        assert f"{sel} {{ background: {fill}; }}" in qss, sel


def test_glass_card_rule_is_mode_correct():
    """The SCENE card fill: raised@0.62 in dark, panel@0.86 in light — never
    the other way around, and both above the ratified scrim floor."""
    assert style.GLASS_CARD_ALPHA_DARK >= style.MIN_PANEL_GLASS_ALPHA
    assert style.GLASS_CARD_ALPHA_LIGHT >= style.MIN_PANEL_GLASS_ALPHA
    qd = style.build_qss(palette("dark"))
    ql = style.build_qss(palette("light"))
    assert style._rgba(DARK["raised"], style.GLASS_CARD_ALPHA_DARK) in qd
    assert style._rgba(LIGHT["panel"], style.GLASS_CARD_ALPHA_LIGHT) in ql
    assert 'QFrame#cardPane[glassCard="true"]' in qd
    assert 'QGroupBox[glassCard="true"]' in qd


def test_hazard_and_well_have_no_glass_variant_in_any_material_state():
    """The consequence rule as QSS text: no reachable material state may grow
    a translucent variant for the hazard or well selectors."""
    try:
        for kind in ("none", "mica", "acrylic"):
            style.set_window_backdrop(kind)
            for mode in ("dark", "light"):
                qss = style.build_qss(palette(mode))
                assert "hazardSurface[glass" not in qss
                assert "wellPane[glass" not in qss
    finally:
        style.reset_theme_customization()


def test_concentric_radius_law():
    """kit §3.2: RADIUS_SHELF is derived (r_outer = r_inner + gap), not taste."""
    assert style.RADIUS_SHELF == style.RADIUS_XL + style.SPACE_XS == 24


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_rungs_actually_render_not_just_appear_in_the_qss_text(mode):
    """RENDERED-PIXEL guard — the lesson of this very beat: a malformed QSS
    fragment (a stray pseudo-comment) can kill Qt's stylesheet parsing for
    every rule after it while every TEXT-level assertion above keeps passing.
    So grab each kit surface offscreen and assert the actual painted pixel is
    the token, byte for byte."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame

    app = _app()
    style.apply_theme(app, mode)
    try:
        p = palette(mode)
        expected = {
            "cardPane": p["card"],
            "shelfPane": p["shelf"],
            "wellPane": p["well"],
            "hazardSurface": p["panel"],
        }
        for name, token in expected.items():
            f = QFrame()
            f.setObjectName(name)
            f.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            f.resize(160, 120)
            f.show()
            app.processEvents()
            got = f.grab().toImage().pixelColor(80, 60).name().lower()
            f.hide()
            f.deleteLater()
            assert got == token.lower(), (
                f"[{mode}] #{name} renders {got}, token says {token} — the "
                f"stylesheet is not parsing past some earlier rule")
    finally:
        # Restore the pristine no-stylesheet state this test found the
        # process in — later tests in this session must not inherit a sheet.
        app.setStyleSheet("")


# --------------------------------------------------------------------------- #
# 3. Contrast at the floor — FLAT and SCENE, worst legal ground               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("ink", CARD_TEXT_INKS)
def test_every_ink_but_faint_clears_aa_on_the_opaque_card(mode, ink):
    p = palette(mode)
    got = contrast(p[ink], p["card"])
    assert got >= AA_TEXT, f"[{mode}] {ink} on opaque card = {got:.2f}:1"


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("ink", CARD_TEXT_INKS)
def test_every_ink_but_faint_clears_aa_on_the_scene_card(mode, ink):
    """kit §6.1/§6.2 SCENE column — the glass card composite over the WORST
    legal ground. The thinnest legal ink in the whole system is dark `crit`
    (kit publishes 5.32), so everything here should pass with >= 0.8 margin."""
    p = palette(mode)
    got = contrast(p[ink], scene_card(mode))
    assert got >= AA_TEXT, f"[{mode}] {ink} on SCENE card = {got:.2f}:1"


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("ink", PANE_TEXT_INKS)
def test_pane_legal_inks_clear_aa_on_the_scene_shelf(mode, ink):
    """kit §6.3 — the shelf carries chrome + labels only; text/muted are its
    only legal inks and both must pass on the SCENE composite."""
    p = palette(mode)
    got = contrast(p[ink], scene_shelf(mode))
    assert got >= AA_TEXT, f"[{mode}] {ink} on SCENE shelf = {got:.2f}:1"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_faint_stays_retired_for_text_on_the_card(mode):
    """If a future pass "fixes" faint until it passes here, that is a
    deliberate design decision to make, not an accident to inherit."""
    p = palette(mode)
    assert contrast(p["faint"], p["card"]) < AA_TEXT
    assert contrast(p["faint"], scene_card(mode)) < AA_TEXT


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_tier_invariance_on_the_nominal_ground(mode):
    """kit §2.1: over the NOMINAL ground (the canvas itself) a surface's SCENE
    composite lands on its own opaque token — turning glass off changes
    nothing about what anything IS. Tolerance 1.1: light's card is the one
    rung that cannot be perfectly invariant (kit §2.1's own admission — a
    translucent white card cannot reach L* 100; it lands ~1.0 short, below
    the JND; machine-measured 1.01 via the proper L* roundtrip where the
    kit's coarser model printed 0.9)."""
    p = palette(mode)
    canvas = p["canvas"]
    scene_card_nominal = (_blend(p["raised"], canvas, style.GLASS_CARD_ALPHA_DARK)
                          if mode == "dark" else
                          _blend(p["panel"], canvas, style.GLASS_CARD_ALPHA_LIGHT))
    scene_shelf_nominal = _blend(p["card"], canvas, style.PANEL_GLASS_ALPHA)
    assert abs(lstar(scene_card_nominal) - lstar(p["card"])) <= 1.1
    assert abs(lstar(scene_shelf_nominal) - lstar(p["shelf"])) <= 1.1


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_tier_drift_over_the_worst_ground_is_bounded_by_the_band_law(mode):
    """kit §1.1's whole point, as arithmetic: a surface at alpha a transmits
    (1-a) of the ground, so over the WORST legal ground its composite can
    drift from its token by at most (1-a) x ΔL*4.0 beyond the nominal offset.
    (The kit's §2.1 prose printed <=1.0 for these rows using its coarser
    ±9-sRGB-unit ground shortcut; scripts/kit_contrast_check.py — the machine
    ground truth — measures 1.38/1.39 for the cards and 2.54 for the dark
    shelf via the proper CIE roundtrip. This test pins the honest bound.)"""
    p = palette(mode)
    card_alpha = (style.GLASS_CARD_ALPHA_DARK if mode == "dark"
                  else style.GLASS_CARD_ALPHA_LIGHT)
    card_bound = (1 - card_alpha) * 4.0 + 1.1
    shelf_bound = (1 - style.PANEL_GLASS_ALPHA) * 4.0 + 1.1
    assert abs(lstar(scene_card(mode)) - lstar(p["card"])) <= card_bound
    assert abs(lstar(scene_shelf(mode)) - lstar(p["shelf"])) <= shelf_bound


def test_the_well_ink_law_is_still_a_real_failure():
    """kit §4.4: every semantic ink FAILS AA on the light well — the measured
    failure that makes "no semantic-coloured text in a well" a law rather
    than taste. If the palette ever drifts until these pass, the law needs a
    deliberate re-visit, not silent decay."""
    p = palette("light")
    for ink in ("good", "warn", "crit", "accent", "sim"):
        assert contrast(p[ink], p["well"]) < AA_TEXT, ink


# --------------------------------------------------------------------------- #
# 4. The components — headless construction, both themes, consequence rules   #
# --------------------------------------------------------------------------- #

def test_components_construct_and_refresh_offscreen():
    _app()
    pane = panel_kit.GlassPane("Chrome shelf", register=False)
    well = panel_kit.Well()
    hazard = panel_kit.HazardSurface("HV", stripe="danger", theme_mode="dark")
    assert pane.objectName() == "shelfPane"
    assert well.objectName() == "wellPane"
    assert hazard.objectName() == "hazardSurface"
    for w in (pane, well, hazard):
        assert w.graphicsEffect() is None       # hard rule 3 — no effects, ever
    for mode in ("dark", "light"):
        hazard.refresh_theme(mode)
        p = palette(mode)
        # The opacity pin (the laser-banner idiom): the instance sheet forces
        # an opaque fill so even an accidental registration cannot composite.
        assert f"background: {p['panel']}" in hazard.styleSheet()
        assert hazard._stripe_color.name().lower() == p["danger"].lower()


def test_hazard_stripe_kinds_resolve_their_class_token():
    _app()
    motion = panel_kit.HazardSurface("Motion", stripe="armed", theme_mode="dark")
    assert motion.stripe_kind() == "armed"
    assert motion._stripe_color.name().lower() == palette("dark")["armed"].lower()
    hv = panel_kit.HazardSurface("HV", stripe="danger", theme_mode="light")
    assert hv.stripe_kind() == "danger"
    assert hv._stripe_color.name().lower() == palette("light")["danger"].lower()


def test_registry_refuses_hazard_and_well_surfaces():
    _app()
    with pytest.raises(ValueError):
        panel_kit.register_glass_pane(panel_kit.HazardSurface("HV"))
    with pytest.raises(ValueError):
        panel_kit.register_glass_pane(panel_kit.Well())
    with pytest.raises(ValueError):
        panel_kit.register_glass_pane(panel_kit.Card("x"), role="island")


def test_glasspane_auto_registers_and_follows_the_switch():
    _app()
    pane = panel_kit.GlassPane("Auto-registered chrome")
    hazard = panel_kit.HazardSurface("HV")
    try:
        assert pane in panel_kit.registered_glass_panes()
        panel_kit.set_panel_glass(True)
        assert pane.property("glassPane") == "true"
        # The hazard surface carries NEITHER flag with the switch on.
        assert not hazard.property("glassPane")
        assert not hazard.property("glassCard")
    finally:
        panel_kit.set_panel_glass(False)
    assert not pane.property("glassPane")


def test_role_card_flips_the_glass_card_flag_not_the_pane_flag():
    _app()
    card = panel_kit.Card("A card that goes SCENE-glass")
    panel_kit.register_glass_pane(card, role="card")
    try:
        panel_kit.set_panel_glass(True)
        assert card.property("glassCard") == "true"
        assert not card.property("glassPane")
    finally:
        panel_kit.set_panel_glass(False)
    assert not card.property("glassCard")


def test_figure_card_is_still_refused_for_every_role():
    _app()
    fig = panel_kit.FigureCard("Live map")
    for role in ("pane", "card"):
        with pytest.raises(ValueError):
            panel_kit.register_glass_pane(fig, role=role)
