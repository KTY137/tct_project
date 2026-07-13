"""
Application-wide visual style — light and dark themes.

A single QSS template is rendered against a palette dict, so light/dark share
exactly the same layout/spacing and only the colours differ.  Applied via
``apply_theme(app, mode)`` from ``main.py`` and toggled live from the View menu.

This module is the design-system foundation (Milestone 2.1).  Components should
reference the shared *tokens* below (accent/status colours, spacing, radius and
type scales, axis-rail palette) instead of hardcoding magic numbers or colours.

v5 token-calibration pass (apple_style_ui_audit.md, Track A step 5) reconciled
these tokens against ``artifacts_claude/tct_polish_preview.html``: a
palette-reach fix for the toolbar Connect/Disconnect buttons (see the
``#connectBtn``/``#disconnectBtn`` rules), a calmer label/heading weight
scale (700 -> 600 on captions/eyebrows/section titles), and a distinct
large/light ``FONT_DISPLAY`` role for hero numeric tiles (``#readoutCell``)
so values "breathe" instead of reusing the small bold-mono instrument-LCD
look everywhere. Theming-only: no widget/layout was added, removed, or moved.

Cockpit v5 D0 pass (docs/design/cockpit_design_system.md, ratified
2026-07-12 — the CANONICAL spec, superseding earlier apple_style_ui_audit.md
calls where the two disagree, e.g. hero values going back to mono/w600 per
§3): the accent/canvas/panel/hairline/text/sim/good/warn(=armed)/crit(=danger)
values below are now sourced VERBATIM from the frozen reference
``artifacts_claude/tct_cockpit_design_v4_final.html``'s ``:root``/
``[data-theme]`` custom properties, plus four new surface/emphasis tokens
(``raised``/``sunk``/``well``/``specular``) and the canonical semantic names
(``danger``/``armed`` alongside the pre-existing ``crit``/``warn`` — same
values, both keys work) from that spec's §2. This is a FOUNDATION/token pass
only (docs/design/cockpit_design_system.md §9 "D0"): every existing dict key
keeps working (additive), individual panels are not yet restyled (that is
D1+), but because so much shared QSS already reads these tokens, the visual
effect reaches every panel at once — see the new Type-scale ROLES block
below (``FONT_RAIL_PX``, ``FONT_PANEL_TITLE_PX``, ``FONT_METRIC_LABEL_PX``,
``FONT_VALUE_PX``, ``FONT_UNIT_PX``, ...) for the vocabulary D1+ panels
should reach for instead of a generic ``FONT["xs".."display"]`` step.
"""
from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette

from gui import backdrop

# ---------------------------------------------------------------------------
# Scales — reference these instead of magic numbers so spacing/rounding/type
# stay coherent across every panel.  They are plain module constants; the QSS
# template interpolates them directly.
# ---------------------------------------------------------------------------

# Spacing scale (px)
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE = {"xs": SPACE_XS, "sm": SPACE_SM, "md": SPACE_MD, "lg": SPACE_LG, "xl": SPACE_XL}

# Corner-radius scale (px) — cockpit v5 round-2: recalibrated to the frozen
# artifact's OWN radius tokens (tct_cockpit_design_v4_final.html ``--r-sm:8;
# --r:12; --r-lg:16`` — the spec §2 "Radii 8/12/16" rule). sm = buttons /
# inputs / chips-adjacent small shapes; md = cards / tiles; lg = large
# clusters / hero shells. xs (4) survives only for sub-element highlights
# (menu items, tooltips) that have no artifact counterpart; pill is the one
# intentionally larger shape.
RADIUS_XS = 4     # menu-item highlights / tooltips (sub-element only)
RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16
RADIUS_PILL = 999
RADIUS = {"xs": RADIUS_XS, "sm": RADIUS_SM, "md": RADIUS_MD,
          "lg": RADIUS_LG, "pill": RADIUS_PILL}

# Type scale (px). Roles (see build_qss() call sites for where each lands):
#   xs/sm  = caption / small label (eyebrows, table headers, chip text).
#   md     = body — the "*" default; stays normal-weight, never bold.
#   lg     = small heading (EmptyState headline).
#   xl     = true instrument-readout digits (motor position LCD).
#   display= hero numeric tile value (MetricTile/ReadoutCell) — large and
#            light, the "values ... do not breathe enough" fix from
#            apple_style_ui_audit.md. Monospace stays reserved for true
#            numeric readouts/identifiers (MONO_FAMILY below); display
#            values use the proportional UI face instead.
FONT_XS = 11
FONT_SM = 12
FONT_MD = 13
FONT_LG = 18       # was 16 — EmptyState headline gets a touch more presence
FONT_XL = 20
FONT_DISPLAY = 24  # hero tile values (artifact reference: 26px / weight 350)
FONT = {"xs": FONT_XS, "sm": FONT_SM, "md": FONT_MD, "lg": FONT_LG, "xl": FONT_XL,
        "display": FONT_DISPLAY}

# ---------------------------------------------------------------------------
# Font families — round-2 typography pass (Kaya live-review 2026-07-12).
#
# SANS_FAMILIES: the artifact's own --sans stack, Windows-first. On Win 11
# Qt's font DB enumerates the Segoe UI Variable *named instances* as separate
# families ("... Display"/"... Text"/"... Small"); the plain "Segoe UI
# Variable" typographic family may or may not be enumerable depending on the
# font engine, so both spellings are listed — otherwise the old single
# '"Segoe UI Variable"' request silently fell through to classic Segoe UI,
# which is a big part of "the fonts don't look like the artifact". Display
# is listed first because the approved artifact renders with Display in the
# browser (its --sans lists "Segoe UI Variable Display" before "Segoe UI").
#
# MONO_FAMILIES: reordered to prefer Cascadia Mono (the modern Win-11 mono,
# and the artifact's nearest available --mono entry) over Consolas.
#
# Both lists are consumed twice: joined into QSS ``font-family`` strings
# below (Qt 6 QSS maps a comma list onto QFont::setFamilies — verified: the
# resolved widget font carries the full fallback list), and set directly on
# the application-default QFont in ``apply_theme`` (so QML chrome text and
# any unstyled widget inherit the same stack + hinting).
# ---------------------------------------------------------------------------
SANS_FAMILIES = [
    "Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI Variable",
    "Segoe UI", "Inter", "Helvetica Neue", "Arial",
]
SANS_FAMILY = ", ".join(f'"{f}"' for f in SANS_FAMILIES) + ", system-ui, sans-serif"

MONO_FAMILIES = [
    "Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono", "Courier New",
]
MONO_FAMILY = ", ".join(f'"{f}"' for f in MONO_FAMILIES) + ", monospace"

# Text-rasterization hinting for the app-default font (Windows: DirectWrite).
# "vertical" ≈ the natural/symmetric rendering browsers use — the closest Qt
# gets to how the approved HTML artifact rasterizes on the same display;
# "none" is softer/mac-like (fractional advances), "full" is the classic
# grid-fit Win32 look the app previously inherited by default. ONE tunable
# token: if Kaya's next live look wants crisper or softer text, change this
# string, nothing else.
FONT_HINTING = "vertical"
_HINTING_PREFS = {
    "none": QFont.HintingPreference.PreferNoHinting,
    "vertical": QFont.HintingPreference.PreferVerticalHinting,
    "full": QFont.HintingPreference.PreferFullHinting,
    "default": QFont.HintingPreference.PreferDefaultHinting,
}


def _apply_app_font(app) -> None:
    """Set the application-default ``QFont`` (family stack + px size +
    hinting preference).

    QSS ``font-family``/``font-size`` only reach QWidgets; the QML chrome
    (rail / pill shelf / status strip) and anything unstyled inherit the
    *application* font — previously the raw platform default (classic
    "Segoe UI" 9 pt, full hinting), which is why chrome text looked flatter
    than the artifact. Pixel-sized (not pt) so QWidget-QSS px, QML
    ``font.pixelSize`` and this default all live on one DPI-consistent px
    scale. Hinting is NOT expressible in QSS, but stylesheet font resolution
    (``rule.font.resolve(widget.font())``) inherits every property QSS does
    not set — so setting it here modernises QSS-styled text too."""
    f = QFont()
    f.setFamilies(SANS_FAMILIES)
    f.setPixelSize(FONT_MD)
    f.setHintingPreference(
        _HINTING_PREFS.get(FONT_HINTING, QFont.HintingPreference.PreferDefaultHinting))
    if app.font() != f:
        app.setFont(f)


