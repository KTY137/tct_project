"""U2.1 — LANTERN kit conformance suite (kit_spec_v1.md §2, §4.1, §5.3–5.4).

Offscreen tests for the kit's material core: ``gui/qml/kit/Surface.qml``
(rung ladder §2.2, tier resolution §2.3, state table §2.6, hazard
construction-throw §2.1), ``gui/qml/kit/LivingGround.qml`` (band law §5.3,
run-active clamp ruling 1, calm policy §5.4/u2_hero_plan §4 R4),
``gui/qml/kit/FocusRing.qml`` (outside-offset ring + halo §4.1, ruling 3/4),
the dead-zone registry (§4.4, ruling 5), the pre-rendered asset drift-guard
(scripts/gen_shadow_assets.py's manifest vs the live gui/style.py tokens)
and the ``GLASS_LIVE_PANE_BUDGET = 1`` MultiEffect lint.

Offscreen tier note (u2_hero_plan.md §3.3): offscreen runs cap at TOKEN
(gui/glass_env.py SAFE_FLOOR), so these tests assert FLAT/TOKEN invariants +
geometry/band/budget laws structurally; the SCENE-tier *resolution*
(one-rung-up-at-alpha) is asserted on the resolved token/alpha properties
with the frost machinery deliberately inactive (no ground / frostEnabled
false — the SCENE-gated Loaders never construct QtQuick.Effects/Shapes
offscreen). SCENE pixels are verified in the windowed Kaya review.

Same bare-QQmlEngine harness as tests/test_qml_scan_status.py (leaf view
components; no window chrome needed). Living-glass settings are monkeypatched
at the gui.app_settings accessor level so the user's persisted QSettings can
never leak into an assertion.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtWidgets import QApplication

_QML_DIR = Path(__file__).resolve().parent.parent / "gui" / "qml"
_KIT_DIR = _QML_DIR / "kit"
_ASSETS_DIR = _KIT_DIR / "assets"

# Surface.Rung declaration order (Surface.qml — frozen kit API).
SHELF, CARD, TILE, WELL, ISLAND, HAZARD = 0, 1, 2, 3, 4, 5
# gui/glass_env.py::GlassTier ints, mirrored by KitEnv.
FLAT, TOKEN, WINDOW, SCENE = 0, 1, 2, 3

# kit_spec_v1.md §2.4: one live MultiEffect pane, transient only — and in this
# codebase exactly ONE instantiation exists at all: the frost bake's source
# blur (kit/FrostBake.qml).
GLASS_LIVE_PANE_BUDGET = 1


# --------------------------------------------------------------------------- #
# Harness                                                                      #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(seconds: float = 0.05) -> None:
    app = _app()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.005)


def _engine() -> QQmlEngine:
    """Fresh engine with ``import Tct`` resolvable (imports gui.qml_theme,
    which registers the Theme singleton process-wide) — the exact setup
    tests/test_qml_scan_status.py::_engine uses."""
    _app()
    from gui import qml_shell, qml_theme
    qml_shell._ensure_qml_dll_path()
    qml_theme.set_theme_mode("light")
    return QQmlEngine()


def _load(engine: QQmlEngine, path: Path, props: dict | None = None):
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    _pump(0.02)
    if props:
        obj = component.createWithInitialProperties(props)
    else:
        obj = component.create()
    return component, obj


def _errs(component: QQmlComponent) -> list[str]:
    return [e.toString() for e in component.errors()]


def _env(obj) -> QObject:
    """The engine's KitEnv singleton, via the kit's own ``kitEnv`` exposure."""
    env = obj.property("kitEnv")
    assert env is not None
    return env


def _qml(obj, code: str):
    """Evaluate a JS expression in *obj*'s creation context (resolves the
    kit's KitEnv/KitAssets singletons and Qt.* helpers). PySide6's
    ``QQmlExpression.evaluate()`` returns ``(value, valueIsUndefined)``."""
    ctx = QQmlEngine.contextForObject(obj)
    expr = QQmlExpression(ctx, obj, code)
    result = expr.evaluate()
    assert not expr.hasError(), expr.error().toString()
    if isinstance(result, tuple):
        return result[0]
    return result


def _patch_glass(monkeypatch, mode: str = "subtle", speed: float = 1.0,
                 motion: bool = True) -> dict:
    """Pin the living-glass settings at the accessor level (hermetic vs the
    user's real QSettings store). Mutate the returned dict + _repush_theme()
    to change values mid-test."""
    from gui import app_settings
    state = {"mode": mode, "speed": speed, "motion": motion}
    monkeypatch.setattr(app_settings, "living_glass_mode",
                        lambda store=None: state["mode"])
    monkeypatch.setattr(app_settings, "living_glass_speed",
                        lambda store=None: state["speed"])
    monkeypatch.setattr(app_settings, "motion_enabled",
                        lambda store=None: state["motion"])
    return state


def _repush_theme() -> None:
    """Force every live Theme binding to re-evaluate (the bridge's single
    ``changed`` notify — same mechanism a theme toggle uses)."""
    from gui import qml_theme
    qml_theme.set_theme_mode(qml_theme.current_mode())


def _color_name(obj, prop: str) -> str:
    return obj.property(prop).name().lower()


def _strip_qml_comments(source: str) -> str:
    """Blank // and /* */ comment text (string literals survive — a hex
    colour inside a string IS the violation the guards look for)."""
    out: list[str] = []
    i, n = 0, len(source)
    in_line = in_block = False
    quote: str | None = None
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if quote is not None:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------- #
# Surface — construction + rung resolution per tier (§2.2 / §2.3)              #
# --------------------------------------------------------------------------- #
def test_surface_loads_with_zero_errors():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml")
    try:
        assert _errs(component) == []
        assert obj is not None
        assert obj.property("objectName") == "kitSurface"
        assert obj.property("rung") == CARD          # default rung
        assert _env(obj).property("tier") == TOKEN   # safe floor default
    finally:
        if obj is not None:
            obj.deleteLater()
        _pump()


def test_rung_resolution_flat_token_window():
    """FLAT/TOKEN (and WINDOW, which the kit paints identically) render the
    OPAQUE rung token — §2.2 column 1, §2.3 tier invariance."""
    from gui.style import PLOT_BG, palette

    p = palette("light")
    expected = {
        SHELF: p["shelf"], CARD: p["card"], TILE: p["raised"],
        WELL: p["well"], ISLAND: PLOT_BG, HAZARD: p["panel"],
    }
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml")
    try:
        assert _errs(component) == []
        env = _env(obj)
        for tier in (FLAT, TOKEN, WINDOW):
            env.setProperty("tier", tier)
            for rung, hexval in expected.items():
                obj.setProperty("rung", rung)
                _pump(0.01)
                assert _color_name(obj, "resolvedFillColor") == hexval.lower(), (
                    f"tier={tier} rung={rung}")
                assert obj.property("resolvedFillAlpha") == 1.0
                assert obj.property("effectiveGlass") is False
    finally:
        obj.deleteLater()
        _pump()


def test_rung_resolution_scene_paints_one_rung_up_at_rung_alpha():
    """SCENE: Shelf paints `card` @ glassPaneAlpha, Card paints `raised` @
    glassCardAlpha; tile/well/island/hazard stay their own opaque token —
    §2.2 column 2 / §2.3 "paint one rung up, at your rung's alpha"."""
    from gui.style import (GLASS_CARD_ALPHA_LIGHT, PLOT_BG,
                           get_panel_glass_alpha, palette)

    p = palette("light")
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml")
    try:
        assert _errs(component) == []
        env = _env(obj)
        env.setProperty("tier", SCENE)

        obj.setProperty("rung", SHELF)
        _pump(0.01)
        assert obj.property("effectiveGlass") is True
        assert _color_name(obj, "resolvedFillColor") == p["card"].lower()
        assert abs(obj.property("resolvedFillAlpha")
                   - get_panel_glass_alpha()) < 1e-9

        obj.setProperty("rung", CARD)
        _pump(0.01)
        assert obj.property("effectiveGlass") is True
        assert _color_name(obj, "resolvedFillColor") == p["raised"].lower()
        assert abs(obj.property("resolvedFillAlpha")
                   - GLASS_CARD_ALPHA_LIGHT) < 1e-9

        for rung, hexval in ((TILE, p["raised"]), (WELL, p["well"]),
                             (ISLAND, PLOT_BG), (HAZARD, p["panel"])):
            obj.setProperty("rung", rung)
            _pump(0.01)
            assert obj.property("effectiveGlass") is False
            assert _color_name(obj, "resolvedFillColor") == hexval.lower()
            assert obj.property("resolvedFillAlpha") == 1.0

        # No ground registered -> the frost sampler Loader must stay inert
        # (this is what keeps QtQuick.Shapes/Effects out of offscreen runs).
        obj.setProperty("rung", CARD)
        _pump(0.01)
        loader = obj.findChild(QObject, "surfaceFrostLoader")
        assert loader is not None
        assert loader.property("active") is False
    finally:
        obj.deleteLater()
        _pump()


def test_surface_theme_switch_smoke():
    """Headless construction + theme-switch smoke (standing panel rule):
    both themes must resolve from tokens, zero inline hex."""
    from gui import qml_theme
    from gui.style import palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml")
    try:
        assert _errs(component) == []
        assert _color_name(obj, "resolvedFillColor") == palette("light")["card"].lower()
        qml_theme.set_theme_mode("dark")
        _pump(0.02)
        assert _color_name(obj, "resolvedFillColor") == palette("dark")["card"].lower()
        assert _color_name(obj, "resolvedBorderColor") == \
            palette("dark")["hairline_strong"].lower()
        qml_theme.set_theme_mode("light")
        _pump(0.02)
        assert _color_name(obj, "resolvedFillColor") == palette("light")["card"].lower()
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# Surface — the state table (§2.6)                                             #
# --------------------------------------------------------------------------- #
def test_state_table_hover_steps_shadow_and_border():
    from gui.style import palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml",
                           {"rung": TILE, "interactive": True})
    try:
        assert _errs(component) == []
        assert obj.property("materialState") == "idle"
        assert obj.property("shadowLevel") == "contact"     # tile base
        assert _color_name(obj, "resolvedBorderColor") == \
            palette("light")["hairline"].lower()

        obj.setProperty("previewHover", True)
        _pump(0.01)
        assert obj.property("materialState") == "hover"
        assert obj.property("shadowLevel") == "card"        # one step up
        # Tier-independent channel: border -> hairlineStrong (survives FLAT).
        assert _color_name(obj, "resolvedBorderColor") == \
            palette("light")["hairline_strong"].lower()

        # Card: base "card" -> hover "pane", and the 9-patch source follows.
        obj.setProperty("rung", CARD)
        _pump(0.01)
        assert obj.property("shadowLevel") == "pane"
        shadow = obj.findChild(QObject, "surfaceShadow")
        assert shadow.property("visible") is True
        assert "shadow_pane_light.png" in shadow.property("source").toString()
    finally:
        obj.deleteLater()
        _pump()


def test_state_table_pressed_fill_token_and_shadow_step_down():
    from gui.style import palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml",
                           {"rung": CARD, "interactive": True})
    try:
        assert _errs(component) == []
        obj.setProperty("pressed", True)
        _pump(0.01)
        assert obj.property("materialState") == "pressed"
        # Tier-independent channel: the fill TOKEN changes.
        assert _color_name(obj, "resolvedFillColor") == \
            palette("light")["pressed"].lower()
        assert obj.property("resolvedFillAlpha") == 1.0
        assert obj.property("shadowLevel") == "contact"     # one step down
    finally:
        obj.deleteLater()
        _pump()


def test_state_table_disabled_opaque_disabled_bg_and_no_glass():
    from gui.style import palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml",
                           {"rung": CARD, "interactive": True})
    try:
        assert _errs(component) == []
        _env(obj).setProperty("tier", SCENE)
        obj.setProperty("enabled", False)
        _pump(0.01)
        assert obj.property("materialState") == "disabled"
        # §2.6 disabled: frost sampling OFF, pane goes opaque disabled_bg.
        assert obj.property("effectiveGlass") is False
        assert _color_name(obj, "resolvedFillColor") == \
            palette("light")["disabled_bg"].lower()
        assert obj.property("resolvedFillAlpha") == 1.0
        assert obj.property("shadowLevel") == "none"
    finally:
        obj.deleteLater()
        _pump()


def test_no_shadow_on_well_island_hazard_rungs():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml",
                           {"interactive": True, "previewHover": True})
    try:
        assert _errs(component) == []
        for rung in (WELL, ISLAND, HAZARD):
            obj.setProperty("rung", rung)
            _pump(0.01)
            assert obj.property("shadowLevel") == "none", f"rung={rung}"
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# Surface — hazard: dead material, construction throw (§2.1, §2.6, ruling 4)   #
# --------------------------------------------------------------------------- #
def test_hazard_material_is_dead_even_at_scene():
    from gui.style import palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml",
                           {"rung": HAZARD, "interactive": True})
    try:
        assert _errs(component) == []
        _env(obj).setProperty("tier", SCENE)
        obj.setProperty("previewHover", True)
        obj.setProperty("pressed", True)
        _pump(0.01)
        # No frost, no lift, no press response — opaque panel, always.
        assert obj.property("effectiveGlass") is False
        assert obj.property("hovered") is False
        assert obj.property("materialState") == "idle"
        assert obj.property("shadowLevel") == "none"
        assert _color_name(obj, "resolvedFillColor") == \
            palette("light")["panel"].lower()
        assert obj.property("resolvedFillAlpha") == 1.0
        # Redundant hazard channel present (stripe); halo dead, ring wired.
        stripe = obj.findChild(QObject, "surfaceHazardStripe")
        assert stripe.property("visible") is True
        ring = obj.findChild(QObject, "kitFocusRing")
        assert ring is not None                    # ruling 4: ring ALWAYS
        assert ring.property("halo") is False      # ruling 4: halo NEVER
    finally:
        obj.deleteLater()
        _pump()


def test_hazard_construction_throw_on_glass_flag():
    """§2.1: Surface THROWS at construction on `rung: Hazard` + any glass/
    shadow/halo-response flag — the QML twin of register_glass_pane's
    refusal. The thrown Error surfaces through the engine's warning channel;
    the material resolution independently clamps safe."""
    engine = _engine()
    warnings: list[str] = []
    engine.warnings.connect(
        lambda errs: warnings.extend(e.toString() for e in errs))
    engine.setOutputWarningsToStandardError(False)

    for flag in ("glassOverride", "shadowOverride", "haloOverride"):
        warnings.clear()
        component, obj = _load(engine, _KIT_DIR / "Surface.qml",
                               {"rung": HAZARD, flag: True})
        try:
            assert _errs(component) == []
            _pump(0.05)
            assert any("Hazard rung refuses" in w for w in warnings), (
                f"no construction throw for {flag}: {warnings}")
            # Fail-safe direction is DOWN: still opaque, still no glass.
            _env(obj).setProperty("tier", SCENE)
            _pump(0.01)
            assert obj.property("effectiveGlass") is False
            assert obj.property("resolvedFillAlpha") == 1.0
        finally:
            if obj is not None:
                obj.deleteLater()
            _pump()


# --------------------------------------------------------------------------- #
# FocusRing — outside-offset ring + halo (§4.1, rulings 3/4)                   #
# --------------------------------------------------------------------------- #
def test_focus_ring_outside_offset_geometry():
    from gui.style import FOCUS_HALO_ALPHA_LIGHT, FOCUS_RING_OFFSET_PX, palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "FocusRing.qml",
                           {"active": True, "targetRadius": 12})
    try:
        assert _errs(component) == []
        obj.setProperty("width", 100)
        obj.setProperty("height", 40)
        _pump(0.03)
        assert obj.property("visible") is True
        ring_w = obj.property("ringWidth")
        assert ring_w == 2                                   # §4.1 spec-fixed
        outset = FOCUS_RING_OFFSET_PX + ring_w

        rect = obj.findChild(QObject, "focusRingRect")
        # Drawn ENTIRELY OUTSIDE the fill boundary: outer edge at offset+width,
        # border drawn inward, inner edge exactly focusRingOffsetPx out.
        assert rect.property("width") == 100 + 2 * outset
        assert rect.property("height") == 40 + 2 * outset
        assert rect.property("radius") == 12 + outset        # concentric law
        # border is a grouped QQuickPen (no PySide converter) — read via QML.
        assert _qml(rect, "border.width") == ring_w
        assert _qml(rect, "border.color.toString()").lower() == \
            palette("light")["accent"].lower()
        assert rect.property("color").alpha() == 0           # ring, not fill

        # Halo: garnish BorderImage, live theme alpha, outside the ring.
        halo = obj.findChild(QObject, "focusHalo")
        assert halo.property("visible") is True
        assert abs(halo.property("opacity") - FOCUS_HALO_ALPHA_LIGHT) < 1e-9
        manifest = json.loads((_ASSETS_DIR / "manifest.json")
                              .read_text(encoding="utf-8"))
        halo_pad = manifest["geometry"]["halo_pad"]
        assert halo.property("width") == 100 + 2 * halo_pad
    finally:
        obj.deleteLater()
        _pump()


def test_focus_ring_halo_present_on_card_surface():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml",
                           {"rung": CARD, "interactive": True})
    try:
        assert _errs(component) == []
        ring = obj.findChild(QObject, "kitFocusRing")
        assert ring is not None
        assert ring.property("halo") is True
        # haloOverride can only turn the garnish OFF, never grant it.
        obj.setProperty("haloOverride", False)
        _pump(0.01)
        assert ring.property("halo") is False
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# LivingGround — band law (§5.3), N random phases                              #
# --------------------------------------------------------------------------- #
def test_band_law_n_random_phases_positions_move_alpha_never(monkeypatch):
    """Constitution-grade §5.3: washes move POSITION, never alpha; the summed
    tint stays <= Theme.groundTintAlphaMax for ANY frame. Drives `phase`
    (the one flow variable) through N random values and asserts both."""
    from gui.style import GROUND_TINT_ALPHA_MAX

    _patch_glass(monkeypatch, mode="subtle")
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "LivingGround.qml")
    try:
        assert _errs(component) == []
        obj.setProperty("width", 400)
        obj.setProperty("height", 300)
        _pump(0.03)

        # Frame-invariant budget, by construction (baked peaks, constant 1.0
        # item opacity): 2*washPeak + sweepPeak <= GROUND_TINT_ALPHA_MAX.
        assert obj.property("tintBudgetPeak") <= GROUND_TINT_ALPHA_MAX + 1e-9

        wash1 = obj.findChild(QObject, "groundWash1")
        wash2 = obj.findChild(QObject, "groundWash2")
        sweep = obj.findChild(QObject, "groundSweep")
        layer = obj.findChild(QObject, "groundWashLayer")
        assert layer.property("visible") is True   # TOKEN tier: static wash

        ax = obj.property("ax")
        assert ax > 0                              # subtle: half amplitude
        cx1_expected = 400 * 0.30

        rng = random.Random(20260715)
        xs: list[float] = []
        for _ in range(24):
            obj.setProperty("phase", rng.random())
            _pump(0.005)
            for item in (wash1, wash2, sweep):
                # THE BAND LAW: alpha never moves with phase.
                assert item.property("opacity") == 1.0
            x = wash1.property("x")
            xs.append(round(x, 3))
            # Position is a bounded pure function of phase (Lissajous).
            cx1 = x + wash1.property("width") / 2
            assert abs(cx1 - cx1_expected) <= ax + 0.51

        assert len(set(xs)) > 10, "washes did not move with phase"
    finally:
        obj.deleteLater()
        _pump()


def test_ground_no_semantic_tint_and_wash_pixels_respect_budget():
    """§5.3: the ground is tinted only with `accent` and neutrals — the wash
    sprites are baked from the accent token (checked against the LIVE palette
    on the actual PNG pixels), and no baked pixel exceeds the budget split."""
    from gui.style import palette

    manifest = json.loads((_ASSETS_DIR / "manifest.json")
                          .read_text(encoding="utf-8"))
    wash_peak = manifest["budget"]["wash_peak_alpha"]
    for mode in ("dark", "light"):
        img = QImage(str(_ASSETS_DIR / f"ground_wash_{mode}.png"))
        assert not img.isNull()
        accent = palette(mode)["accent"].lstrip("#")
        exp_rgb = tuple(int(accent[i:i + 2], 16) for i in (0, 2, 4))
        centre = img.pixelColor(img.width() // 2, img.height() // 2)
        for got, want in zip((centre.red(), centre.green(), centre.blue()),
                             exp_rgb):
            assert abs(got - want) <= 3, (mode, got, want)
        max_a = 0.0
        for y in range(0, img.height(), 4):
            for x in range(0, img.width(), 4):
                max_a = max(max_a, img.pixelColor(x, y).alphaF())
        assert max_a <= wash_peak + 1.5 / 255.0, (mode, max_a)


def test_reduced_motion_collapse(monkeypatch):
    """§5.2: Theme.motionEnabled == false -> the ground goes static (the flow
    animation stops, the bake cadence drops to 0 — "frost baked once")."""
    state = _patch_glass(monkeypatch, mode="subtle", motion=True)
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "LivingGround.qml",
                           {"frostEnabled": False})
    try:
        assert _errs(component) == []
        obj.setProperty("width", 400)
        obj.setProperty("height", 300)
        env = _env(obj)
        env.setProperty("tier", SCENE)
        _pump(0.02)
        assert obj.property("flowing") is True
        assert obj.property("flowRunning") is True
        assert obj.property("bakeHz") == 6          # subtle cadence

        state["motion"] = False
        _repush_theme()
        _pump(0.03)
        assert obj.property("flowing") is False
        assert obj.property("flowRunning") is False
        assert obj.property("bakeHz") == 0          # static -> 0 Hz

        state["motion"] = True
        _repush_theme()
        _pump(0.03)
        assert obj.property("flowRunning") is True
    finally:
        obj.deleteLater()
        _pump()


def test_ground_tier_posture_flat_nothing_token_static(monkeypatch):
    _patch_glass(monkeypatch, mode="subtle")
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "LivingGround.qml",
                           {"frostEnabled": False})
    try:
        assert _errs(component) == []
        layer = obj.findChild(QObject, "groundWashLayer")
        env = _env(obj)

        env.setProperty("tier", FLAT)
        _pump(0.01)
        assert layer.property("visible") is False    # FLAT: nothing
        env.setProperty("tier", TOKEN)
        _pump(0.01)
        assert layer.property("visible") is True     # TOKEN: static wash
        assert obj.property("flowRunning") is False
        assert obj.property("bakeHz") == 0
    finally:
        obj.deleteLater()
        _pump()


def test_ground_mode_off_hides_washes(monkeypatch):
    state = _patch_glass(monkeypatch, mode="subtle")
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "LivingGround.qml",
                           {"frostEnabled": False})
    try:
        assert _errs(component) == []
        layer = obj.findChild(QObject, "groundWashLayer")
        assert layer.property("visible") is True
        state["mode"] = "off"
        _repush_theme()
        _pump(0.02)
        assert layer.property("visible") is False
        assert obj.property("bakeHz") == 0
    finally:
        obj.deleteLater()
        _pump()


def test_run_active_speed_clamp_ruling_1(monkeypatch):
    """Ruling 1: whenever ANY run is active, the living-glass effective speed
    clamps to <= 1.0x app-wide; the persisted range applies in full only
    while idle."""
    state = _patch_glass(monkeypatch, mode="full", speed=2.0)
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "LivingGround.qml",
                           {"frostEnabled": False})
    try:
        assert _errs(component) == []
        env = _env(obj)
        assert abs(obj.property("effectiveSpeed") - 2.0) < 1e-9
        env.setProperty("runActive", True)
        _pump(0.01)
        assert abs(obj.property("effectiveSpeed") - 1.0) < 1e-9
        # A sub-1.0 setting is NOT raised by the clamp (min, not set).
        state["speed"] = 0.5
        _repush_theme()
        _pump(0.02)
        assert abs(obj.property("effectiveSpeed") - 0.5) < 1e-9
        env.setProperty("runActive", False)
        _pump(0.01)
        assert abs(obj.property("effectiveSpeed") - 0.5) < 1e-9
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# Calm policy — ONE switch (§5.4, u2_hero_plan §4 R4)                          #
# --------------------------------------------------------------------------- #
def test_calm_policy_panel_scoped_default_freezes_only_the_owning_sampler(monkeypatch):
    _patch_glass(monkeypatch, mode="subtle")
    engine = _engine()
    g_comp, ground = _load(engine, _KIT_DIR / "LivingGround.qml",
                           {"frostEnabled": False})
    s_comp, owner = _load(engine, _KIT_DIR / "Surface.qml",
                          {"rung": CARD, "runOwner": True})
    b_comp, bystander = _load(engine, _KIT_DIR / "Surface.qml",
                              {"rung": CARD})
    try:
        assert _errs(g_comp) == [] and _errs(s_comp) == [] and _errs(b_comp) == []
        env = _env(ground)
        assert env.property("calmPolicy") == "panel"     # ratified default
        env.setProperty("tier", SCENE)
        env.setProperty("runActive", True)
        _pump(0.02)
        # Panel-scoped: the run-owning pane freezes its own sampler...
        assert owner.property("samplerFrozen") is True
        assert bystander.property("samplerFrozen") is False
        # ...and the ROOM KEEPS FLOWING at the idle rate (<=1.0x clamp).
        assert ground.property("calmActive") is False
        assert ground.property("flowing") is True
        assert ground.property("bakeHz") == 6
        env.setProperty("runActive", False)
        _pump(0.01)
        assert owner.property("samplerFrozen") is False
    finally:
        ground.deleteLater()
        owner.deleteLater()
        bystander.deleteLater()
        _pump()


def test_calm_policy_global_fallback_same_hook_stills_the_room(monkeypatch):
    """The encoded fallback (measurement-B insurance): flipping the ONE
    policy flag to "global" makes a run still the whole ground and drop the
    bake to 0 Hz — no other code path changes."""
    _patch_glass(monkeypatch, mode="subtle")
    engine = _engine()
    g_comp, ground = _load(engine, _KIT_DIR / "LivingGround.qml",
                           {"frostEnabled": False})
    s_comp, owner = _load(engine, _KIT_DIR / "Surface.qml",
                          {"rung": CARD, "runOwner": True})
    try:
        assert _errs(g_comp) == [] and _errs(s_comp) == []
        env = _env(ground)
        env.setProperty("tier", SCENE)
        env.setProperty("calmPolicy", "global")
        env.setProperty("runActive", True)
        _pump(0.02)
        assert env.property("globalCalm") is True
        assert ground.property("calmActive") is True
        assert ground.property("flowing") is False
        assert ground.property("bakeHz") == 0            # bake -> 0 Hz
        assert owner.property("samplerFrozen") is True   # subsumed, harmless
        # Idle again: the room resumes.
        env.setProperty("runActive", False)
        _pump(0.02)
        assert ground.property("calmActive") is False
        assert ground.property("bakeHz") == 6
    finally:
        ground.deleteLater()
        owner.deleteLater()
        _pump()


def test_detached_whole_calm_hook_eases_amplitude():
    """§5.4: a detached run-owning panel is its own ground and calms WHOLE —
    LivingGround.calm eases wash amplitude toward 0 (the 1200 ms law)."""
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "LivingGround.qml",
                           {"frostEnabled": False})
    try:
        assert _errs(component) == []
        assert obj.property("amplitudeScale") == 1.0
        obj.setProperty("calm", True)
        _pump(0.05)
        assert obj.property("calmActive") is True
        # Behavior-eased toward 0 (don't wait the full 1200 ms — direction
        # plus target suffice offscreen).
        assert obj.property("amplitudeScale") < 1.0
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# Dead-zone registry (§4.4, ruling 5)                                          #
# --------------------------------------------------------------------------- #
def test_island_surface_auto_registers_as_dead_zone():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml",
                           {"rung": ISLAND, "objectName": "mapIsland"})
    try:
        assert _errs(component) == []
        assert _qml(obj, "KitEnv.deadZones.length") == 1
        assert _qml(obj, "KitEnv.deadZones[0].name") == "mapIsland"
    finally:
        obj.deleteLater()
        _pump()


def test_dead_zone_violation_geometry():
    """The geometric assertion: any translucent extent within spaceMd (12 px)
    of a registered zone — by any mechanism — is a violation; exactly-12-px
    clearance is legal."""
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Surface.qml", {"rung": CARD})
    try:
        assert _errs(component) == []
        _qml(obj, "KitEnv.registerDeadZoneRect('plot', Qt.rect(100, 100, 200, 150))")
        assert _qml(obj, "KitEnv.deadZones.length") == 1
        # 10 px gap on both axes -> violation (per mechanism, named).
        assert _qml(obj, "KitEnv.violations(Qt.rect(0, 0, 90, 90), 'shadow').length") == 1
        assert _qml(obj, "KitEnv.violations(Qt.rect(0, 0, 90, 90), 'halo')[0].mechanism") == "halo"
        assert _qml(obj, "KitEnv.violations(Qt.rect(0, 0, 90, 90), 'sample')[0].zone") == "plot"
        # Overlap -> violation.
        assert _qml(obj, "KitEnv.violations(Qt.rect(150, 150, 10, 10), 'sample').length") == 1
        # Exactly spaceMd apart -> legal (>= clearance).
        assert _qml(obj, "KitEnv.violations(Qt.rect(0, 0, 88, 88), 'shadow').length") == 0
        # Comfortably clear -> legal.
        assert _qml(obj, "KitEnv.violations(Qt.rect(0, 0, 80, 80), 'halo').length") == 0
        # assertClear returns the same list (the runtime debug hook).
        assert _qml(obj, "KitEnv.assertClear(Qt.rect(0, 0, 90, 90), 'shadow', 'testPane').length") == 1
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# GLASS_LIVE_PANE_BUDGET lint — one MultiEffect, in the frost bake, only       #
# --------------------------------------------------------------------------- #
def test_glass_live_pane_budget_single_multieffect_in_frost_bake():
    hits: dict[str, int] = {}
    for path in sorted(_QML_DIR.rglob("*.qml")):
        stripped = _strip_qml_comments(path.read_text(encoding="utf-8"))
        n = len(re.findall(r"\bMultiEffect\s*\{", stripped))
        if n:
            hits[path.relative_to(_QML_DIR).as_posix()] = n
    assert sum(hits.values()) <= GLASS_LIVE_PANE_BUDGET, (
        f"MultiEffect budget ({GLASS_LIVE_PANE_BUDGET}) exceeded: {hits} — "
        "the frost bake owns the ONE blur (kit_spec_v1.md §2.4); everything "
        "else samples it")
    assert set(hits) == {"kit/FrostBake.qml"}, hits


# --------------------------------------------------------------------------- #
# Asset drift-guard — the bake must match the LIVE gui/style.py tokens         #
# --------------------------------------------------------------------------- #
def test_shadow_assets_exist():
    expected = [f"shadow_{lvl}_{mode}.png"
                for lvl in ("contact", "card", "pane", "float")
                for mode in ("dark", "light")]
    expected += ["focus_halo_dark.png", "focus_halo_light.png",
                 "ground_wash_dark.png", "ground_wash_light.png",
                 "manifest.json"]
    for name in expected:
        assert (_ASSETS_DIR / name).exists(), name


def test_asset_manifest_matches_live_style_tokens():
    """If gui/style.py's shadow/accent/budget/focus tokens move, the baked
    PNGs are stale — this fails loudly until gen_shadow_assets.py is re-run."""
    from gui.style import (FOCUS_HALO_ALPHA_DARK, FOCUS_HALO_ALPHA_LIGHT,
                           FOCUS_RING_OFFSET_PX, GROUND_TINT_ALPHA_MAX,
                           SHADOW_A_DARK, SHADOW_A_LIGHT, SHADOW_B_DARK,
                           SHADOW_B_LIGHT, SHADOW_C_DARK, SHADOW_C_LIGHT,
                           SHADOW_D_DARK, SHADOW_D_LIGHT, palette)

    manifest = json.loads((_ASSETS_DIR / "manifest.json")
                          .read_text(encoding="utf-8"))
    live = {
        "dark": {"shadow_ink": palette("dark")["shadow_ink"],
                 "accent": palette("dark")["accent"],
                 "shadow_a": SHADOW_A_DARK, "shadow_b": SHADOW_B_DARK,
                 "shadow_c": SHADOW_C_DARK, "shadow_d": SHADOW_D_DARK,
                 "focus_halo_alpha": FOCUS_HALO_ALPHA_DARK},
        "light": {"shadow_ink": palette("light")["shadow_ink"],
                  "accent": palette("light")["accent"],
                  "shadow_a": SHADOW_A_LIGHT, "shadow_b": SHADOW_B_LIGHT,
                  "shadow_c": SHADOW_C_LIGHT, "shadow_d": SHADOW_D_LIGHT,
                  "focus_halo_alpha": FOCUS_HALO_ALPHA_LIGHT},
    }
    for mode, tokens in live.items():
        for key, want in tokens.items():
            got = manifest["tokens"][mode][key]
            if isinstance(want, str):
                assert got.lower() == want.lower(), (mode, key)
            else:
                assert abs(got - want) < 1e-9, (mode, key)

    budget = manifest["budget"]
    assert abs(budget["ground_tint_alpha_max"] - GROUND_TINT_ALPHA_MAX) < 1e-9
    assert (2 * budget["wash_peak_alpha"] + budget["sweep_peak_alpha"]
            <= GROUND_TINT_ALPHA_MAX + 1e-9)
    assert manifest["geometry"]["focus_ring_offset_px"] == FOCUS_RING_OFFSET_PX
    assert manifest["geometry"]["focus_ring_width_px"] == 2   # §4.1
    assert manifest["geometry"]["focus_halo_px"] == 8         # §4.1


def test_generated_kit_assets_qml_matches_manifest():
    """KitAssets.qml is generated alongside the PNGs — its 9-patch geometry
    and budget split must be the manifest's, byte for byte in meaning."""
    manifest = json.loads((_ASSETS_DIR / "manifest.json")
                          .read_text(encoding="utf-8"))
    text = (_KIT_DIR / "KitAssets.qml").read_text(encoding="utf-8")

    def _num(pattern: str) -> float:
        m = re.search(pattern, text)
        assert m, pattern
        return float(m.group(1))

    assert abs(_num(r"washPeakAlpha:\s*([\d.]+)")
               - manifest["budget"]["wash_peak_alpha"]) < 1e-9
    assert abs(_num(r"sweepPeakAlpha:\s*([\d.]+)")
               - manifest["budget"]["sweep_peak_alpha"]) < 1e-9
    assert _num(r"haloPad:\s*(\d+)") == manifest["geometry"]["halo_pad"]
    assert _num(r"haloBorder:\s*(\d+)") == manifest["geometry"]["halo_border"]
    for lvl, pad in manifest["geometry"]["shadow_pad"].items():
        assert re.search(rf'"{lvl}":\s*{pad}\b', text), (lvl, pad)
