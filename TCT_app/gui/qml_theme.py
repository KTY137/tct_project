"""QML ``Theme`` singleton — the QML-side analogue of ``gui.style.apply_theme``.

The QML-hybrid frontend (``docs/research/qml_hybrid_architecture.md`` §3) needs
the *same* palette/type/spacing tokens that ``gui/style.py`` already owns, but
reachable from ``.qml`` as bound properties. Rather than code-generate a
``Tokens.qml`` (a second file to keep in sync — the drift the §3 assessment
explicitly rejects), this module exposes ``gui/style.py``'s ``LIGHT``/``DARK``
dicts through **one Qt QObject** registered as a QML singleton. Every colour is
a NOTIFY-able ``Property`` bound to the active palette; on a theme toggle
``set_theme_mode()`` swaps the active dict and re-emits ``changed`` on every
live singleton, so QML property bindings re-evaluate automatically (live theme
switch, zero copies — the "bind, don't poll" rule). ``gui/style.py`` stays the
single source of truth for the token *values*.

Registration uses the PySide6 declarative ``@QmlElement``/``@QmlSingleton``
decorators (tooling-visible, unlike ``setContextProperty``). We are on Qt 6.11,
so ``QQmlEngine.setExternalSingletonInstance`` (6.12) is deliberately NOT used;
the engine constructs one instance per engine and we keep a weak registry of
them so a theme toggle can notify each without leaking a reference that would
outlive the engine.

Sizes (font/spacing/radius) are exposed as ``constant`` properties: they do not
change on a theme toggle (only colours do), matching ``gui/style.py`` where the
scales are shared across both themes.

QML usage::

    import Tct
    Rectangle { color: Theme.material; radius: Theme.radiusMd }
"""
from __future__ import annotations

import logging
import re
import weakref

from PySide6.QtCore import Property, QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtQml import QmlElement, QmlSingleton

from gui import app_settings
from gui.style import (
    BLUR_CARD_PX, BLUR_OVERLAY_PX, BLUR_PANE_PX, FOCUS_HALO_ALPHA_DARK,
    FOCUS_HALO_ALPHA_LIGHT, FOCUS_RING_OFFSET_PX, FONT, FONT_BODY_PX,
    FONT_METRIC_LABEL_PX, FONT_PANEL_TITLE_PX, FONT_RAIL_PX, FONT_UNIT_PX,
    FONT_VALUE_COMPACT_PX, FONT_VALUE_PX, FROST_REBAKE_HZ_FULL,
    FROST_REBAKE_HZ_SUBTLE, GLASS_CARD_ALPHA_DARK, GLASS_CARD_ALPHA_LIGHT,
    GROUND_FLOW_PERIOD_S, GROUND_TINT_ALPHA_MAX, MONO_FAMILIES,
    MOTION_SPRING_UI, MOTION_TAP_MS, MOTION_UNFOLD_MS, RADIUS,
    SHADOW_A_DARK, SHADOW_A_LIGHT, SHADOW_B_DARK, SHADOW_B_LIGHT,
    SHADOW_C_DARK, SHADOW_C_LIGHT, SHADOW_D_DARK, SHADOW_D_LIGHT, SPACE,
    PLOT_BG, PLOT_FG, PLOT_GRID, PLOT_OVERLAY, TRACKING_METRIC_LABEL_PX,
    TRANSITION_MS, WEIGHT_BODY, WEIGHT_METRIC_LABEL, WEIGHT_PANEL_TITLE,
    WEIGHT_RAIL, WEIGHT_UNIT, WEIGHT_VALUE, get_panel_glass_alpha, palette,
)

# QColor's string constructor cannot parse CSS functional ``rgba()`` notation
# (only named colours / "#rrggbb[aa]"), which is how gui/style.py stores
# "specular" (``"rgba(255, 255, 255, 0.92)"``). Rather than hand-copy the
# alpha into a second literal here (the exact drift that went stale — 0.85/
# 0.045 vs style.py's 0.92/0.14 — before this fix), this regex pulls the
# alpha out of style.py's own string in one place; see the ``specular``
# property below for why it is parsed live on every access instead of cached.
_RGBA_ALPHA_RE = re.compile(
    r"rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)")