def _apply_app_palette(app, p: dict) -> None:
    """Backstop the canvas colour in the *application palette*, not just in QSS.

    The QSS canvas rule names the real shells (``QMainWindow``, ``QDialog``,
    ``QWidget#mainShell``) instead of the old bare-``QWidget`` blanket that
    painted a black box behind every label. A widget shown as its OWN top-level
    window without being one of those (a panel grabbed standalone by
    ``scripts/capture_panels.py``, a future popup) then has no styled ancestor to
    inherit from and would fall back to the platform's light grey — wrong in the
    dark theme. Qt fills exactly that case from ``QPalette.Window``.

    Deliberately minimal: only ``Window``/``WindowText``. Nothing in this GUI
    sets ``autoFillBackground``, so these roles reach *only* the unstyled
    top-level fill — they cannot repaint styled widgets. Roles like ``Base``
    are left alone; item views carry explicit QSS surfaces."""
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(p["bg"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(p["text"]))
    app.setPalette(pal)


# ---------------------------------------------------------------------------
# Type-scale ROLES (docs/design/cockpit_design_system.md §3, Codex-calibrated).
# Distinct from the generic FONT["xs".."display"]/RADIUS scales above: these
# are named for the *role* a panel is styling (a rail button vs. a panel
# title vs. a metric label vs. a hero value vs. a unit suffix) rather than a
# generic size step, so D1+ panels reach for e.g. ``FONT_METRIC_LABEL_PX``
# instead of re-guessing "was it FONT_XS or 10?" per call site. The spec
# gives each role a px *range*; each constant here picks ONE concrete number
# from that range (documented alongside) so every panel adopting a role
# renders pixel-identical instead of drifting by eye. Weights are plain ints
# (Qt QSS already accepts arbitrary 100-900 weights — see the pre-existing
# ``font-weight: 640`` in ``eyebrow_title`` below — not just normal/bold).
# ---------------------------------------------------------------------------
FONT_RAIL_PX = 13                  # rail / button labels (range 13)
WEIGHT_RAIL = 600                  # (range w560-600)

FONT_PANEL_TITLE_PX = 18           # panel titles (range 17-20; no hero titles
WEIGHT_PANEL_TITLE = 650           # in operational panels)

FONT_BODY_PX = 13                  # explanatory prose — sentence-case, never
WEIGHT_BODY = 450                  # uppercase (law 3) — (range 12.5-13/w400-450)

FONT_METRIC_LABEL_PX = 10          # tiny tracked mono uppercase "instrument
WEIGHT_METRIC_LABEL = 600          # engraving" label (MetricTile/ReadoutCell
TRACKING_METRIC_LABEL_EM = 0.08    # title, chip text) — tracking is a MAXIMUM
TRACKING_METRIC_LABEL_PX = 1       # (<=.08em); Qt QSS letter-spacing takes a
                                    # px length, not em — 1px is the closest
                                    # legible step at a 10px face.

FONT_VALUE_PX = 26                 # primary/hero metric value (range 24-28),
FONT_VALUE_COMPACT_PX = 18         # mono, tabular; compact variant is the
WEIGHT_VALUE = 600                 # tile's smaller/dense mode (range 17-20).

FONT_UNIT_PX = 11                  # unit suffix, muted ink (range 11-12)
WEIGHT_UNIT = 400

# Motion/transition timing (law 8: "state transitions ease ~200 ms; only
# live states pulse"). A shared constant so QSS/QML/any future
# QVariantAnimation-driven repolish agrees on one number instead of each
# call site picking its own — mirrored as ``Theme.transitionMs`` in
# ``gui/qml_theme.py``. Qt Style Sheets have no ``transition`` property (CSS
# does, the HTML artifact reference uses it), so on the QWidget side this is
# documentation/a future animation's duration, not a live QSS transition;
# QML's ``Behavior { ... duration: Theme.transitionMs }`` bindings are where
# it is actually load-bearing today (see gui/qml/MetricTile.qml).
TRANSITION_MS = 200

def _rgba(hex_color: str, alpha: float) -> str:
    """Hex ``#rrggbb`` -> ``rgba(r,g,b,alpha)`` for translucent QSS fills.

    Defined above ``LIGHT``/``DARK`` (cockpit v5 token pass) so the palette
    dicts themselves can compute a derived tone (e.g. ``tint`` from
    ``accent``) at definition time instead of hand-picking a second,
    easy-to-drift hex for the same colour."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _darken(hex_color: str, amount: float = 0.15) -> str:
    """Hex ``#rrggbb`` darkened toward black by *amount* (0..1).

    Used for hover/pressed shades of solid accent buttons (connect/disconnect/
    danger) so those states derive from the same token instead of a separately
    hand-picked hex — one source of truth per colour. Defined above
    ``LIGHT``/``DARK`` alongside ``_rgba`` (see its docstring)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = max(0, min(255, int(r * (1 - amount))))
    g = max(0, min(255, int(g * (1 - amount))))
    b = max(0, min(255, int(b * (1 - amount))))
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(fg_hex: str, bg_hex: str, alpha: float) -> str:
    """Alpha-blend *fg_hex* over *bg_hex* at *alpha* (0..1), returning a
    PLAIN (opaque) hex — unlike ``_rgba`` (a translucent ``rgba(...)`` QSS
    literal), this is for tokens that must also be a real, directly
    QColor-parseable hex: ``gui/qml_theme.py``'s ``Theme`` singleton reads
    palette dict values straight into ``QColor(...)``, which — unlike Qt
    Style Sheets — does NOT understand CSS ``rgba()`` functional notation.
    Used for "tint"/"active" (an accent wash resolved once at palette-build
    time against the surface it typically sits on, "panel") so the SAME
    dict value works for both a QSS background and a QML ``QColor``
    property instead of needing two representations of one colour."""
    fr, fgc, fb = (int(fg_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    br, bgc, bb = (int(bg_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    r = round(fr * alpha + br * (1 - alpha))
    g = round(fgc * alpha + bgc * (1 - alpha))
    b = round(fb * alpha + bb * (1 - alpha))
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Shared accent — cockpit v5 token pass (docs/design/cockpit_design_system.md
# §2, ratified 2026-07-12): "one accent", #5AA9FF dark / #2A6FE0 light,
# sourced verbatim from artifacts_claude/tct_cockpit_design_v4_final.html's
# ``:root``/``[data-theme]`` custom properties (the frozen visual reference).
# ``accent_strong`` is DERIVED (``_darken(accent, 0.15)``, no longer a
# separately hand-picked hex) — the hover/pressed/default-fill variant.
# ---------------------------------------------------------------------------
ACCENT_LIGHT = "#2A6FE0"
ACCENT_LIGHT_STRONG = _darken(ACCENT_LIGHT, 0.15)
ACCENT_DARK = "#5AA9FF"
ACCENT_DARK_STRONG = _darken(ACCENT_DARK, 0.15)

# Status accents — cockpit v5: law 1 collapses the semantic palette to four
# saturated accents (danger/armed/good/sim) plus the one accent above; "warn"/
# "crit" (the pre-existing dict keys almost every QSS rule below already
# reads) are kept as the SAME names but now hold the ratified armed/danger
# hex exactly (see DANGER_*/ARMED_* aliases below) — every existing p['warn']/
# p['crit'] consumer repaints to the correct colour with zero call-site edits,
# which is the whole point of a foundation/token pass ("lifts every panel").
# The exported names remain available for existing panel code that imports a
# single fixed semantic colour; the palette below uses theme-tuned light/dark
# values for the global QSS.
OK_GREEN = "#3DD68C"          # dark "good" (spec §2)
WARN_AMBER = "#FFB84D"        # dark "armed" (spec §2) — kept under the old
WARN_RED = "#FF5A61"          # dark "danger" (spec §2)   name for compat
OK_GREEN_LIGHT = "#128A63"
WARN_AMBER_LIGHT = "#B26F00"
WARN_RED_LIGHT = "#DE434B"

# Canonical spec names (§2) as their own constants/aliases, for new call
# sites (and the dict keys below) that want to say what they mean instead of
# reaching for the legacy OK_GREEN/WARN_AMBER/WARN_RED names.
GOOD_DARK, GOOD_LIGHT = OK_GREEN, OK_GREEN_LIGHT
ARMED_DARK, ARMED_LIGHT = WARN_AMBER, WARN_AMBER_LIGHT
DANGER_DARK, DANGER_LIGHT = WARN_RED, WARN_RED_LIGHT

# Device-manager status accents (gui/device_panel.py's ``_STATUS_STYLE``) —
# "simulated" and "error", alongside OK_GREEN/WARN_AMBER/WARN_RED above.
# SIM_PURPLE/SIM_PURPLE_LIGHT keep their PRE-EXISTING NAME for import
# compatibility (gui/device_panel.py, gui/camera_panel.py, ... already import
# it) but the VALUE is now the ratified spec "sim" cyan (law 6: "sim never
# borrows green" — and, as importantly, never borrows purple either now that
# a single cyan is the one-and-only sim-marking colour app-wide; see
# SIM_CYAN_DARK/LIGHT for the same value under its honest name for new call
# sites). "error" (a hard device error, distinct from "warn"/"armed") is
# unchanged — not one of the four spec semantic tokens, left for a future
# Bias/Camera EmptyState-error pass (D4) to reconsider.
SIM_PURPLE = "#41D8E4"
SIM_PURPLE_LIGHT = "#0C9FB0"
SIM_CYAN_DARK, SIM_CYAN_LIGHT = SIM_PURPLE, SIM_PURPLE_LIGHT
ERROR_ORANGE = "#ff8a1f"
ERROR_ORANGE_LIGHT = "#d96c00"

# General amber token (distinct from the warn status colour): matches the
# bias axis-rail hue so a "bias" accent is amber everywhere. Unchanged by the
# v5 token pass — axis-rail semantics are D1 (Planner) territory.
AMBER_LIGHT = "#C67F14"
AMBER_DARK = "#E8A33D"

LIGHT = {
    "accent": ACCENT_LIGHT, "accent_strong": ACCENT_LIGHT_STRONG,
    "amber": AMBER_LIGHT,
    "good": OK_GREEN_LIGHT, "warn": WARN_AMBER_LIGHT, "crit": WARN_RED_LIGHT,
    "sim": SIM_PURPLE_LIGHT, "error": ERROR_ORANGE_LIGHT,
    # Canonical spec names (§2) — same values as good/warn/crit/sim above,
    # added so new code can read/write the name the design contract actually
    # uses instead of the legacy good/warn/crit vocabulary.
    "danger": DANGER_LIGHT, "armed": ARMED_LIGHT,
    "canvas": "#E9EDF4", "bg": "#E9EDF4",
    # material/material_strong: toolbar/menu/status-bar chrome. Synced to
    # panel/canvas (v5) rather than a third hand-picked tone, so the ribbon
    # reads as the SAME surface ladder as every card instead of a separately
    # drifting grey.
    "material": "#FFFFFF", "material_strong": "#E9EDF4",
    "panel": "#FFFFFF",
    # border/border_strong: kept as their own keys for existing call sites,
    # synced 1:1 to hairline/hairline_strong (the two concepts were already
    # near-identical pre-v5; DARK even had them byte-equal).
    "border": "#D9DFEA", "border_strong": "#BFC9DA",
    "hairline": "#D9DFEA", "hairline_strong": "#BFC9DA",
    "specular": "rgba(255, 255, 255, 0.85)",
    "toplight": "#F4F7FB",
    "text": "#131A28", "muted": "#525D72", "faint": "#949DB0",
    "on_accent": "#ffffff",
    # tint/active: accent-tinted wash, blended (see ``_blend``) at the
    # spec's "--accent-soft" alpha (0.10 light / 0.13 dark — see DARK below)
    # against "panel" instead of a separately hand-picked hex that could
    # drift from "accent" — and, unlike a raw ``_rgba()`` string, still a
    # plain hex ``gui/qml_theme.py``'s ``Theme.tint`` QColor property can
    # parse directly (see ``_blend``'s docstring).
    "tint": _blend(ACCENT_LIGHT, "#FFFFFF", 0.10),
    "active": _blend(ACCENT_LIGHT, "#FFFFFF", 0.10),
    # field: v5 evidence (tct_cockpit_design_v4_final.html's `.btn` rule) —
    # a DEFAULT BUTTON/CHIP surface is "panel-2" (raised), not a sunken
    # input well; that raised tone is what "field" already meant here
    # (QPushButton/QToolButton/QComboBox/statusChip all key off it). Genuine
    # input wells (QLineEdit/QSpinBox/...) are repointed to "well" directly
    # at their own QSS rule below instead of overloading this token.
    "field": "#F4F7FB",
    # pressed/disabled_bg: a control being pushed in / greyed out both read
    # as "recessed" — the spec's "sunk" surface, rather than two more
    # one-off hand-picked tones.
    "pressed": "#E2E7F0", "disabled_bg": "#E2E7F0",
    # Cockpit kit (Phase 0, docs/design/cockpit_style_overhaul.md §2) —
    # additive layering/emphasis tokens, v5-recalibrated
    # (docs/design/cockpit_design_system.md §2): "raised" (the spec's own
    # name — "panel_2" is kept as an exact alias for existing call sites),
    # "sunk"/"well" are the two recessed surfaces (well = input wells/dial
    # recesses; sunk = a deeper trough, e.g. a segmented-control track or a
    # progress trough); "hover" is a neutral interaction wash — synced to
    # "raised" so the existing `background: p['hover']` hover rules become a
    # same-tone no-op and only their sibling `border-color` rule actually
    # shifts on hover, matching the v5 artifact's own `.btn:hover` (border
    # colour only, no background change).
    "panel_2": "#F4F7FB", "raised": "#F4F7FB", "panel_3": "#eef0f4",
    "sunk": "#E2E7F0", "well": "#EDF1F7",
    "hover": "#F4F7FB",
    # Round-2 material tokens (all DERIVED via _blend — one source of truth):
    #   chrome — the frosted rail/topbar strip: the artifact's
    #     ``color-mix(in srgb, var(--panel-2) 74%, var(--panel))`` (.rail),
    #     the cheap solid fallback for its backdrop blur ("one frosted
    #     chrome strip", spec §2).
    #   strip — the recessed status-strip wash: ``color-mix(sunk 55%, panel)``
    #     (.statusstrip).
    #   edge — the specular TOP EDGE of a raised surface: the artifact's
    #     ``inset 0 1px 0 var(--specular)`` machined-edge highlight,
    #     approximated in QSS as a lighter ``border-top-color`` (QSS has no
    #     inset box-shadow). Alpha follows the per-theme specular token.
    #   edge_shade — the darker top edge of a SUNKEN surface (inputs,
    #     segmented tracks, progress troughs): the inverse cue, approximating
    #     the artifact's ``inset 0 1px 2px rgba(0,0,0,.14-.2)``.
    "chrome": _blend("#F4F7FB", "#FFFFFF", 0.74),
    "strip": _blend("#E2E7F0", "#FFFFFF", 0.55),
    "edge": _blend("#FFFFFF", "#D9DFEA", 0.85),
    "edge_shade": _blend("#000000", "#D9DFEA", 0.16),
    # Plot chrome tokens (grid/overlay) — kept identical in both dicts on
    # purpose, same idiom as good/warn/crit above: the plot canvas itself
    # (PLOT_BG/PLOT_FG, below) is a fixed dark "instrument screen" in BOTH
    # themes, so its grid/overlay accents don't repaint on a theme switch
    # either. Present in both dicts so FigureCard/panels can resolve them
    # via palette(mode) without a fixed-vs-per-theme special case.
    "plot_grid": None, "plot_overlay": None,
}

DARK = {
    "accent": ACCENT_DARK, "accent_strong": ACCENT_DARK_STRONG,
    "amber": AMBER_DARK,
    "good": OK_GREEN, "warn": WARN_AMBER, "crit": WARN_RED,
    "sim": SIM_PURPLE, "error": ERROR_ORANGE,
    "danger": DANGER_DARK, "armed": ARMED_DARK,
    "canvas": "#0A0D13", "bg": "#0A0D13",
    "material": "#121824", "material_strong": "#0A0D13",
    "panel": "#121824",
    "border": "#222B3E", "border_strong": "#334159",
    "hairline": "#222B3E", "hairline_strong": "#334159",
    "specular": "rgba(255, 255, 255, 0.045)",
    "toplight": "#192134",
    "text": "#E9EDF5", "muted": "#98A1B5", "faint": "#5B657A",
    "on_accent": "#04222c",
    "tint": _blend(ACCENT_DARK, "#121824", 0.13),
    "active": _blend(ACCENT_DARK, "#121824", 0.13),
    "field": "#192134",
    "pressed": "#0C1019", "disabled_bg": "#0C1019",
    # See the matching comments in LIGHT above.
    "panel_2": "#192134", "raised": "#192134", "panel_3": "#2b2b31",
    "sunk": "#0C1019", "well": "#0E1420",
    "hover": "#192134",
    # Round-2 material tokens — see the matching comments in LIGHT above.
    # Dark "edge" uses a slightly higher alpha than the 0.045 specular token:
    # a 1px border line has far less area than the artifact's inset highlight
    # band, so it needs a touch more ink to read at all on a real display.
    "chrome": _blend("#192134", "#121824", 0.74),
    "strip": _blend("#0C1019", "#121824", 0.55),
    "edge": _blend("#FFFFFF", "#222B3E", 0.10),
    "edge_shade": _blend("#000000", "#222B3E", 0.30),
    "plot_grid": None, "plot_overlay": None,
}

# ---------------------------------------------------------------------------
# Axis-rail palette — one signature colour per parameter axis, for the scan
# "Recipe Tree" planner and any panel that wants a control to read as its axis
# (bias=amber, Z=violet, X=teal, Y=magenta, laser=purple, delay=green).
# Defined as tokens now; wired into panels in a later task.  ``hazard`` is the
# dangerous-action stripe.
# ---------------------------------------------------------------------------
AXIS_RAIL = {
    "bias":   {"light": "#C67F14", "dark": "#E8A33D"},
    "z":      {"light": "#6455C9", "dark": "#8E82EC"},
    "x":      {"light": "#1690A2", "dark": "#36B7C9"},
    "y":      {"light": "#BB4680", "dark": "#E27AAE"},
    "laser":  {"light": "#8E4FCE", "dark": "#B482EC"},
    "delay":  {"light": "#2A8C6C", "dark": "#4FBE99"},
    "hazard": {"light": "#CE3F35", "dark": "#F2635A"},
}


def axis_color(axis: str, mode: str = "dark") -> str:
    """Return the axis-rail hex for *axis* in the given theme *mode*."""
    key = "light" if str(mode).lower() == "light" else "dark"
    return AXIS_RAIL.get(str(axis).lower(), AXIS_RAIL["bias"])[key]


def palette(mode: str) -> dict:
    """Return the ``LIGHT``/``DARK`` token dict for *mode*.

    Generalises the ``p = DARK if theme_mode == "dark" else LIGHT`` idiom
    every panel/``settings_window._palette`` already hand-rolls into one
    shared helper, for cockpit-kit widgets (``gui/panel_kit.py``) that need
    to resolve a token (e.g. ``palette(mode)["panel_2"]``) outside of
    ``build_qss``.
    """
    return DARK if str(mode).lower() == "dark" else LIGHT


# ---------------------------------------------------------------------------
# Static "glow"/emphasis accent set — cockpit kit (Phase 0). Deliberately
# NOT per-theme (same hex in light and dark, unlike the palette dicts above):
# it marks non-hot-path emphasis (e.g. a CheckableCard/MetricTile "armed"
# state's static border) with one fixed, always-legible language rather than
# a colour that would shift on a theme toggle. This is a *token*, not an
# effect — rule 3 (cockpit_style_overhaul.md §1) still forbids any
# QGraphicsDropShadow/glow QGraphicsEffect on a hot-path widget; nothing here
# creates one, and this set must never be applied to the camera view or a
# pyqtgraph plot/container.
# ---------------------------------------------------------------------------
GLOW = {
    "accent": ACCENT_DARK,
    "good": OK_GREEN,
    "warn": WARN_AMBER,
    "crit": WARN_RED,
    "armed": WARN_AMBER,
    "danger": WARN_RED,   # canonical spec alias for "crit" (see palette dicts)
}


def glow_color(kind: str = "accent") -> str:
    """Return the static glow/emphasis hex for *kind* (non-hot-path chrome
    only — see the ``GLOW`` module docstring above)."""
    return GLOW.get(str(kind).lower(), GLOW["accent"])


def repolish(widget) -> None:
    """Force Qt to re-evaluate stylesheet selectors for dynamic properties."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_chip_state(chip, state: str) -> None:
    """Set a ``statusChip`` QLabel's dynamic ``state`` property and force Qt
    to repaint it immediately.

    Qt does not re-evaluate a stylesheet selector on its own when a dynamic
    property changes — unpolish THEN polish (polish alone can leave the old
    look when moving between two non-default states, e.g. warn -> crit).
    Centralised here so panels reuse one idiom instead of hand-rolling it.
    ``state`` should usually be one of ``{"neutral", "good", "warn", "crit"}``;
    anything else falls through to the quiet neutral pill (see the
    ``QLabel#statusChip`` QSS above).
    """
    chip.setProperty("state", state)
    repolish(chip)


def build_qss(p: dict) -> str:
    return f"""
* {{
    font-family: {SANS_FAMILY};
    font-size: {FONT_MD}px;
    color: {p['text']};
}}

/* Canvas — ONLY the real shells paint it.
   HISTORY (2026-07-13, the "black box behind every label" bug): this rule used
   to read `QMainWindow, QDialog, QWidget {{ ... }}`. A bare `QWidget` type
   selector is a trap: Qt QSS type selectors match SUBCLASSES, and QLabel,
   QCheckBox, QSplitter, QStackedWidget, QFrame ... are all QWidgets. Every one
   of them got `background: bg` (the near-black canvas) AND — because setting any
   background turns on WA_StyledBackground — actually PAINTED it. Invisible on
   the canvas itself, a black slab on every card and panel.
   Never re-add a bare-QWidget background rule; paint shells by name.
   Every top-level window in this app IS a QMainWindow (TCTMainWindow,
   DeviceManagerWindow, detachable_tabs._DetachedWindow) or a QDialog
   (SettingsWindow, ThemeEditorDialog, the ROI/trigger dialogs), so children
   always have a painted shell above them to inherit from. The app palette
   (see `_apply_app_palette`) is the belt-and-braces backstop for anything
   shown as its own window without being one of those (e.g. a panel grabbed
   standalone by scripts/capture_panels.py).
   Guard: tests/test_style_no_label_box.py. */
QMainWindow, QDialog {{ background: {p['bg']}; }}
QWidget#mainShell {{ background: {p['bg']}; }}

/* Text-ish widgets are transparent — they sit ON a surface, they are not one.
   Explicit (not merely "inherited by omission") so that re-introducing a
   blanket rule above cannot silently put the box back: these three still win.
   Chips/marks/pills keep their own fill — ID and class selectors outrank a
   type selector (QLabel#statusChip, QLabel#ribbonMark, ...). */
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}

QScrollArea#ribbonScroll {{ background: transparent; border: none; }}
QFrame#systemRibbon {{
    background: {p['chrome']}; border: 1px solid {p['hairline']};
    border-top-color: {p['edge']};
    border-radius: {RADIUS_MD}px;
}}
QFrame#ribbonBrand {{ background: transparent; }}
QLabel#ribbonMark {{
    min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px;
    border-radius: {RADIUS_SM - 1}px; background: {p['accent']};
    color: {p['on_accent']}; font-weight: 700;
}}
QLabel#ribbonWordmark {{ font-weight: 700; }}
QFrame#ribbonGroup {{
    background: {p['field']}; border: 1px solid {p['hairline']};
    border-top-color: {p['edge']};
    border-radius: {RADIUS_MD}px;
}}
QLabel#ribbonLabel {{
    color: {p['faint']}; font-size: {FONT_XS}px; font-weight: 600; letter-spacing: 0;
}}

