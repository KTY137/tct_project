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

import weakref

from PySide6.QtCore import Property, QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtQml import QmlElement, QmlSingleton

from gui.style import (
    FONT, FONT_METRIC_LABEL_PX, FONT_UNIT_PX, FONT_VALUE_COMPACT_PX,
    FONT_VALUE_PX, MONO_FAMILIES, RADIUS, SPACE, PLOT_BG, PLOT_FG, PLOT_GRID,
    PLOT_OVERLAY, TRACKING_METRIC_LABEL_PX, TRANSITION_MS, palette,
)

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

    # ``specular`` (docs/design/cockpit_design_system.md §2) is a
    # translucent white highlight whose ALPHA (not hue) differs per theme —
    # gui/style.py stores it as an ``rgba(255, 255, 255, a)`` QSS string,
    # which QColor cannot parse (QColor's string constructor only accepts
    # named colours / "#rrggbb[aa]", not CSS rgba() functional notation), so
    # it is intentionally NOT in TOKEN_MAP (whose consistency test compares
    # exact hex strings) and is computed here from a small alpha-only table
    # instead of duplicating a second hex.
    _SPECULAR_ALPHA = {"light": 0.85, "dark": 0.045}

    @Property(QColor, notify=changed)
    def specular(self) -> QColor:
        alpha = self._SPECULAR_ALPHA.get(_MODE, self._SPECULAR_ALPHA["dark"])
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