_LOG = logging.getLogger(__name__)

# Only ever reached if gui/style.py's specular token becomes UNPARSEABLE (a
# malformed dev-tool override, say) — normally the alpha is parsed live. A
# single conservative constant (not a per-theme table) so this fallback can
# NEVER silently drift out of step the way the old hardcoded 0.85/0.045 table
# did; on the fallback path the "correct" value is undefined anyway.
_SPECULAR_FALLBACK_ALPHA = 0.1
_specular_parse_warned = False


def _alpha_from_rgba(rgba: str) -> float:
    """Extract the alpha channel from a CSS ``rgba(r, g, b, a)`` string.

    Raises ``ValueError`` on a non-rgba() token — the strict low-level parser
    (pinned by the drift-guard test). Callers that must not raise from inside a
    QML ``@Property`` getter go through :func:`_specular_alpha`."""
    match = _RGBA_ALPHA_RE.match(str(rgba).strip())
    if not match:
        raise ValueError(f"gui.qml_theme: not a parseable rgba() string: {rgba!r}")
    return float(match.group(1))


def _specular_alpha(mode: str) -> float:
    """Specular highlight alpha for *mode*, parsed live from ``gui.style``.

    The safe wrapper the ``Theme.specular`` @Property getter uses: raising from
    inside a QML property getter is a diagnosis nightmare (it surfaces as an
    opaque binding error with no site), so a parse miss logs a WARNING once and
    falls back to :data:`_SPECULAR_FALLBACK_ALPHA` instead. The drift-guard
    tests still exercise :func:`_alpha_from_rgba` directly, so correctness of
    the normal path stays pinned."""
    global _specular_parse_warned
    try:
        return _alpha_from_rgba(palette(mode)["specular"])
    except (ValueError, KeyError, TypeError):
        if not _specular_parse_warned:
            _specular_parse_warned = True
            _LOG.warning(
                "gui.qml_theme: specular token for mode %r is not a parseable "
                "rgba() string (%r); falling back to alpha %.3f.",
                mode, palette(mode).get("specular"), _SPECULAR_FALLBACK_ALPHA)
        return _SPECULAR_FALLBACK_ALPHA

# PySide6 declarative registration: the QML side does ``import Tct``.
QML_IMPORT_NAME = "Tct"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0

# QML colour-property name -> gui.style palette-dict key. Kept as a module
# constant (not just inlined in the properties) so tests can iterate it to prove
# every Theme colour matches style.py for both themes without hand-listing them.
TOKEN_MAP: dict[str, str] = {
    "canvas": "canvas",
    "material": "material",
    "panel": "panel",
    "panel2": "panel_2",
    "raised": "raised",     # cockpit v5 (docs/design/cockpit_design_system.md
    "sunk": "sunk",         # §2) surface-ladder additions — same hex as the
    "well": "well",         # matching gui/style.py LIGHT/DARK dict key.
    "card": "card",         # round-03 glass-kit elevation rungs (kit.md §2) —
    "shelf": "shelf",       # derived in gui/style.py, never hand-picked here.
    "field": "field",
    "chrome": "chrome",     # round-2 material: frosted rail strip (solid
    "strip": "strip",       # color-mix fallback) + recessed status-strip wash.
    "hairline": "hairline",
    "hairlineStrong": "hairline_strong",
    "border": "border",
    "text": "text",
    "muted": "muted",
    "faint": "faint",
    "accent": "accent",
    "accentStrong": "accent_strong",
    "tint": "tint",
    "good": "good",
    "warn": "warn",
    "crit": "crit",
    "sim": "sim",
    "danger": "danger",     # cockpit v5 canonical semantic names — same
    "armed": "armed",       # value as crit/warn above, see gui/style.py.
    "onAccent": "on_accent",
    # LANTERN kit-bridge (kit_spec_v1.md §6 + Appendix A.1/A.4, U2-entry
    # Theme-bridge beat, docs/CODEX_QUEUE.md §C13) — colour exposures that
    # resolve 1:1 from an EXISTING gui/style.py palette-dict key (no new
    # style.py constant needed; only the bridge entry was missing).
    "dangerFill": "danger_fill",
    "onDanger": "on_danger",
    "onArmed": "on_armed",
    "error": "error",
    "chip": "chip",
    "edge": "edge",
    "edgeShade": "edge_shade",
    "pressed": "pressed",
    "disabledBg": "disabled_bg",
    "shadowInk": "shadow_ink",
}