/* Group boxes: card-like with breathing room — padding matches the v5
   artifact's nested-card padding (tct_polish_preview.html's `.card2`, 15/17)
   instead of the old, tighter 12/10. The title is a section header — medium
   weight, not bold: apple_style_ui_audit.md flagged headings/labels as
   "too loud/heavy" (was 700; size is unchanged). */
/* NOTE (regression triage 2026-07-12): QGroupBox is the app's plot/camera
   CONTAINER class (scope, camera, monitor, ...). Per-side border colors force
   Qt's slow four-edge border path on every repaint of the frame, so the
   machined top edge is deliberately NOT applied here (hard rule 3: no extra
   paint cost on hot-path containers). The machined material survives on
   static chrome + interaction-only controls (ribbon, buttons, tabs,
   segments, dock titles, control clusters). */
QGroupBox {{
    background: {p['panel']};
    border: 1px solid {p['hairline']};
    border-radius: {RADIUS_MD}px;
    margin-top: {SPACE_LG - 2}px;
    padding: {SPACE_LG - 1}px {SPACE_LG + 1}px {SPACE_LG - 1}px {SPACE_LG + 1}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {SPACE_MD}px;
    padding: 2px {SPACE_SM - 2}px;
    color: {p['muted']};
    font-weight: 600;
    letter-spacing: 0;
}}

/* Inputs — a genuine recessed input WELL (docs/design/cockpit_design_system.md
   §2's ``well`` token — "input wells, dial recesses"; the v4 artifact's own
   ``.field`` class keys off ``--well`` too), distinct from the "field" dict
   key above (which is now the RAISED default-button/chip surface, per the
   artifact's ``.btn{{background:var(--panel-2)}}`` — see the LIGHT/DARK
   comments in gui/style.py). Padding matches the v5 artifact's field
   treatment (tct_polish_preview.html's `.well`, 6/12) for more breathing
   room than the old, tighter 4/8. */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p['well']};
    border: 1px solid {p['hairline']};
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_SM - 2}px {SPACE_MD}px;
    selection-background-color: {p['accent']};
    selection-color: {p['on_accent']};
}}
/* Machined shaded top edge ONLY on the single-line inputs (cursor-blink-rate
   repaints — cheap). The multiline editors (QPlainTextEdit/QTextEdit: log
   view, YAML editor) repaint on every appended line/scroll, so they keep a
   uniform border (hard rule 3 — see the QGroupBox note above). */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    border-top-color: {p['edge_shade']};
}}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {p['border_strong']}; background: {p['well']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {p['accent']};
    outline: 2px solid {_rgba(p['accent'], 0.30)};
    outline-offset: 1px;
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {p['muted']}; background: {p['disabled_bg']};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p['panel']};
    border: 1px solid {p['hairline']};
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS}px;
    outline: none;
    selection-background-color: {p['accent']};
    selection-color: {p['on_accent']};
}}

/* Buttons — round-2: the FULL v4-artifact `.btn` recipe (frozen reference's
   own numbers): raised surface, a VISIBLE hairline-strong border with the
   specular top edge (machined-edge material — the borderless tonal blob of
   round 1 is what read as "flat"), w560 label, hover = border to accent
   (no fill change), padding 8/16 vs the artifact's 9/16. */
QPushButton {{
    background: {p['field']};
    border: 1px solid {p['hairline_strong']};
    border-top-color: {p['edge']};
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_SM - 1}px {SPACE_LG}px;
    font-weight: 560;
}}
QPushButton:hover {{ border-color: {p['accent']}; background: {p['hover']}; }}
QPushButton:pressed {{ background: {p['active']}; }}
QPushButton:focus {{ outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px; }}
QPushButton:disabled {{
    color: {p['faint']}; background: {p['disabled_bg']}; border-color: {p['hairline']};
}}
QPushButton:default, QPushButton[state="primary"] {{
    background: {p['accent']}; color: {p['on_accent']}; border: 1px solid {p['accent']};
}}
QPushButton:default:hover, QPushButton[state="primary"]:hover {{ background: {p['accent_strong']}; }}
QPushButton[state="primary"]:pressed {{ background: {_darken(p['accent_strong'], 0.15)}; }}
QPushButton[state="busy"] {{
    background: {p['tint']}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.55)};
}}
QPushButton[state="good"] {{
    background: {_rgba(p['good'], 0.16)}; color: {p['good']};
    border: 1px solid {_rgba(p['good'], 0.55)};
}}
QPushButton[state="warn"], QPushButton#armedBtn, QPushButton[state="armed"] {{
    background: {_rgba(p['warn'], 0.16)}; color: {p['warn']};
    border: 1px solid {_rgba(p['warn'], 0.65)};
    font-weight: 700;
}}
QPushButton[state="crit"] {{
    background: {_rgba(p['crit'], 0.16)}; color: {p['crit']};
    border: 1px solid {_rgba(p['crit'], 0.55)};
}}

/* Cockpit-kit button variants (gui/panel_kit.py ActionBar) — "secondary" and
   "ghost" are new looks; "primary"/"armed"/"danger" (below, folded into the
   existing :default/warn/#dangerBtn rules) and "busy" (above) reuse rules
   that already existed so every variant maps to exactly one visual language
   app-wide (cockpit_style_overhaul.md §1 rule 1/2) instead of a second,
   parallel button-colour system. */
QPushButton[state="secondary"] {{
    background: {p['field']}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.55)};
}}
QPushButton[state="secondary"]:hover {{
    background: {p['tint']}; border-color: {p['accent']};
}}
QPushButton[state="secondary"]:pressed {{ background: {_rgba(p['accent'], 0.18)}; }}
QPushButton[state="secondary"]:disabled {{
    color: {p['faint']}; background: {p['disabled_bg']}; border-color: transparent;
}}
QPushButton[state="ghost"] {{
    background: transparent; color: {p['muted']}; border: 1px solid transparent;
}}
QPushButton[state="ghost"]:hover {{
    background: {p['field']}; color: {p['text']}; border-color: {p['hairline']};
}}
QPushButton[state="ghost"]:pressed {{ background: {_rgba(p['accent'], 0.14)}; }}
QPushButton[state="ghost"]:disabled {{ color: {p['faint']}; background: transparent; }}

/* "motion" variant — law 2's amber-gated command class (motion commands are
   never plain/ghost and never red; a stage move, a homing action, ... reads
   as amber outline). Numbers match the v4 artifact's ``.btn.motion`` exactly
   (a transparent fill, a ~55%-alpha armed border, armed-coloured text,
   filling to the armed-soft tint on hover) so the QSS-widget and QML/HTML
   references agree byte-for-byte on the recipe, not just the colour. Uses
   "armed" (the canonical spec name — see the palette dicts) rather than the
   legacy "warn" key so a reader can tell this rule was written against the
   ratified command-class law, not a generic warning look. */
QPushButton[state="motion"] {{
    background: transparent; color: {p['armed']};
    border: 1.5px solid {_rgba(p['armed'], 0.55)}; font-weight: 620;
}}
QPushButton[state="motion"]:hover {{
    background: {_rgba(p['armed'], 0.14)}; border-color: {p['armed']};
}}
QPushButton[state="motion"]:pressed {{ background: {_rgba(p['armed'], 0.24)}; }}
QPushButton[state="motion"]:disabled {{
    color: {p['faint']}; background: transparent; border-color: {p['hairline']};
}}

/* Toolbuttons (toolbar actions, tab corner "detach" button, ...) get the same
   quiet hover/pressed/checked language as QPushButton so a toolbar reads as
   one coherent instrument instead of bare OS chrome. The objectName overrides
   below (connectBtn/disconnectBtn) still win — an ID selector out-specifies
   this bare-type one regardless of source order. */
QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: {RADIUS_SM}px; padding: {SPACE_XS}px {SPACE_SM}px;
}}
QToolButton:hover {{ background: {p['field']}; border-color: {p['hairline']}; }}
QToolButton:pressed {{ background: {_rgba(p['accent'], 0.18)}; }}
QToolButton:checked {{
    background: {p['tint']}; color: {p['accent']};
    border-color: {_rgba(p['accent'], 0.55)};
}}
QToolButton:focus {{ outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px; }}
QToolButton:disabled {{ color: {p['muted']}; }}
QToolButton#detachTabButton {{
    background: {p['field']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_MD}px; padding: {SPACE_XS}px {SPACE_SM}px;
    font-weight: 700;
}}
QToolButton#detachTabButton:hover {{
    background: {p['tint']}; color: {p['accent']};
    border-color: {_rgba(p['accent'], 0.45)};
}}
QToolButton#detachTabButton:pressed {{ background: {_rgba(p['accent'], 0.20)}; }}

/* Connect/Disconnect toolbar buttons (objectName set by tct_gui.py after
   building the QToolBar action widgets — "objectNames for the green/red QSS
   accents"). v5 palette-reach fix: this used to be a persistent SOLID
   good/crit fill — the "loud flat-green CONNECT ALL" finding in
   apple_style_ui_audit.md, a leftover pre-v5 button language the rest of
   the app had already moved off of (see the tonal
   QPushButton[state="good"/"crit"] rules above). Rest/hover now share that
   same tonal language; press is the only moment that still goes fully
   solid, matching tct_polish_preview.html's button spec note ("tinted
   material that goes solid only at the moment of commitment"). Connect/
   Disconnect are ordinary reversible actions, not hardware-dangerous ones
   (see CLAUDE.md's confirmation-required list) — unlike dangerBtn below,
   calming their rest state does not touch the danger-hierarchy rule. */
QPushButton#connectBtn, QToolButton#connectBtn {{
    background: {_rgba(p['good'], 0.16)}; color: {p['good']};
    border: 1px solid {_rgba(p['good'], 0.55)}; font-weight: 600;
}}
QPushButton#connectBtn:hover, QToolButton#connectBtn:hover {{
    background: {_rgba(p['good'], 0.26)}; border-color: {p['good']};
}}
QPushButton#connectBtn:pressed, QToolButton#connectBtn:pressed {{
    background: {p['good']}; color: white; border-color: {p['good']};
}}
QPushButton#disconnectBtn, QToolButton#disconnectBtn {{
    background: {_rgba(p['crit'], 0.16)}; color: {p['crit']};
    border: 1px solid {_rgba(p['crit'], 0.55)}; font-weight: 600;
}}
QPushButton#disconnectBtn:hover, QToolButton#disconnectBtn:hover {{
    background: {_rgba(p['crit'], 0.26)}; border-color: {p['crit']};
}}
QPushButton#disconnectBtn:pressed, QToolButton#disconnectBtn:pressed {{
    background: {p['crit']}; color: white; border-color: {p['crit']};
}}
QPushButton#connectBtn:disabled, QToolButton#connectBtn:disabled,
QPushButton#disconnectBtn:disabled, QToolButton#disconnectBtn:disabled {{
    background: {p['disabled_bg']}; color: {p['muted']}; border: 1px solid {p['border']};
}}

/* Tabs (also the DetachableTabWidget) — round-2: the v4 artifact's `.pill`
   language (law 1, quiet nominal): the SELECTED page is a neutral RAISED
   pill (panel-2 + hairline-strong + specular top edge), not an accent-
   tinted one — a selected tab is a place, not a state, so it carries no
   colour. */
/* The pane is a container, not a surface (third instance of the black box):
   it hard-coded `background: bg`, which is right for the SHELL's tab widget
   (it sits on the canvas anyway) but punched a canvas-coloured hole through
   every NESTED tab widget — multi_bias_panel's channel tabs, settings_window's
   section tabs, both of which sit on a panel. Transparent renders identically
   on the shell and correctly inside a panel. */
QTabWidget::pane {{
    border: none; top: -1px; background: transparent;
}}
QTabBar::tab {{
    background: transparent; padding: {SPACE_SM - 2}px {SPACE_LG - 3}px; margin-right: 4px;
    border: 1px solid transparent; border-radius: {RADIUS_MD}px;
    color: {p['muted']}; font-weight: 560;
}}
QTabBar::tab:selected {{
    background: {p['raised']}; color: {p['text']};
    border: 1px solid {p['hairline_strong']};
    border-top-color: {p['edge']};
    font-weight: 600;
}}
/* Hover must be unmistakable (law: what's interactive must look interactive):
   raised wash + hairline-STRONG ring — regression triage 2026-07-12 after the
   neutral-raised selected rewrite left hover reading as nothing. */
QTabBar::tab:hover:!selected {{
    background: {p['field']}; color: {p['text']}; border-color: {p['hairline_strong']};
}}
QTabBar::tab:focus {{ outline: none; }}

/* Menu / toolbar */
QMenuBar {{ background: {p['material_strong']}; border-bottom: 1px solid {p['hairline']}; padding: 1px {SPACE_XS}px; }}
QMenuBar::item {{
    background: transparent; padding: {SPACE_XS}px {SPACE_SM + 2}px; border-radius: {RADIUS_XS}px;
}}
QMenuBar::item:selected {{ background: {p['field']}; color: {p['text']}; }}
QMenuBar::item:pressed {{ background: {p['accent']}; color: {p['on_accent']}; }}
QMenu {{
    background: {p['panel']}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS}px;
}}
QMenu::item {{
    padding: {SPACE_XS + 1}px {SPACE_LG}px {SPACE_XS + 1}px {SPACE_MD}px;
    border-radius: {RADIUS_XS}px;
}}
QMenu::item:selected {{ background: {p['accent']}; color: {p['on_accent']}; }}
QMenu::item:disabled {{ color: {p['muted']}; }}
QMenu::separator {{ height: 1px; background: {p['hairline']}; margin: {SPACE_XS}px {SPACE_SM}px; }}
QToolBar {{ background: {p['material_strong']}; border-bottom: 1px solid {p['hairline']}; spacing: {SPACE_SM - 2}px; padding: {SPACE_XS}px; }}

/* Status bar + dock titles */
QStatusBar {{ background: {p['material_strong']}; border-top: 1px solid {p['hairline']}; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {p['material']}; padding: {SPACE_SM - 2}px {SPACE_MD - 2}px;
    border: 1px solid {p['hairline']}; border-top-color: {p['edge']};
    border-radius: {RADIUS_SM}px;
    font-weight: 600;
}}

QCheckBox {{ spacing: {SPACE_SM}px; }}
QCheckBox:focus, QRadioButton:focus {{
    outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px;
}}
/* Scroll areas are containers, not surfaces — the SECOND source of the black
   box (independent of the blanket QWidget rule above): this used to hard-code
   `background: bg`, so any QScrollArea nested inside a card/panel punched a
   canvas-coloured hole through it. Transparent = it shows whatever surface it
   was placed on. (QScrollArea only; QAbstractItemView / QGraphicsView are NOT
   QScrollArea subclasses, so plots and item views are untouched here.) */
QScrollArea {{ border: none; background: transparent; }}

/* Tooltip — a bordered surface matching the panels (Qt's stock tooltip is an
   abrupt inverted-colour flag; this keeps it calm and legible in both
   themes). */
QToolTip {{
    background: {p['panel']}; color: {p['text']};
    border: 1px solid {p['hairline']};
    padding: {SPACE_XS}px {SPACE_SM}px; border-radius: {RADIUS_SM}px;
}}

/* Scrollbars — slim, rounded, quiet at rest, brighten toward the accent on
   hover/drag so they read as chrome rather than a leftover OS-default gutter. */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 3px 2px 3px 2px; }}
QScrollBar::handle:vertical {{
    background: {_rgba(p['muted'], 0.35)}; min-height: 28px; border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: {_rgba(p['accent'], 0.55)}; }}
QScrollBar::handle:vertical:pressed {{ background: {p['accent']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px; border: none; background: transparent;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px 3px 2px 3px; }}
QScrollBar::handle:horizontal {{
    background: {_rgba(p['muted'], 0.35)}; min-width: 28px; border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{ background: {_rgba(p['accent'], 0.55)}; }}
QScrollBar::handle:horizontal:pressed {{ background: {p['accent']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px; border: none; background: transparent;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* Splitter handles (e.g. scope/motor stage-view split panes) — thin and
   quiet at rest, brighten so a drag target is discoverable without drawing a
   heavy grip when idle. */
QSplitter::handle {{ background: {p['hairline']}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QSplitter::handle:hover {{ background: {p['accent']}; }}

/* Progress bars (IV/V-scan sweeps) — a sunken trough. Uniform border: this
   widget repaints on every scan/sweep tick (hard rule 3 — see QGroupBox). */
QProgressBar {{
    background: {p['disabled_bg']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_SM}px; text-align: center; color: {p['text']};
    min-height: 16px;
}}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: {RADIUS_SM - 1}px; margin: 1px; }}

/* Sliders (scope t/div + offsets, theme editor) — these had NO rule of their
   own and were themed only as a side effect of the old blanket QWidget
   background: with the blanket gone they fell back to the base style's default
   (light-grey) groove, which is wrong in the dark theme. Named explicitly: a
   recessed well groove, a raised machined handle, accent fill up to the value.
   superqt's QSlider subclasses inherit this too. */
QSlider::groove:horizontal {{
    background: {p['well']}; border: 1px solid {p['hairline']};
    height: 4px; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {p['accent']}; border: 1px solid {p['accent']};
    height: 4px; border-radius: 2px;
}}
QSlider::groove:vertical {{
    background: {p['well']}; border: 1px solid {p['hairline']};
    width: 4px; border-radius: 2px;
}}
QSlider::sub-page:vertical {{
    background: {p['well']}; border-radius: 2px;
}}
QSlider::handle {{
    background: {p['field']}; border: 1px solid {p['hairline_strong']};
    border-top-color: {p['edge']};
}}
QSlider::handle:horizontal {{
    width: 12px; margin: -6px 0; border-radius: 7px;
}}
QSlider::handle:vertical {{
    height: 12px; margin: 0 -6px; border-radius: 7px;
}}
QSlider::handle:hover {{ border-color: {p['accent']}; }}
QSlider::handle:pressed {{ background: {p['accent']}; border-color: {p['accent']}; }}
QSlider:disabled {{ }}
QSlider::groove:disabled {{ background: {p['disabled_bg']}; }}
QSlider::handle:disabled {{
    background: {p['disabled_bg']}; border-color: {p['hairline']};
}}

/* Tables (device/monitor panels) */
QHeaderView::section {{
    background: {p['material']}; color: {p['muted']};
    font-weight: 600; font-size: {FONT_XS}px; letter-spacing: 0;
    padding: {SPACE_XS}px {SPACE_SM}px; border: none;
    border-bottom: 1px solid {p['hairline']}; border-right: 1px solid {p['hairline']};
}}
QTableView, QTableWidget {{
    background: {p['panel']}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_SM}px;
    gridline-color: {p['hairline']};
    selection-background-color: {_rgba(p['accent'], 0.22)}; selection-color: {p['text']};
}}
/* Item views are a real surface (like the tables above) — they used to get one
   only by accident, from the blanket QWidget rule that painted the canvas on
   everything. Named explicitly now, on the same `panel` surface as QTableView,
   so dropping the blanket cannot leave a list floating on nothing. */
QListWidget, QTreeWidget, QListView, QTreeView {{
    background: {p['panel']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_SM}px;
    selection-background-color: {_rgba(p['accent'], 0.22)}; selection-color: {p['text']};
}}
QTreeWidget::item, QListWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {p['field']}; }}

/* Danger action button (STOP / immediate hardware abort). Same red language
   as the toolbar Disconnect button, under its own name so any panel can mark
   an "abort now" control this way without borrowing the connect/disconnect
   semantics. QPushButton[state="danger"] (gui/panel_kit.py ActionBar) is
   folded into the same selectors byte-for-byte — an opt-in via the state
   property reaches the identical look instead of a second danger language
   (cockpit_style_overhaul.md §1 rule 2: one danger visual language). */
QPushButton#dangerBtn, QPushButton[state="danger"] {{
    background: {p['crit']}; color: white; border: 1px solid {p['crit']};
    font-weight: 700;
}}
QPushButton#dangerBtn:hover, QPushButton[state="danger"]:hover {{
    background: {_darken(p['crit'], 0.12)}; border-color: {_darken(p['crit'], 0.12)};
}}
QPushButton#dangerBtn:pressed, QPushButton[state="danger"]:pressed {{ background: {_darken(p['crit'], 0.22)}; }}
QPushButton#dangerBtn:focus, QPushButton[state="danger"]:focus {{ outline: 2px solid {_rgba(p['crit'], 0.40)}; outline-offset: 1px; }}
QPushButton#dangerBtn:disabled, QPushButton[state="danger"]:disabled {{
    background: {p['disabled_bg']}; color: {p['muted']}; border: 1px solid {p['border']};
}}

/* Motor-style digital readout (gui/motor_panel.py only) — a dark instrument
   screen like the plot canvas, so a true hardware readout (stage position)
   reads as an instrument display. Values use a monospace face for tabular
   alignment — the "reserve monospace for numeric readouts" half of the
   apple_style_ui_audit.md typography finding. */
QFrame#instrumentReadout {{
    background: {PLOT_BG}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_MD}px;
}}
QLabel#readoutAxis {{
    color: {PLOT_FG}; font-size: {FONT_XS}px; font-weight: 600; letter-spacing: 0;
}}
QLabel#readoutValue {{
    color: {p['accent']};
    font-family: {MONO_FAMILY};
    font-size: {FONT_XL}px; font-weight: 600;
}}

/* Metric tile (gui/status_widgets.py ReadoutCell / gui/panel_kit.py
   MetricTile — the app-wide "hero number" tile: Scan Viewer progress/ETA,
   Camera beam stats, calibration results, intensity readouts, ...).
   cockpit v5 (docs/design/cockpit_design_system.md §3) SUPERSEDES the
   earlier apple_style_ui_audit.md "drop monospace, go proportional" call:
   the ratified type scale is explicit — "primary values mono 24-28 px w600
   tabular" — so the value goes back to MONO_FAMILY at the spec's weight/size
   instead of the old light-proportional look. Label uses the spec's "tiny
   tracked mono uppercase" metric-label role (FONT_METRIC_LABEL_PX/
   WEIGHT_METRIC_LABEL/TRACKING_METRIC_LABEL_PX, defined near FONT above).
   State communicates through VALUE INK ONLY (law 1/no accent side-bars) —
   the four canonical semantic states (danger/armed/good/sim) plus the
   legacy warn/crit names both resolve here; "normal"/no property falls
   through to the bare rule, the same graceful-unknown idiom as statusChip.
   ``stale`` (law 4: "staleness is designed") is a SEPARATE boolean property
   placed after the state rules so it always wins the cascade — a stale tile
   desaturates its ink back to "faint" regardless of the semantic state
   underneath (gui.panel_kit.MetricTile.set_stale()). */
/* Uniform border on purpose: readout cells repaint on every metric update /
   flash repolish (hard rule 3 — see QGroupBox). The QML MetricTile draws its
   specular edge as a real translucent line instead, which QSS cannot. */