# Current theme mode, shared by every live Theme singleton (one per QML engine).
_MODE = "light"
# Weak refs to constructed Theme instances so set_theme_mode() can re-emit
# ``changed`` on each without keeping a strong ref that would outlive its engine.
_INSTANCES: "weakref.WeakSet[Theme]" = weakref.WeakSet()


def current_mode() -> str:
    """Return the active QML theme mode ('light' | 'dark')."""
    return _MODE


def set_theme_mode(mode: str) -> str:
    """Swap the active palette and notify every live ``Theme`` singleton.

    Called from ``tct_gui``'s theme path (menu toggle or the QML rail's toggle
    button) so the QML chrome repaints in lockstep with the QSS ``apply_theme``.
    Returns the normalised mode.
    """
    global _MODE
    _MODE = "dark" if str(mode).lower() == "dark" else "light"
    for inst in list(_INSTANCES):
        try:
            inst._emit_changed()
        except RuntimeError:
            # Underlying C++ QObject already deleted with its engine — the weak
            # ref will drop on its own; nothing to do.
            pass
    return _MODE


@QmlElement
@QmlSingleton
class Theme(QObject):
    """Palette/type/spacing tokens as QML-bindable properties (see module doc)."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        _INSTANCES.add(self)

    # Called by set_theme_mode(); a method (not a direct .emit) so the weak-ref
    # loop has a stable attribute to invoke and to localise the emit.
    def _emit_changed(self) -> None:
        self.changed.emit()

    def _c(self, key: str) -> QColor:
        return QColor(palette(_MODE)[key])

    # -- theme flag ------------------------------------------------------ #
    @Property(bool, notify=changed)
    def dark(self) -> bool:  # noqa: D401 - QML property
        return _MODE == "dark"

    # -- colours (per-theme, NOTIFY on toggle) --------------------------- #
    @Property(QColor, notify=changed)
    def canvas(self) -> QColor: return self._c("canvas")

    @Property(QColor, notify=changed)
    def material(self) -> QColor: return self._c("material")

    @Property(QColor, notify=changed)
    def panel(self) -> QColor: return self._c("panel")

    @Property(QColor, notify=changed)
    def panel2(self) -> QColor: return self._c("panel_2")

    # -- cockpit v5 surface ladder (docs/design/cockpit_design_system.md §2) #
    @Property(QColor, notify=changed)
    def raised(self) -> QColor: return self._c("raised")

    @Property(QColor, notify=changed)
    def sunk(self) -> QColor: return self._c("sunk")

    @Property(QColor, notify=changed)
    def well(self) -> QColor: return self._c("well")

    # -- round-03 glass-kit elevation rungs (kit.md §2; derived in style.py) #
    @Property(QColor, notify=changed)
    def card(self) -> QColor: return self._c("card")

    @Property(QColor, notify=changed)
    def shelf(self) -> QColor: return self._c("shelf")

    @Property(QColor, notify=changed)
    def field(self) -> QColor: return self._c("field")

    # -- round-2 material tokens (see gui/style.py's LIGHT/DARK comments) - #
    @Property(QColor, notify=changed)
    def chrome(self) -> QColor: return self._c("chrome")

    @Property(QColor, notify=changed)
    def strip(self) -> QColor: return self._c("strip")

    @Property(QColor, notify=changed)
    def hairline(self) -> QColor: return self._c("hairline")

    @Property(QColor, notify=changed)
    def hairlineStrong(self) -> QColor: return self._c("hairline_strong")

    @Property(QColor, notify=changed)
    def border(self) -> QColor: return self._c("border")

    @Property(QColor, notify=changed)
    def text(self) -> QColor: return self._c("text")

    @Property(QColor, notify=changed)
    def muted(self) -> QColor: return self._c("muted")

    @Property(QColor, notify=changed)
    def faint(self) -> QColor: return self._c("faint")

    @Property(QColor, notify=changed)
    def accent(self) -> QColor: return self._c("accent")

    @Property(QColor, notify=changed)
    def accentStrong(self) -> QColor: return self._c("accent_strong")

    @Property(QColor, notify=changed)
    def tint(self) -> QColor: return self._c("tint")

    @Property(QColor, notify=changed)
    def good(self) -> QColor: return self._c("good")

    @Property(QColor, notify=changed)
    def warn(self) -> QColor: return self._c("warn")

    @Property(QColor, notify=changed)
    def crit(self) -> QColor: return self._c("crit")

    @Property(QColor, notify=changed)
    def sim(self) -> QColor: return self._c("sim")

    # -- cockpit v5 canonical semantic names (same value as crit/warn) --- #
    @Property(QColor, notify=changed)
    def danger(self) -> QColor: return self._c("danger")

    @Property(QColor, notify=changed)
    def armed(self) -> QColor: return self._c("armed")

    @Property(QColor, notify=changed)
    def onAccent(self) -> QColor: return self._c("on_accent")

    # -- LANTERN kit-bridge colours (kit_spec_v1.md §6 + Appendix A.1/A.4;
    #    U2-entry Theme-bridge beat, docs/CODEX_QUEUE.md §C13) — 1:1 resolves
    #    from an existing gui/style.py palette-dict key via TOKEN_MAP above. #
    @Property(QColor, notify=changed)
    def dangerFill(self) -> QColor: return self._c("danger_fill")

    @Property(QColor, notify=changed)
    def onDanger(self) -> QColor: return self._c("on_danger")

    @Property(QColor, notify=changed)
    def onArmed(self) -> QColor: return self._c("on_armed")

    @Property(QColor, notify=changed)
    def error(self) -> QColor: return self._c("error")

    @Property(QColor, notify=changed)
    def chip(self) -> QColor: return self._c("chip")

    @Property(QColor, notify=changed)
    def edge(self) -> QColor: return self._c("edge")

    @Property(QColor, notify=changed)
    def edgeShade(self) -> QColor: return self._c("edge_shade")

    @Property(QColor, notify=changed)
    def pressed(self) -> QColor: return self._c("pressed")

    @Property(QColor, notify=changed)
    def disabledBg(self) -> QColor: return self._c("disabled_bg")

    # Shadow-ladder ink (kit_spec_v1.md §2.5/A.4) — dark #000000 / light =
    # the theme's own text hue; see LIGHT["shadow_ink"]/DARK["shadow_ink"]
    # in gui/style.py.
    @Property(QColor, notify=changed)
    def shadowInk(self) -> QColor: return self._c("shadow_ink")

    # ``specular`` (docs/design/cockpit_design_system.md §2) is a
    # translucent white highlight whose ALPHA (not hue) differs per theme —
    # gui/style.py stores it as an ``rgba(255, 255, 255, a)`` QSS string,
    # which QColor cannot parse (see ``_alpha_from_rgba`` above), so it is
    # intentionally NOT in TOKEN_MAP (whose consistency test compares exact
    # hex strings) and is parsed here from style.py's own string instead.
    @Property(QColor, notify=changed)
    def specular(self) -> QColor:
        # Parsed live from ``palette(_MODE)`` (not cached at import/class
        # scope) for the same reason ``_c()`` re-reads it on every access:
        # gui/style.py's LIGHT/DARK dicts are mutated in place at runtime by
        # ``set_glass_amount()``/dev-tool overrides (see its
        # ``_recompute_palettes``), so a cached alpha would go stale exactly
        # the way the old hardcoded 0.85/0.045 table did. ``_specular_alpha``
        # (not ``_alpha_from_rgba`` directly) so a malformed token degrades to
        # a warned fallback instead of raising from inside this @Property.
        alpha = _specular_alpha(_MODE)
        c = QColor(255, 255, 255)
        c.setAlphaF(alpha)
        return c

    # -- motion/transition timing (law 8 — constant across both themes) -- #
    @Property(int, constant=True)
    def transitionMs(self) -> int: return TRANSITION_MS

    # -- plot canvas colours (fixed in BOTH themes — constants) ---------- #
    @Property(QColor, constant=True)
    def plotBg(self) -> QColor: return QColor(PLOT_BG)

    @Property(QColor, constant=True)
    def plotFg(self) -> QColor: return QColor(PLOT_FG)

    @Property(QColor, constant=True)
    def plotGrid(self) -> QColor: return QColor(PLOT_GRID)

    @Property(QColor, constant=True)
    def plotOverlay(self) -> QColor: return QColor(PLOT_OVERLAY)

    # -- type scale (px, shared across themes — constants) --------------- #
    @Property(int, constant=True)
    def fontXs(self) -> int: return FONT["xs"]

    @Property(int, constant=True)
    def fontSm(self) -> int: return FONT["sm"]

    @Property(int, constant=True)
    def fontMd(self) -> int: return FONT["md"]

    @Property(int, constant=True)
    def fontLg(self) -> int: return FONT["lg"]

    @Property(int, constant=True)
    def fontXl(self) -> int: return FONT["xl"]

    @Property(int, constant=True)
    def fontDisplay(self) -> int: return FONT["display"]

    # -- type-scale ROLES (cockpit_design_system.md §3 — same constants the
    #    QSS side reads, so QML tiles and QWidget tiles render one scale) -- #
    @Property(int, constant=True)
    def fontMetricLabel(self) -> int: return FONT_METRIC_LABEL_PX

    @Property(int, constant=True)
    def fontValue(self) -> int: return FONT_VALUE_PX

    @Property(int, constant=True)
    def fontValueCompact(self) -> int: return FONT_VALUE_COMPACT_PX

    @Property(int, constant=True)
    def fontUnit(self) -> int: return FONT_UNIT_PX

    @Property(int, constant=True)
    def trackingMetricLabel(self) -> int: return TRACKING_METRIC_LABEL_PX

    # LANTERN kit-bridge typography roles (kit_spec_v1.md §6 + Appendix A.2;
    # U2-entry Theme-bridge beat, docs/CODEX_QUEUE.md §C13) — every one of
    # these already exists as a named FONT_*_PX/WEIGHT_* constant in
    # gui/style.py; only the bridge property was missing. `weightMetricLabel`/
    # `weightValue`/`weightUnit` complete the metric-tile trio that
    # `fontMetricLabel`/`fontValue`/`fontValueCompact`/`fontUnit` above only
    # covered the SIZE half of.
    @Property(int, constant=True)
    def fontRail(self) -> int: return FONT_RAIL_PX

    @Property(int, constant=True)
    def weightRail(self) -> int: return WEIGHT_RAIL

    @Property(int, constant=True)
    def fontPanelTitle(self) -> int: return FONT_PANEL_TITLE_PX

    @Property(int, constant=True)
    def weightPanelTitle(self) -> int: return WEIGHT_PANEL_TITLE

    @Property(int, constant=True)
    def fontBody(self) -> int: return FONT_BODY_PX

    @Property(int, constant=True)
    def weightBody(self) -> int: return WEIGHT_BODY

    @Property(int, constant=True)
    def weightMetricLabel(self) -> int: return WEIGHT_METRIC_LABEL

    @Property(int, constant=True)
    def weightValue(self) -> int: return WEIGHT_VALUE

    @Property(int, constant=True)
    def weightUnit(self) -> int: return WEIGHT_UNIT

    # Resolved monospace family for QML `font.family` (a single string —
    # the QML font value type has no families-list property). Picks the
    # first gui.style.MONO_FAMILIES entry the font database actually has;
    # falls back to the first entry (Qt's own font matching then does the
    # rest). Resolved lazily & cached: the font DB needs a QGuiApplication,
    # which is guaranteed by the time any QML binding evaluates.
    _mono_family: str | None = None

    @Property(str, constant=True)
    def monoFamily(self) -> str:
        if Theme._mono_family is None:
            from PySide6.QtGui import QFontDatabase
            available = set(QFontDatabase.families())
            Theme._mono_family = next(
                (f for f in MONO_FAMILIES if f in available), MONO_FAMILIES[0])
        return Theme._mono_family

    # -- spacing scale (px — constants) ---------------------------------- #
    @Property(int, constant=True)
    def spaceXs(self) -> int: return SPACE["xs"]

    @Property(int, constant=True)
    def spaceSm(self) -> int: return SPACE["sm"]

    @Property(int, constant=True)
    def spaceMd(self) -> int: return SPACE["md"]

    @Property(int, constant=True)
    def spaceLg(self) -> int: return SPACE["lg"]

    @Property(int, constant=True)
    def spaceXl(self) -> int: return SPACE["xl"]

    # -- radius scale (px — constants) ----------------------------------- #
    @Property(int, constant=True)
    def radiusSm(self) -> int: return RADIUS["sm"]

    @Property(int, constant=True)
    def radiusMd(self) -> int: return RADIUS["md"]

    @Property(int, constant=True)
    def radiusLg(self) -> int: return RADIUS["lg"]

    @Property(int, constant=True)
    def radiusPill(self) -> int: return RADIUS["pill"]

    # -- LANTERN kit-bridge — round-03 elevation-rung radii (kit_spec_v1.md
    #    §6 + Appendix A.1; already SHIPPED in gui/style.py's RADIUS map,
    #    only the bridge property was missing) ---------------------------- #
    @Property(int, constant=True)
    def radiusXl(self) -> int: return RADIUS["xl"]

    @Property(int, constant=True)
    def radiusShelf(self) -> int: return RADIUS["shelf"]

    # -- LANTERN kit-bridge — glass alphas (Appendix A.1). Mode-dependent
    #    (`notify=changed`) even though the DARK/LIGHT SCENE-tier alphas
    #    are fixed constants, matching the ``dark``/``glassCardAlpha``-style
    #    pattern used elsewhere in this class for a value that varies by
    #    theme but not on its own. ``glassPaneAlpha`` additionally tracks
    #    the LIVE, user-tunable panel-glass alpha (gui.style.
    #    set_panel_glass_alpha, theme editor's Material section) via
    #    ``get_panel_glass_alpha()`` — re-read on every access, same idiom
    #    as ``specular`` above; a change made outside a theme toggle will
    #    only reach a bound QML property on the NEXT ``changed`` emission
    #    (a pre-existing limitation of this class's single notify signal,
    #    not new to this beat). --------------------------------------------#
    @Property(float, notify=changed)
    def glassPaneAlpha(self) -> float: return get_panel_glass_alpha()

    @Property(float, notify=changed)
    def glassCardAlpha(self) -> float:
        return GLASS_CARD_ALPHA_DARK if _MODE == "dark" else GLASS_CARD_ALPHA_LIGHT

    # -- LANTERN kit-bridge — motion & living-glass (kit_spec_v1.md §6 +
    #    Appendix A.3). `motionEnabled`/`livingGlassMode`/`livingGlassSpeed`
    #    read gui.app_settings live (same "re-read on every access" idiom as
    #    `specular`/`glassPaneAlpha` above — see their docstrings for the
    #    same notify-signal caveat). `motionTap`/`motionUnfold` are fixed
    #    spec durations; `motionSpringUi` is ONE QVariant exposure carrying
    #    both spring constants together (kit_spec_v1.md Appendix A.3 counts
    #    it as a single bindable property, not two). ----------------------#
    @Property(bool, notify=changed)
    def motionEnabled(self) -> bool: return app_settings.motion_enabled()

    @Property(str, notify=changed)
    def livingGlassMode(self) -> str: return app_settings.living_glass_mode()

    @Property(float, notify=changed)
    def livingGlassSpeed(self) -> float: return app_settings.living_glass_speed()

    @Property(int, constant=True)
    def motionTap(self) -> int: return MOTION_TAP_MS

    @Property(int, constant=True)
    def motionUnfold(self) -> int: return MOTION_UNFOLD_MS

    @Property("QVariant", constant=True)
    def motionSpringUi(self) -> dict: return dict(MOTION_SPRING_UI)

    # -- LANTERN kit-bridge — shadow-ladder alphas (kit_spec_v1.md §2.5/
    #    Appendix A.4, APPROVED for promotion). Mode-dependent, same pattern
    #    as `glassCardAlpha` above. `shadowInk` itself is a colour property,
    #    already added alongside the other TOKEN_MAP colours above. -------#
    @Property(float, notify=changed)
    def shadowA(self) -> float: return SHADOW_A_DARK if _MODE == "dark" else SHADOW_A_LIGHT

    @Property(float, notify=changed)
    def shadowB(self) -> float: return SHADOW_B_DARK if _MODE == "dark" else SHADOW_B_LIGHT

    @Property(float, notify=changed)
    def shadowC(self) -> float: return SHADOW_C_DARK if _MODE == "dark" else SHADOW_C_LIGHT

    @Property(float, notify=changed)
    def shadowD(self) -> float: return SHADOW_D_DARK if _MODE == "dark" else SHADOW_D_LIGHT

    # -- LANTERN kit-bridge — frost, focus and ground (kit_spec_v1.md §6 +
    #    Appendix A.5). Fixed spec constants except `focusHaloAlpha`, which
    #    is mode-dependent (0.35 dark / 0.25 light, ruling 3's halo garnish
    #    — never appears on hazard rungs, ruling 4). `groundTintAlphaMax` is
    #    the already-SHIPPED `GROUND_TINT_ALPHA_MAX` band-law budget (kit §1.1
    #    / AmbientGround) — only the bridge property was missing. ---------#
    @Property(int, constant=True)
    def blurPane(self) -> int: return BLUR_PANE_PX

    @Property(int, constant=True)
    def blurCard(self) -> int: return BLUR_CARD_PX

    @Property(int, constant=True)
    def blurOverlay(self) -> int: return BLUR_OVERLAY_PX

    @Property(int, constant=True)
    def frostRebakeHzSubtle(self) -> int: return FROST_REBAKE_HZ_SUBTLE

    @Property(int, constant=True)
    def frostRebakeHzFull(self) -> int: return FROST_REBAKE_HZ_FULL

    @Property(float, notify=changed)
    def focusHaloAlpha(self) -> float:
        return FOCUS_HALO_ALPHA_DARK if _MODE == "dark" else FOCUS_HALO_ALPHA_LIGHT

    @Property(int, constant=True)
    def focusRingOffsetPx(self) -> int: return FOCUS_RING_OFFSET_PX

    @Property(int, constant=True)
    def groundFlowPeriodS(self) -> int: return GROUND_FLOW_PERIOD_S

    @Property(float, constant=True)
    def groundTintAlphaMax(self) -> float: return GROUND_TINT_ALPHA_MAX