QFrame#readoutCell {{
    background: {p['raised']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_MD}px;
}}
/* Label ink: MUTED, not faint — the artifact's `.tile .lab` uses --muted and
   §3 demands "label ink >=85%"; faint is reserved for the caption below. */
QLabel#readoutCellTitle {{
    color: {p['muted']}; font-family: {MONO_FAMILY};
    font-size: {FONT_METRIC_LABEL_PX}px; font-weight: {WEIGHT_METRIC_LABEL};
    letter-spacing: {TRACKING_METRIC_LABEL_PX}px;
}}
QLabel#readoutCellValue {{
    color: {p['text']};
    font-family: {MONO_FAMILY};
    font-size: {FONT_VALUE_PX}px; font-weight: {WEIGHT_VALUE};
    letter-spacing: 0;
}}
/* Compact tile variant (spec §3 "compact 17-20 px") — the dense mode for
   tiles whose values are long strings (a position triple, a channel value
   with unit) or that sit 4-across in a dashboard row. Property set by
   ``gui.panel_kit.MetricTile(compact=True)``; placed before the state rules
   so semantic ink still wins the cascade. */
QLabel#readoutCellValue[compact="true"] {{ font-size: {FONT_VALUE_COMPACT_PX}px; }}
QLabel#readoutCellValue[state="good"] {{ color: {p['good']}; }}
QLabel#readoutCellValue[state="warn"], QLabel#readoutCellValue[state="armed"] {{
    color: {p['armed']}; font-weight: 700;
}}
QLabel#readoutCellValue[state="crit"], QLabel#readoutCellValue[state="danger"] {{
    color: {p['danger']}; font-weight: 700;
}}
QLabel#readoutCellValue[state="sim"] {{ color: {p['sim']}; }}
QLabel#readoutCellValue[stale="true"] {{ color: {p['faint']}; font-weight: 400; }}
QLabel#readoutCellTitle[stale="true"] {{ color: {p['faint']}; }}
QFrame#readoutCell[stale="true"] {{ background: {p['well']}; }}
/* MetricTile caption (gui/panel_kit.py) — the law-4 "why" line under a stale
   tile ("not connected" / "no run" / "value aged Ns"), and any live tile's
   short body caption (e.g. an "avg x N" chip). Sentence-case body ink (law
   3: "Explanations: sentence-case sans. Never uppercase prose."), never the
   tracked-mono-uppercase label treatment above. */
QLabel#metricTileCaption {{
    color: {p['faint']}; font-size: {FONT_XS}px; font-weight: {WEIGHT_BODY};
}}
QLabel#metricTileCaption[stale="true"] {{ color: {p['faint']}; }}
QFrame#readoutCell[flash="accent"] {{
    border: 1px solid {p['accent']}; background: {_rgba(p['accent'], 0.10)};
}}
QFrame#readoutCell[flash="warn"] {{
    border: 1px solid {p['warn']}; background: {_rgba(p['warn'], 0.10)};
}}
QFrame#readoutCell[flash="crit"] {{
    border: 1px solid {p['crit']}; background: {_rgba(p['crit'], 0.10)};
}}

/* Recessed control cluster — groups related buttons (e.g. a jog pad) into
   one visual unit inside a QGroupBox, the way a physical jog controller
   reads as a single control rather than loose buttons in a form. */
QFrame#controlCluster {{
    background: {p['field']}; border: 1px solid {p['hairline']};
    border-top-color: {p['edge']};
    border-radius: {RADIUS_LG}px;
}}
/* Tracking/weight per the spec's metric-label role (FONT_METRIC_LABEL_PX/
   WEIGHT_METRIC_LABEL/TRACKING_METRIC_LABEL_PX — see the Type-scale ROLES
   block near FONT above); font-family is DELIBERATELY left on the shared
   sans stack (the ``*`` selector), not switched to MONO_FAMILY: unlike the
   narrowly-scoped ReadoutCell/MetricTile title (which the spec explicitly
   names and which is almost always a single short ALL-CAPS word), this
   objectName is reused across many existing per-field captions that carry
   real punctuation (units in parens, a trailing colon — e.g. "Y (MM):")
   where a mono fallback face was observed to substitute distractingly wide
   glyphs for "(" ")" ":" on at least one text backend. D1+ per-panel work
   can promote individual captions to MONO_FAMILY once each is reviewed. */
QLabel#clusterCaption {{
    color: {p['muted']};
    font-size: {FONT_METRIC_LABEL_PX}px; font-weight: {WEIGHT_METRIC_LABEL};
    letter-spacing: {TRACKING_METRIC_LABEL_PX}px;
}}

/* Jog pad buttons — compact, square-ish directional keys inside a cluster. */
QPushButton#jogBtn {{
    min-width: 34px; min-height: 30px; font-weight: 700;
    padding: {SPACE_XS}px;
}}
QPushButton#jogBtn:hover {{ border-color: {p['accent']}; color: {p['accent']}; }}
QPushButton#jogBtn:pressed {{ background: {p['pressed']}; }}
QPushButton#jogBtn:focus {{ outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px; }}

/* Segmented control — exclusive preset buttons (e.g. jog step size). Round-2:
   a genuinely SUNKEN track (the artifact's `.seg`: sunk surface + inset
   shadow, approximated by the shaded top edge) with segments one radius step
   tighter than the track (artifact 9/6). */
QFrame#segmented {{
    background: {p['sunk']}; border: 1px solid {p['hairline']};
    border-top-color: {p['edge_shade']};
    border-radius: {RADIUS_SM}px;
}}
QPushButton#segBtn {{
    background: transparent; border: none; border-radius: {RADIUS_SM - 2}px;
    padding: {SPACE_XS + 1}px {SPACE_SM + 2}px; color: {p['muted']}; font-weight: 600;
}}
QPushButton#segBtn:hover:!checked {{ background: {p['hover']}; color: {p['text']}; }}
/* Selected segment: a neutral RAISED chip popping out of the sunken track
   (artifact `.seg button[aria-selected]` — panel-2 + specular, no accent:
   law 1, a mode choice is a place, not a state). */
QPushButton#segBtn:checked {{
    background: {p['raised']}; color: {p['text']};
    border: 1px solid {p['hairline_strong']}; border-top-color: {p['edge']};
}}
QPushButton#segBtn:disabled {{ color: {p['muted']}; background: transparent; }}
QPushButton#segBtn:focus {{ outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px; }}

/* Card wrapper matching QGroupBox's look, for non-groupbox panes that must
   sit visually level with group boxes (e.g. a live view beside a controls
   column). */
/* Uniform border on purpose: cardPane hosts the camera live view, the stage
   view and every FigureCard plot (hard rule 3 — see QGroupBox). */
QFrame#cardPane {{
    background: {p['panel']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_MD}px;
}}

/* Channel card — a cardPane variant used per scope channel.  The panel adds an
   inline coloured left border per channel; this is the shared base look. */
QFrame#channelCard {{
    background: {p['panel']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_SM}px;
}}

/* Eyebrow — a small caption label above a heading/value.  QSS cannot
   uppercase text, so the panel should pass already-uppercased text; letter-
   spacing gives it the tracking real small-caps captions need to read
   comfortably at this size instead of looking merely "shrunk". */
/* font-family deliberately stays on the shared sans stack — see the
   matching comment on QLabel#clusterCaption above (this selector has the
   exact same "reused for punctuation-bearing captions" risk: eyebrow_title
   AND form_row's per-field caption both key off it). */
QLabel#eyebrow {{
    color: {p['faint']};
    font-size: {FONT_METRIC_LABEL_PX}px; font-weight: {WEIGHT_METRIC_LABEL};
    letter-spacing: {TRACKING_METRIC_LABEL_PX}px;
}}

/* ---------------------------------------------------------------------
   Panel composition kit (gui/panel_kit.py) — the design-preview's titled-
   card header (see artifacts_claude/scan_planner_preview_claude.html
   ``.card-hd``), generalised from the bespoke header gui/planner_panel.py
   builds by hand so later panels (starting with the M2.4 scope/laser pilot)
   can reuse one ``Card`` widget instead of re-deriving the same header/
   divider/spacing by eye.  Sits on top of the existing ``cardPane`` surface
   above — a Card IS a cardPane with a structured header prepended.
   --------------------------------------------------------------------- */
QFrame#cardHeader {{
    background: transparent; border-bottom: 1px solid {p['hairline']};
}}
QLabel#cardTitle {{ font-weight: 600; }}
QLabel#cardSubtitle {{
    font-family: {MONO_FAMILY}; font-size: {FONT_XS}px; color: {p['muted']};
}}

/* Status chip — a small pill communicating a status.  Drive the look with a
   dynamic property ``state``; ``gui.status_widgets.normalize_state()`` maps
   every raw device/run string onto the small canonical set used below.
   LAW 1 (quiet nominal): "neutral" is the deliberately unremarkable default
   for connected/ready/idle — ISA-101 grey, not a green "all clear" light;
   colour is reserved for a genuine confirmation ("good"), an abnormal/fault
   condition ("crit"/"warn"), an armed/live-dangerous state ("armed"), or a
   running/live process ("info"/"busy"). LAW 7 (never lie about hardware):
   "disconnected" and "unknown" are each their OWN state — a hollow outline
   (no fill: "nothing there") vs. a dashed border (filled but "not
   confirmed") — collapsing either into plain "neutral" would claim more
   certainty than the driver actually has. LAW 6 (sim can never pass as
   real): "simulated" gets a dashed cyan ring (a cheap hatch approximation)
   instead of a solid fill, and its colour (``p['sim']``) can never resolve
   to green (see gui/style.py's SIM_PURPLE/SIM_CYAN_* constants).
   To restyle live after changing the property, unpolish THEN polish (polish
   alone can keep the old look when transitioning between two non-default
   states):
       chip.setProperty("state", "good")
       chip.style().unpolish(chip); chip.style().polish(chip)
   (``gui.status_widgets.StatusChip.set_status()``/``gui.style.set_chip_state``
   already do this.) Any unlisted state value falls through to the quiet
   neutral pill. */
QLabel#statusChip {{
    padding: 2px {SPACE_SM + 2}px;
    border-radius: {RADIUS_PILL}px;
    font-size: {FONT_XS}px; font-weight: 600;
    background: {p['field']}; color: {p['muted']};
    border: 1px solid {p['hairline']};
}}
QLabel#statusChip[state="neutral"] {{
    background: {p['field']}; color: {p['muted']}; border: 1px solid {p['hairline']};
}}
QLabel#statusChip[state="disconnected"] {{
    background: transparent; color: {p['faint']}; border: 1px solid {p['hairline']};
}}
QLabel#statusChip[state="unknown"] {{
    background: {p['field']}; color: {p['muted']};
    border: 1px dashed {p['hairline_strong']};
}}
QLabel#statusChip[state="good"] {{
    background: {_rgba(p['good'], 0.16)}; color: {p['good']};
    border: 1px solid {_rgba(p['good'], 0.55)};
}}
QLabel#statusChip[state="warn"], QLabel#statusChip[state="fault"] {{
    background: {_rgba(p['warn'], 0.16)}; color: {p['warn']};
    border: 1px solid {_rgba(p['warn'], 0.55)};
}}
QLabel#statusChip[state="crit"] {{
    background: {_rgba(p['crit'], 0.16)}; color: {p['crit']};
    border: 1px solid {_rgba(p['crit'], 0.55)};
}}
QLabel#statusChip[state="info"], QLabel#statusChip[state="busy"] {{
    background: {p['tint']}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.50)};
}}
/* Generic pulse hook for a live/running chip (law 8: "only live states
   pulse"). ``pulsePhase`` is a plain "0"/"1" property an external 1 Hz-
   cadence driver toggles (no timer lives in this module or in
   gui/status_widgets.py — see StatusChip.set_pulse_phase()); distinct from
   the pre-existing per-subsystem ``motionPulse``/``motionPulsePhase`` hooks
   below, which stay as-is for their own laser/HV/scan call sites. */
QLabel#statusChip[state="busy"][pulsePhase="1"] {{
    background: {_rgba(p['accent'], 0.30)}; border: 1px solid {p['accent']};
}}
QLabel#statusChip[state="armed"] {{
    background: {_rgba(p['warn'], 0.20)}; color: {p['warn']};
    border: 1px solid {_rgba(p['warn'], 0.70)};
}}
QLabel#statusChip[state="simulated"] {{
    background: {_rgba(p['sim'], 0.12)}; color: {p['sim']};
    border: 1px dashed {_rgba(p['sim'], 0.70)};
}}
QLabel#statusChip[motionPulse="laser"][motionPulsePhase="0"] {{
    background: {_rgba(p['crit'], 0.14)}; color: {p['crit']};
    border: 1px solid {_rgba(p['crit'], 0.42)};
}}
QLabel#statusChip[motionPulse="laser"][motionPulsePhase="1"] {{
    background: {_rgba(p['crit'], 0.24)}; color: {p['crit']};
    border: 1px solid {_rgba(p['crit'], 0.78)};
}}
QLabel#statusChip[motionPulse="hv"][motionPulsePhase="0"] {{
    background: {_rgba(p['warn'], 0.14)}; color: {p['warn']};
    border: 1px solid {_rgba(p['warn'], 0.42)};
}}
QLabel#statusChip[motionPulse="hv"][motionPulsePhase="1"] {{
    background: {_rgba(p['warn'], 0.24)}; color: {p['warn']};
    border: 1px solid {_rgba(p['warn'], 0.78)};
}}
QLabel#statusChip[motionPulse="scan"][motionPulsePhase="0"] {{
    background: {_rgba(p['accent'], 0.14)}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.42)};
}}
QLabel#statusChip[motionPulse="scan"][motionPulsePhase="1"] {{
    background: {_rgba(p['accent'], 0.24)}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.78)};
}}

/* Same law-1/6/7/8 state language as statusChip above, adapted to a 9px dot:
   "disconnected" is a hollow ring (no fill), "unknown" is a filled-but-
   dashed ring (known-but-unconfirmed), "simulated" is a dashed cyan ring
   with a soft fill (the cheap "hatched" approximation — never a solid fill,
   so it can never read as a confident "good"/"crit" state at a glance), and
   ``pulsePhase`` is the same externally-driven "0"/"1" toggle as the chip's
   hook (no timer here — see StatusLamp.set_pulse_phase()). */
QFrame#statusLamp {{
    min-width: 9px; max-width: 9px; min-height: 9px; max-height: 9px;
    border-radius: 4px; background: {p['muted']}; border: none;
}}
QFrame#statusLamp[state="neutral"] {{ background: {p['muted']}; border: none; }}
QFrame#statusLamp[state="disconnected"] {{
    background: transparent; border: 1px solid {p['faint']};
}}
QFrame#statusLamp[state="unknown"] {{
    background: {p['faint']}; border: 1px dashed {p['hairline_strong']};
}}
QFrame#statusLamp[state="good"] {{ background: {p['good']}; border: none; }}
QFrame#statusLamp[state="warn"], QFrame#statusLamp[state="armed"], QFrame#statusLamp[state="fault"] {{
    background: {p['warn']}; border: none;
}}
QFrame#statusLamp[state="crit"] {{ background: {p['crit']}; border: none; }}
QFrame#statusLamp[state="info"], QFrame#statusLamp[state="busy"] {{ background: {p['accent']}; border: none; }}
QFrame#statusLamp[state="busy"][pulsePhase="1"] {{
    background: {p['accent']}; border: 1px solid {_rgba(p['accent'], 0.55)};
}}
QFrame#statusLamp[state="simulated"] {{
    background: {_rgba(p['sim'], 0.35)}; border: 1px dashed {p['sim']};
}}

QFrame#statusPill {{
    background: {p['material']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_PILL}px;
}}
QFrame#statusPill[state="disconnected"] {{ border: 1px solid {p['hairline']}; }}
QFrame#statusPill[state="unknown"] {{ border: 1px dashed {p['hairline_strong']}; }}
QFrame#statusPill[state="good"] {{ border-color: {_rgba(p['good'], 0.55)}; }}
QFrame#statusPill[state="warn"], QFrame#statusPill[state="armed"], QFrame#statusPill[state="fault"] {{
    border-color: {_rgba(p['warn'], 0.60)};
}}
QFrame#statusPill[state="crit"] {{ border-color: {_rgba(p['crit'], 0.60)}; }}
QFrame#statusPill[state="info"], QFrame#statusPill[state="busy"] {{ border-color: {_rgba(p['accent'], 0.55)}; }}
QFrame#statusPill[state="simulated"] {{ border: 1px dashed {_rgba(p['sim'], 0.70)}; }}
QLabel#statusPillText {{
    font-size: {FONT_XS}px; font-weight: 600; color: {p['text']};
}}

QFrame#activityRing {{
    min-width: 10px; max-width: 10px; min-height: 10px; max-height: 10px;
    border-radius: 5px; background: transparent;
    border: 1px solid {_rgba(p['accent'], 0.28)};
}}
QFrame#activityRing[phase="0"] {{ border-top: 2px solid {p['accent']}; }}
QFrame#activityRing[phase="1"] {{ border-right: 2px solid {p['accent']}; }}
QFrame#activityRing[phase="2"] {{ border-bottom: 2px solid {p['accent']}; }}
QFrame#activityRing[phase="3"] {{ border-left: 2px solid {p['accent']}; }}

/* ---------------------------------------------------------------------
   Scan Routine Planner "Recipe Tree" (Phase 2.2 step 3 — gui/planner_panel.py).
   Axis-rail colours (bias/z/x/y/laser/delay/hazard) differ per row and can't
   be parameterised by a static QSS selector, so the panel sets them as
   per-instance inline styles via ``gui.style.axis_color()`` — the same idiom
   gui/motor_panel.py and gui/bias_panel.py already use for their axis-rail
   readouts (see their ``refresh_theme()``). These rules only carry the
   structural chrome shared by every axis/row.
   --------------------------------------------------------------------- */
QFrame#plannerLoopHead {{
    background: {p['panel']}; border: 1px solid {p['border']};
    border-radius: {RADIUS_MD}px;
}}
QLabel#plannerTag {{
    font-family: {MONO_FAMILY}; font-size: {FONT_XS - 1}px; font-weight: 700;
    letter-spacing: 0; padding: 2px {SPACE_XS + 2}px; border-radius: {RADIUS_XS}px;
}}
QLabel#plannerAxisName {{ font-weight: 600; }}
QLabel#plannerCountPill {{
    font-family: {MONO_FAMILY}; font-size: {FONT_XS}px; font-weight: 700;
    padding: 2px {SPACE_SM + 1}px; border-radius: {RADIUS_PILL}px;
}}
QDoubleSpinBox#plannerValueSpin {{
    font-family: {MONO_FAMILY}; padding: 1px {SPACE_XS}px; min-width: 56px;
}}
QFrame#plannerActionLeaf {{ background: transparent; border-radius: {RADIUS_SM}px; }}
QFrame#plannerActionLeaf:hover {{ background: {p['pressed']}; }}
QLabel#plannerLeafGlyph {{ color: {p['muted']}; min-width: 16px; }}
QLabel#plannerLeafLabel {{ color: {p['text']}; font-weight: 500; }}
QLabel#plannerLeafMeta {{
    font-family: {MONO_FAMILY}; font-size: {FONT_XS}px; color: {p['muted']};
}}
QFrame#plannerGuard {{
    background: {_rgba(p['good'], 0.07)}; border-left: 3px solid {p['good']};
    border-radius: {RADIUS_SM}px;
}}
QLabel#plannerGuardLabel {{ color: {p['good']}; font-weight: 600; }}
QFrame#plannerDanger {{ border-radius: {RADIUS_SM}px; }}
QLabel#plannerDangerLabel {{ font-weight: 600; }}
QLabel#plannerConfirmPill {{
    font-family: {MONO_FAMILY}; font-size: {FONT_XS - 1}px; font-weight: 700;
    letter-spacing: 0; padding: 2px {SPACE_SM}px; border-radius: {RADIUS_PILL}px;
}}

/* Drop ghost-insertion preview row (dragMoveEvent, gui/planner_panel.py
   PlannerPanel._make_ghost_row): dashed border colour and translucent
   background are set per-instance (axis colour for a loop, accent for an
   action) via the same inline-QSS idiom as plannerDanger/plannerGuard above;
   these rules only carry the shared structural chrome. */
QFrame#plannerGhostRow {{ border-radius: {RADIUS_SM}px; }}
QLabel#plannerGhostLabel {{ font-weight: 600; font-style: italic; }}
QLabel#plannerGhostHint {{
    font-family: {MONO_FAMILY}; font-size: {FONT_XS}px; font-style: italic;
}}
"""


# Plot canvas: a dark "instrument screen" in BOTH themes so the plot area never
# blends into the (white) light UI and reads clearly as a plot even when empty.
PLOT_BG = "#0a0b0d"
PLOT_FG = "#c7cfda"

# Plot chrome (grid/overlay) — cockpit kit (Phase 0). Same "fixed in both
# themes" reasoning as PLOT_BG/PLOT_FG above: FigureCard's hosted plot always
# sits on the dark canvas regardless of app theme, so its grid-line and
# overlay-marker (crosshair/ROI/cursor) accents stay fixed too. Backfilled
# into LIGHT/DARK's "plot_grid"/"plot_overlay" placeholders (declared next to
# the other per-theme tokens, above) so callers can resolve every cockpit-kit
# token the same way via palette(mode) instead of a special case for these two.
PLOT_GRID = "#242a33"
PLOT_OVERLAY = "#ffb454"
for _p in (LIGHT, DARK):
    _p["plot_grid"] = PLOT_GRID
    _p["plot_overlay"] = PLOT_OVERLAY
del _p


# ---------------------------------------------------------------------------
# User theme customization — the theme-editor override layer (Kaya request
# 2026-07-12: browse/configure themes + a settable opaque<->glass material;
# UI in gui/theme_editor.py, opened from View ▸ Theme…).
#
# LIGHT/DARK above stay the ONE source of truth every consumer already reads
# (build_qss, palette(), gui/qml_theme.py's live QColor lookups, panels'
# refresh_theme), so customization works by MUTATING those dicts IN PLACE
# (identity preserved — apply_theme's ``palette is DARK`` check and every
# held reference stay valid) from the pristine base snapshots below.
# Nothing changes without user action: with no overrides and
# glass == DEFAULT_GLASS_AMOUNT the recompute reproduces the inline dict
# values byte-for-byte (guarded by tests/test_theme_editor.py).
# ---------------------------------------------------------------------------

# Pristine defaults, snapshot AFTER the plot-token backfill above so a
# recompute can rebuild the live dicts wholesale.
_BASE_LIGHT: dict = dict(LIGHT)
_BASE_DARK: dict = dict(DARK)
_BASE_SANS_FAMILIES: tuple = tuple(SANS_FAMILIES)
_BASE_MONO_FAMILIES: tuple = tuple(MONO_FAMILIES)
_BASE_FONT_HINTING: str = FONT_HINTING
_BASE_FONT_MD: int = FONT_MD
_BASE_RADII: tuple = (RADIUS_SM, RADIUS_MD, RADIUS_LG)

DEFAULT_GLASS_AMOUNT = 1.0

# ---------------------------------------------------------------------------
# WINDOW OPACITY (Kaya, round 2, 2026-07-13) — the knob "Glass" could never be.
#
# The glass amount below is a PRE-BLEND of opaque chrome tokens: QSS has no
# backdrop blur, so it can only change how much two greys differ — it can never
# make the window see-through, which is what the word "glass" promises. Kaya:
# "irgendwie funkt das opaque teil net so." Correct: it was named for something
# it cannot do (the slider is "Surface tint" now — law 8 applies to our own UI
# copy). REAL translucency is the compositor's job:
# ``QWidget.setWindowOpacity`` (DWM does it natively on Win11), whole window
# including its content.
#
# The 0.80 floor is a SAFETY CLAMP, not taste: an HV-live chip and an Abort
# button must stay legible at EVERY reachable setting (rules 2/5). There is no
# path to a ghost cockpit — a hand-edited QSettings value of 0.2 is CLAMPED on
# load, never obeyed (test_theme_editor.py).
MIN_WINDOW_OPACITY = 0.80
MAX_WINDOW_OPACITY = 1.0
DEFAULT_WINDOW_OPACITY = 1.0

# The four pre-blend strengths that ARE the "glass" material (the same
# alphas the "Round-2 material tokens" inline definitions in LIGHT/DARK use
# — see docs/research/apple_vibrancy_qt_feasibility.md: glass = pre-blended
# opaque tokens, no real blur). ``glass_amount`` g in [0, 1] scales them:
#   chrome     = _blend(raised, panel, 0.74 * g)  — frosted rail/ribbon chrome
#   strip      = _blend(sunk,  panel, 0.55 * g)   — recessed status-strip wash
#   edge       = _blend(#fff, hairline, (0.85 light / 0.10 dark) * g)
#                                                 — specular machined top edge
#   edge_shade = _blend(#000, hairline, (0.16 light / 0.30 dark) * g)
#                                                 — shaded top edge of sunken wells
# g == 1.0 (DEFAULT) reproduces today's v4 glass ceiling byte-for-byte;
# g == 0.0 is fully opaque: chrome/strip collapse to plain "panel" and both
# machined edges collapse to the uniform hairline. PLOT_BG/PLOT_FG are
# deliberately NOT parametrized: plots/camera keep the fixed opaque
# instrument screen at ANY glass amount (design law 8 / "nothing translucent
# over a plot").
_GLASS_BLEND_ALPHAS = {
    "light": {"chrome": 0.74, "strip": 0.55, "edge": 0.85, "edge_shade": 0.16},
    "dark":  {"chrome": 0.74, "strip": 0.55, "edge": 0.10, "edge_shade": 0.30},
}

# Safety palette — LOCKED (laws 1/2/6: quiet nominal / command classes / sim
# can never pass as real). "crit"/"warn" are the legacy byte-alias keys of
# "danger"/"armed" (see the palette dicts): locking "danger" while leaving
# "crit" writable would be a bypass, since most QSS rules read p['crit'].
# There is NO override path — apply_theme_overrides raises, and
# sanitize_overrides silently drops these on any preset-JSON load.
SAFETY_TOKENS = frozenset({"danger", "armed", "sim", "error", "crit", "warn"})

# User-editable token GROUPS: one editor swatch fans out to every dict key
# that names the same concept (bg/canvas are byte-equal aliases today;
# material/material_strong are synced to panel/canvas per the v5 pass; a
# custom "well" override flattens the subtle well-vs-sunk step — acceptable
# for a user theme). Everything NOT reachable from here (raised/field/hover/
# toplight/pressed/..., the axis rails, and every safety token) keeps its
# shipped value.
_OVERRIDE_FANOUT: dict[str, tuple[str, ...]] = {
    "accent":   ("accent",),
    "canvas":   ("canvas", "bg", "material_strong"),
    "panel":    ("panel", "material"),
    "well":     ("well", "sunk"),
    "text":     ("text",),
    "muted":    ("muted",),
    "hairline": ("hairline", "border"),
}
EDITABLE_TOKENS: tuple[str, ...] = tuple(_OVERRIDE_FANOUT)

_HEX6_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# ---------------------------------------------------------------------------
# BUILT-IN PRESETS (Kaya round 2: "ich will mehr theme presets")
#
# Ported verbatim from the v5 playground's `P` map
# (artifacts_claude/v5/src/themes.body.html) — designed and eyeball-checked
# there; nothing here is invented. They live in THIS module because it is the
# only gui/ file allowed to contain hex literals (tests/test_no_inline_hex_gui.py)
# and because tokens are style.py's job; gui/theme_editor.py is pure view.
#
# Keys are EDITABLE_TOKENS *group* names (not raw palette keys) — they fan out
# through _OVERRIDE_FANOUT exactly like a user's own picks, which is why a
# preset can never reach a safety token: `danger`/`armed`/`sim`/`error` are not
# groups, apply_theme_overrides raises on them, and sanitize/validate reject any
# preset that names one (laws 1/2/6). The safety palette is IDENTICAL in all
# five presets, by construction.
#
# "Cockpit Dark" and "Lab Light" carry NO overrides on purpose: they ARE the
# shipped themes (the ratified v5 look), so selecting them restores the app
# exactly as it ships rather than a near-copy. The playground's own glass values
# for those two are likewise not ported — the shipped default is the reference.
# `well` reproduces the playground's derivation (blend(bg, panel, 0.6)) instead
# of a hand-typed value, so the wells track their preset's canvas/panel.
def _preset_well(canvas: str, panel: str) -> str:
    return _blend(canvas, panel, 0.6)


BUILTIN_PRESETS: tuple[dict, ...] = (
    {"name": "Cockpit Dark", "mode": "dark", "glass": DEFAULT_GLASS_AMOUNT,
     "overrides": {}},
    {"name": "Graphite", "mode": "dark", "glass": 0.60, "overrides": {
        "canvas": "#0e0f11", "panel": "#17181c", "text": "#eceef1",
        "muted": "#9a9fa8", "hairline": "#26282e", "accent": "#7aa7d9",
        "well": _preset_well("#0e0f11", "#17181c"),
    }},
    {"name": "Deep Violet", "mode": "dark", "glass": 0.82, "overrides": {
        "canvas": "#0b0a14", "panel": "#151327", "text": "#eae8f5",
        "muted": "#9d98b5", "hairline": "#262239", "accent": "#8f7aff",
        "well": _preset_well("#0b0a14", "#151327"),
    }},
    {"name": "Lab Light", "mode": "light", "glass": DEFAULT_GLASS_AMOUNT,
     "overrides": {}},
    {"name": "Paper", "mode": "light", "glass": 0.55, "overrides": {
        "canvas": "#f2efe9", "panel": "#fffdf8", "text": "#1c1a15",
        "muted": "#5d5850", "hairline": "#e2ddd2", "accent": "#3e6b8f",
        "well": _preset_well("#f2efe9", "#fffdf8"),
    }},
)

# Radius S/M/L scale (theme editor "Radius" segment): (RADIUS_SM, RADIUS_MD,
# RADIUS_LG) triples. "m" is the shipped default (spec §2 "Radii 8/12/16");
# RADIUS_XS/RADIUS_PILL never change.
RADIUS_SCALES: dict[str, tuple[int, int, int]] = {
    "s": (6, 9, 12),
    "m": _BASE_RADII,
    "l": (10, 15, 20),
}

# QSettings("TCT", "TCTSetup") keys — all under theme/*.
_SETTINGS_GLASS_KEY = "theme/glass_amount"
_SETTINGS_OVERRIDES_KEY = "theme/overrides"
_SETTINGS_TYPOGRAPHY_KEY = "theme/typography"
_SETTINGS_RADIUS_KEY = "theme/radius_scale"
_SETTINGS_WINDOW_OPACITY_KEY = "theme/window_opacity"
_SETTINGS_WINDOW_BACKDROP_KEY = "theme/window_backdrop"

# Live customization state (module-level; reset via reset_theme_customization).
_glass_amount: float = DEFAULT_GLASS_AMOUNT
_window_opacity: float = DEFAULT_WINDOW_OPACITY
# Windows 11 DWM system backdrop material — see gui/backdrop.py. Preference
# state only; whether it actually renders is decided at apply time by
# backdrop.is_backdrop_supported(). "none" everywhere else in the module.
_window_backdrop: str = "none"
_overrides: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
_typography: dict = {"sans": None, "mono": None, "hinting": None, "base_px": None}
_radius_scale: str = "m"

_UNSET = object()


def _recompute_palettes() -> None:
    """Rebuild the live LIGHT/DARK dicts in place: base snapshot + user
    overrides (fanned out per _OVERRIDE_FANOUT) + re-derived dependent tokens
    (accent_strong/tint/active, hairline_strong when hairline is overridden)
    + the four glass pre-blends at the current glass amount. At the defaults
    this is byte-identical to the inline definitions (tested)."""
    g = _glass_amount
    for mode, base, live, tint_alpha in (
            ("light", _BASE_LIGHT, LIGHT, 0.10),
            ("dark", _BASE_DARK, DARK, 0.13)):
        merged = dict(base)
        ov = _overrides[mode]
        for key, value in ov.items():
            for target in _OVERRIDE_FANOUT.get(key, ()):
                merged[target] = value
        # Derived accent family — same formulas the palette dicts use inline.
        merged["accent_strong"] = _darken(merged["accent"], 0.15)
        merged["tint"] = merged["active"] = _blend(
            merged["accent"], merged["panel"], tint_alpha)
        if "hairline" in ov:
            # Approximate "strong" as a wash of text over the picked hairline
            # (only when overridden — the shipped strong values stay exact).
            merged["hairline_strong"] = merged["border_strong"] = _blend(
                merged["text"], merged["hairline"], 0.15)
        alphas = _GLASS_BLEND_ALPHAS[mode]

        def _glass(fg: str, bg: str, alpha: float) -> str:
            # 0 strength means NO blend: hand back the exact bg token string
            # (chrome literally IS panel at full opacity — not a re-rounded,
            # possibly case-differing copy of it).
            return bg if alpha <= 0.0 else _blend(fg, bg, alpha)

        merged["chrome"] = _glass(merged["raised"], merged["panel"], alphas["chrome"] * g)
        merged["strip"] = _glass(merged["sunk"], merged["panel"], alphas["strip"] * g)
        merged["edge"] = _glass("#FFFFFF", merged["hairline"], alphas["edge"] * g)
        merged["edge_shade"] = _glass("#000000", merged["hairline"], alphas["edge_shade"] * g)
        live.clear()
        live.update(merged)


def set_glass_amount(amount: float) -> float:
    """Set the material glass amount (0.0 = fully opaque surfaces, 1.0 = the
    v4 glass ceiling — see _GLASS_BLEND_ALPHAS) and recompute both palettes.
    Clamps to [0, 1]; returns the value actually set. The caller still needs
    to regenerate + reapply the QSS (gui.style.apply_theme) to repaint."""
    global _glass_amount
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = DEFAULT_GLASS_AMOUNT
    _glass_amount = max(0.0, min(1.0, amount))
    _recompute_palettes()
    return _glass_amount


def get_glass_amount() -> float:
    return _glass_amount


def set_window_opacity(value) -> float:
    """Set the real (compositor) window opacity and return the value actually
    set — CLAMPED to [MIN_WINDOW_OPACITY, MAX_WINDOW_OPACITY].

    The clamp is a safety rail, not input validation: below the floor an HV-live
    chip or an Abort button starts blending into whatever is behind the window.
    Garbage (None, "", "0.2abc") falls back to fully opaque — the safe end.
    Callers still need :func:`apply_window_opacity` to push it onto the windows.
    """
    global _window_opacity
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = DEFAULT_WINDOW_OPACITY
    if value != value:                      # NaN — no ordering, clamp by hand
        value = DEFAULT_WINDOW_OPACITY
    _window_opacity = max(MIN_WINDOW_OPACITY, min(MAX_WINDOW_OPACITY, value))
    return _window_opacity


def get_window_opacity() -> float:
    return _window_opacity


def apply_window_opacity(app=None, opacity: float | None = None) -> float:
    """Push the current window opacity onto EVERY top-level window of *app*.

    Every window inherits it, so the cockpit stays coherent: the main window,
    the Settings/Theme dialogs, and a torn-off panel (``detachable_tabs``'
    ``_DetachedWindow``, a real top-level QMainWindow) all sit at the same
    translucency instead of one floating opaque slab over a translucent shell.
    Windows created *later* pick it up at construction — see
    ``_DetachedWindow.__init__``.

    Returns the applied opacity. Safe to call with no QApplication (no-op).
    """
    from PySide6.QtWidgets import QApplication

    value = _window_opacity if opacity is None else set_window_opacity(opacity)
    app = app if app is not None else QApplication.instance()
    if app is None:
        return value
    for w in app.topLevelWidgets():
        if w.isWindow() and not _is_transient_window(w):
            w.setWindowOpacity(value)
    return value


def set_window_backdrop(kind) -> str:
    """Set the persisted backdrop-material preference and return the value
    actually set.

    Mirrors :func:`set_window_opacity`'s fail-opaque philosophy: garbage
    (``None``, ``""``, a typo, a kind name from a future/past codebase
    rename) is never trusted as-is — it falls back to ``"none"``, the safe/
    opaque end, instead of raising or reaching a half-applied state. This is
    a preference only; whether it actually renders as a real DWM material is
    decided at apply time by :func:`gui.backdrop.is_backdrop_supported` —
    this setter never touches ctypes/DWM/any window.
    """
    global _window_backdrop
    key = kind.strip().lower() if isinstance(kind, str) else ""
    _window_backdrop = key if key in backdrop.BACKDROP_KINDS else "none"
    return _window_backdrop


def get_window_backdrop() -> str:
    return _window_backdrop


def _reassert_window_palette(window) -> None:
    """Re-sync one top-level window after a backdrop reset — the C1 risk
    note fix (see :func:`apply_window_backdrop_to`).

    ``gui.backdrop.apply_backdrop(window, "none")`` (via
    ``gui/backdrop.py._clear_window_canvas``) already resets the window's
    palette with a blank ``QPalette()`` — that module stays theme-blind on
    purpose, it just undoes its own translucent-canvas prep, it does not
    know what the "right" palette is. This function re-plays that same
    blank reset (colour-wise a no-op: backdrop.py already left the window in
    this state, or never touched it at all) and then forces an immediate
    style repolish (:func:`repolish`), so a reset never has to wait for some
    unrelated event to trigger the repaint that clears a stray default-Qt-
    grey frame.

    Verified empirically (headless, offscreen) before picking this over the
    more obvious ``window.setPalette(app.palette())``: handing a widget a
    FULL palette copy sets ``Qt.WA_SetPalette`` (nonzero ``resolveMask()``)
    and, on its own, stops that widget tracking any LATER bare
    ``QApplication.setPalette()`` call — a stickier bug than the flash being
    fixed here. A blank ``QPalette()`` does not set that attribute by
    itself. The :func:`repolish` call below still ends up setting
    ``WA_SetPalette`` anyway (Qt's stylesheet engine bakes a resolved
    palette into any widget it polishes under an active app stylesheet) —
    but that is harmless in THIS app specifically, because every theme
    change goes through :func:`apply_theme`'s ``app.setStyleSheet(...)``,
    and a stylesheet change unconditionally re-polishes the whole widget
    tree regardless of ``WA_SetPalette`` (confirmed the same way: toggling
    to the other mode right after this reset still updates the window).

    MUST NOT run while a real backdrop material is applied — a live mica/
    acrylic window needs its transparent Window-role palette
    (``gui.backdrop._prepare_window_canvas``) for the DWM material to show
    through. Callers only invoke this for ``kind == "none"``.
    """
    window.setPalette(QPalette())
    repolish(window)


def apply_window_backdrop_to(window, kind: str | None = None) -> str:
    """Apply the given (or current) backdrop kind to a SINGLE top-level
    window and keep it theme-coherent.

    Used both by :func:`apply_window_backdrop`'s app-wide fan-out below and
    by callers that only ever touch one window at construction time
    (``gui.detachable_tabs._DetachedWindow``, ``tct_gui.TCTMainWindow``
    startup) — mirrors the ``set_window_opacity`` / direct
    ``setWindowOpacity`` split those callers already use for the opacity
    knob. ``gui/backdrop.py`` stays theme-blind; this is where style.py
    re-syncs the window's palette after a reset (see
    :func:`_reassert_window_palette`).
    """
    resolved = _window_backdrop if kind is None else kind
    backdrop.apply_backdrop(window, resolved)
    if resolved == "none":
        _reassert_window_palette(window)
    return resolved


def apply_window_backdrop(app=None) -> str:
    """Push the current backdrop kind onto EVERY top-level window of *app*,
    mirroring :func:`apply_window_opacity`'s fan-out (same
    ``_is_transient_window`` skip — menus/tooltips/splashes stay untouched).

    Apply-order contract: callers apply the backdrop BEFORE
    :func:`apply_window_opacity` (see ``tct_gui`` startup / ``_toggle_theme``
    and ``gui.detachable_tabs._DetachedWindow.__init__``). The two knobs stay
    functionally independent — this only fixes which one's Qt-side setup
    runs first, not a rendering guarantee for how a layered (alpha-blended)
    window interacts with a DWM backdrop material. That interaction has to be
    eyeballed on a real Win11 22H2+ display, not reasoned about in code.

    On any unsupported host (anything other than Windows 11 22H2+ running
    the real "windows" Qt platform — in particular this whole offscreen test
    suite) :func:`gui.backdrop.apply_backdrop` is a clean no-op per window, so
    this function is always safe to call.

    Windows created *later* pick up the current kind at construction — see
    :func:`apply_window_backdrop_to`. Safe to call with no QApplication
    (no-op).
    """
    from PySide6.QtWidgets import QApplication

    kind = _window_backdrop
    app = app if app is not None else QApplication.instance()
    if app is None:
        return kind
    for w in app.topLevelWidgets():
        if w.isWindow() and not _is_transient_window(w):
            apply_window_backdrop_to(w, kind)
    return kind


# Window TYPE lives as a value inside WindowType_Mask (Window=0x1, Dialog=0x3,
# Popup=0x9, ...) — those are NOT orthogonal bits, so a naive
# `flags & Qt.WindowType.Popup` truth-test misclassifies a plain QMainWindow as
# a popup (and PySide6's QFlags truthiness makes it worse). Mask and compare.
_TRANSIENT_WINDOW_TYPES = frozenset({
    int(Qt.WindowType.Popup),
    int(Qt.WindowType.ToolTip),
    int(Qt.WindowType.SplashScreen),
})


def _is_transient_window(w) -> bool:
    """Menus / tooltips / splashes are transient chrome, not windows the
    operator looks *through* — fading them is an artifact, not translucency."""
    wtype = int(w.windowFlags()) & int(Qt.WindowType.WindowType_Mask)
    return wtype in _TRANSIENT_WINDOW_TYPES


def apply_theme_overrides(overrides: dict | None, mode: str = "dark", *,
                          merge: bool = True) -> dict:
    """Validate and store user palette *overrides* for *mode*, shallow-merged
    onto the base palette BEFORE QSS generation (the live LIGHT/DARK dicts
    are recomputed in place). Keys must be EDITABLE_TOKENS group names and
    values '#rrggbb' hex strings; any SAFETY_TOKENS key raises ValueError —
    the safety palette is fixed by laws 1/2/6, with no override path.
    ``merge=False`` replaces the stored override set for the mode (the theme
    editor's Apply semantics). Returns a copy of the stored overrides."""
    key = "dark" if str(mode).lower() == "dark" else "light"
    overrides = dict(overrides or {})
    locked = sorted(k for k in overrides if str(k).lower() in SAFETY_TOKENS)
    if locked:
        raise ValueError(
            f"safety palette is fixed by laws 1/2/6 — cannot override: {locked}")
    for k, v in overrides.items():
        if k not in _OVERRIDE_FANOUT:
            raise ValueError(
                f"not an editable theme token: {k!r} (editable: {EDITABLE_TOKENS})")
        if not isinstance(v, str) or not _HEX6_RE.match(v):
            raise ValueError(
                f"override for {k!r} must be a '#rrggbb' hex string, got {v!r}")
    if merge:
        _overrides[key].update(overrides)
    else:
        _overrides[key] = dict(overrides)
    _recompute_palettes()
    return dict(_overrides[key])


def sanitize_overrides(overrides) -> dict:
    """Preset-JSON / QSettings gate: keep only EDITABLE_TOKENS keys with
    valid '#rrggbb' values; safety tokens and unknown keys are DROPPED
    silently (a hand-edited preset can never unlock the safety palette)."""
    clean: dict[str, str] = {}
    if not isinstance(overrides, dict):
        return clean
    for k, v in overrides.items():
        if k in _OVERRIDE_FANOUT and isinstance(v, str) and _HEX6_RE.match(v):
            clean[k] = v
    return clean


def theme_overrides(mode: str) -> dict:
    """Copy of the stored user overrides for *mode*."""
    return dict(_overrides["dark" if str(mode).lower() == "dark" else "light"])


def apply_typography(*, sans=_UNSET, mono=_UNSET, hinting=_UNSET,
                     base_px=_UNSET) -> None:
    """Set the user typography choices and rebind the live module globals
    (SANS_FAMILIES/SANS_FAMILY, MONO_FAMILIES/MONO_FAMILY, FONT_HINTING,
    FONT_MD). ``build_qss``/``_apply_app_font`` resolve these at call time,
    so the next apply_theme() picks them up. Pass ``None`` to reset a field
    to the shipped default; omitted fields keep their current choice. A
    chosen family is promoted to the FRONT of the shipped fallback stack
    (never replacing it — fallbacks keep working). ``base_px`` clamps to
    the shipped default +/- 2."""
    global SANS_FAMILIES, SANS_FAMILY, MONO_FAMILIES, MONO_FAMILY
    global FONT_HINTING, FONT_MD
    if sans is not _UNSET:
        _typography["sans"] = str(sans) if sans else None
    if mono is not _UNSET:
        _typography["mono"] = str(mono) if mono else None
    if hinting is not _UNSET:
        _typography["hinting"] = hinting if hinting in _HINTING_PREFS else None
    if base_px is not _UNSET:
        if base_px is None:
            _typography["base_px"] = None
        else:
            try:
                px = int(base_px)
            except (TypeError, ValueError):
                px = _BASE_FONT_MD
            _typography["base_px"] = max(_BASE_FONT_MD - 2,
                                         min(_BASE_FONT_MD + 2, px))
    chosen_sans = _typography["sans"]
    families = list(_BASE_SANS_FAMILIES)
    if chosen_sans:
        families = [chosen_sans] + [f for f in families if f != chosen_sans]
    SANS_FAMILIES = families
    SANS_FAMILY = ", ".join(f'"{f}"' for f in SANS_FAMILIES) + ", system-ui, sans-serif"
    chosen_mono = _typography["mono"]
    mono_families = list(_BASE_MONO_FAMILIES)
    if chosen_mono:
        mono_families = [chosen_mono] + [f for f in mono_families if f != chosen_mono]
    MONO_FAMILIES = mono_families
    MONO_FAMILY = ", ".join(f'"{f}"' for f in MONO_FAMILIES) + ", monospace"
    FONT_HINTING = _typography["hinting"] or _BASE_FONT_HINTING
    FONT_MD = _typography["base_px"] or _BASE_FONT_MD
    FONT["md"] = FONT_MD


def typography() -> dict:
    """Copy of the stored user typography choices (None = shipped default)."""
    return dict(_typography)


def base_typography() -> dict:
    """The shipped typography defaults (for the editor's combo population)."""
    return {"sans": list(_BASE_SANS_FAMILIES), "mono": list(_BASE_MONO_FAMILIES),
            "hinting": _BASE_FONT_HINTING, "base_px": _BASE_FONT_MD}


def apply_radius_scale(scale: str) -> str:
    """Set the corner-radius scale ("s"/"m"/"l" — see RADIUS_SCALES) and
    rebind the live RADIUS_SM/MD/LG globals + RADIUS dict. Unknown values
    fall back to "m". NOTE: modules that imported RADIUS_* BY VALUE at import
    time keep the old numbers in their per-instance inline styles until
    rebuilt — the global QSS (the dominant consumer) follows immediately."""
    global RADIUS_SM, RADIUS_MD, RADIUS_LG, _radius_scale
    key = str(scale).lower()
    if key not in RADIUS_SCALES:
        key = "m"
    _radius_scale = key
    RADIUS_SM, RADIUS_MD, RADIUS_LG = RADIUS_SCALES[key]
    RADIUS["sm"], RADIUS["md"], RADIUS["lg"] = RADIUS_SM, RADIUS_MD, RADIUS_LG
    return key


def radius_scale() -> str:
    return _radius_scale


def reset_theme_customization() -> None:
    """Restore every user-tunable theme knob (palette overrides, glass
    amount, typography, radius, window backdrop) to the shipped defaults.
    Does NOT touch QSettings — persistence stays the theme editor's
    decision. Does NOT touch any live window either (mirrors
    ``_window_opacity``) — callers that need the reset visible re-apply it
    (``apply_window_backdrop`` / ``apply_window_opacity``)."""
    global _glass_amount, _window_opacity, _window_backdrop
    _overrides["light"] = {}
    _overrides["dark"] = {}
    _glass_amount = DEFAULT_GLASS_AMOUNT
    _window_opacity = DEFAULT_WINDOW_OPACITY
    _window_backdrop = "none"
    apply_typography(sans=None, mono=None, hinting=None, base_px=None)
    apply_radius_scale("m")
    _recompute_palettes()


def _default_settings():
    from PySide6.QtCore import QSettings
    return QSettings("TCT", "TCTSetup")


def save_theme_customization(settings=None) -> None:
    """Persist the current customization under theme/* in
    QSettings("TCT", "TCTSetup") (or an injected *settings* for tests)."""
    s = settings if settings is not None else _default_settings()
    s.setValue(_SETTINGS_GLASS_KEY, float(_glass_amount))
    s.setValue(_SETTINGS_WINDOW_OPACITY_KEY, float(_window_opacity))
    s.setValue(_SETTINGS_WINDOW_BACKDROP_KEY, _window_backdrop)
    s.setValue(_SETTINGS_OVERRIDES_KEY, json.dumps(_overrides))
    s.setValue(_SETTINGS_TYPOGRAPHY_KEY, json.dumps(_typography))
    s.setValue(_SETTINGS_RADIUS_KEY, _radius_scale)
    s.sync()


def load_theme_customization(settings=None) -> None:
    """Load + apply persisted theme/* customization — called at startup right
    where the saved dark/light choice is loaded (main.py before the first
    apply_theme; tct_gui.TCTMainWindow.__init__ for direct construction).
    Every field parses defensively and overrides pass sanitize_overrides, so
    a hand-edited registry can neither unlock the safety palette nor wedge
    startup."""
    global _glass_amount, _window_opacity, _window_backdrop
    s = settings if settings is not None else _default_settings()
    # A load DEFINES the customization state; it never inherits leftovers from
    # whatever was loaded/applied before. An ABSENT key means "shipped default",
    # not "keep the current value" — otherwise a second load (settings-store
    # swap, a test's throwaway .ini) silently carries the previous glass amount
    # / radius scale forward, which is state persisting across loads.
    raw_glass = s.value(_SETTINGS_GLASS_KEY, None)
    if raw_glass is None:
        _glass_amount = DEFAULT_GLASS_AMOUNT
    else:
        try:
            _glass_amount = max(0.0, min(1.0, float(raw_glass)))
        except (TypeError, ValueError):
            _glass_amount = DEFAULT_GLASS_AMOUNT
    # Window opacity goes through set_window_opacity, so the 0.80 SAFETY FLOOR
    # is enforced on the persisted value too: a hand-edited registry entry of
    # 0.2 is clamped to 0.80, never obeyed. Absent -> fully opaque.
    raw_opacity = s.value(_SETTINGS_WINDOW_OPACITY_KEY, None)
    if raw_opacity is None:
        _window_opacity = DEFAULT_WINDOW_OPACITY
    else:
        set_window_opacity(raw_opacity)
    # Backdrop kind goes through set_window_backdrop, so garbage/an unknown
    # kind (a hand-edited registry, a kind retired in a future rename) falls
    # back to "none" — fail-opaque, same philosophy as the opacity clamp
    # above. Absent -> "none" (shipped default, nothing changes visually).
    raw_backdrop = s.value(_SETTINGS_WINDOW_BACKDROP_KEY, None)
    if raw_backdrop is None:
        _window_backdrop = "none"
    else:
        set_window_backdrop(raw_backdrop)
    try:
        blob = json.loads(str(s.value(_SETTINGS_OVERRIDES_KEY, "") or "{}"))
    except (TypeError, ValueError):
        blob = {}
    if not isinstance(blob, dict):
        blob = {}
    for mode in ("light", "dark"):
        _overrides[mode] = sanitize_overrides(blob.get(mode))
    try:
        typo = json.loads(str(s.value(_SETTINGS_TYPOGRAPHY_KEY, "") or "{}"))
    except (TypeError, ValueError):
        typo = {}
    if not isinstance(typo, dict):
        typo = {}
    # Unconditional: a missing/garbage blob resets typography to the shipped
    # defaults (apply_typography(None, ...)) rather than leaving the previous
    # choice bound to the live SANS_FAMILY/FONT_MD globals.
    apply_typography(
        sans=typo.get("sans") or None,
        mono=typo.get("mono") or None,
        hinting=typo.get("hinting") or None,
        base_px=typo.get("base_px") or None,
    )
    # Default is the shipped "m" scale, NOT the currently-loaded one.
    apply_radius_scale(str(s.value(_SETTINGS_RADIUS_KEY, "m")))
    _recompute_palettes()


def _apply_pyqtgraph(p: dict) -> None:
    """Set pyqtgraph's global canvas defaults so every plot built afterwards
    inherits the dark "instrument screen" colours (PLOT_BG/PLOT_FG).

    NOTE: this intentionally does *not* walk ``QApplication.allWidgets()`` to
    restyle already-live plots. That walk was a native crash vector — after
    many widgets have been created/destroyed in one process (windows closed,
    panels detached, deferred deletions not yet flushed), ``allWidgets()`` can
    enumerate wrappers whose C++ QWidget is mid/post-destruction, and touching
    (or even materialising) such a corpse access-violates natively — an AV the
    surrounding ``try/except`` cannot catch. It also silently clobbered plots
    that deliberately opt out of PLOT_BG (e.g. ScanMapWindow's transparent
    axis overlay). Since PLOT_BG/PLOT_FG are *fixed in both themes*, the walk
    never did any theme-dependent work: each plot instead owns its own canvas
    (``pg.PlotWidget(background=PLOT_BG)`` + ``showGrid(...)`` at construction),
    and per-theme accents are re-resolved by each panel's ``refresh_theme``.
    This keeps ``apply_theme`` safe to call at any time (e.g. the settings
    toggle) even with closed / half-destroyed windows still around."""
    try:
        import pyqtgraph as pg
    except Exception:
        return
    pg.setConfigOption("background", PLOT_BG)   # default for plots built later
    pg.setConfigOption("foreground", PLOT_FG)


def apply_theme(app, mode: str = "light") -> str:
    """Apply the global stylesheet for *mode* ('light'|'dark'). Returns the mode.

    Also installs the application-default ``QFont`` (family stack, px size,
    hinting — see ``_apply_app_font``): the QSS below only reaches QWidgets,
    while the QML chrome and unstyled text inherit the app font. Set BEFORE
    the stylesheet so the one global repolish QSS application triggers already
    sees the final font (no second repolish, no flash).

    Also sets the app QPalette's canvas roles (``_apply_app_palette``) — the
    backstop for a widget shown as its own top-level window, now that the QSS
    canvas rule names shells instead of blanket-painting every QWidget."""
    palette = DARK if str(mode).lower() == "dark" else LIGHT
    _apply_app_font(app)
    _apply_app_palette(app, palette)
    app.setStyleSheet(build_qss(palette))
    _apply_pyqtgraph(palette)
    return "dark" if palette is DARK else "light"
