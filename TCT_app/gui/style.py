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

# Corner-radius scale (px). Cards stay at <= 8 px; pills are the only
# intentionally larger shape.
RADIUS_XS = 4     # menus / tooltips
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 8
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

MONO_FAMILY = '"Consolas", "Cascadia Mono", "Cascadia Code", "Courier New", monospace'

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
    font-family: "Segoe UI Variable", "Segoe UI", "Inter var", "Inter", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
    font-size: {FONT_MD}px;
    color: {p['text']};
}}

QMainWindow, QDialog, QWidget {{ background: {p['bg']}; }}
QWidget#mainShell {{ background: {p['bg']}; }}

QScrollArea#ribbonScroll {{ background: transparent; border: none; }}
QFrame#systemRibbon {{
    background: {p['material']}; border: 1px solid {p['hairline']};
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
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_SM - 2}px {SPACE_MD}px;
    selection-background-color: {p['accent']};
    selection-color: {p['on_accent']};
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

/* Buttons — padding/weight match the v5 artifact's `.btn` (7/16, medium
   weight) so a button label reads as a command rather than body text,
   without shouting (apple_style_ui_audit.md: "medium labels"). */
QPushButton {{
    background: {p['field']};
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_SM - 1}px {SPACE_LG}px;
    font-weight: 500;
}}
QPushButton:hover {{ border-color: {p['border_strong']}; background: {p['hover']}; }}
QPushButton:pressed {{ background: {p['active']}; }}
QPushButton:focus {{ outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px; }}
QPushButton:disabled {{
    color: {p['faint']}; background: {p['disabled_bg']}; border-color: transparent;
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

/* Tabs (also the DetachableTabWidget) — a quiet card tab; the active page is
   a pill with accent-tinted material, matching the v5 polish artifact. */
QTabWidget::pane {{
    border: none; top: -1px; background: {p['bg']};
}}
QTabBar::tab {{
    background: transparent; padding: {SPACE_SM - 2}px {SPACE_LG - 3}px; margin-right: 4px;
    border: 1px solid transparent; border-radius: {RADIUS_MD}px;
    color: {p['muted']}; font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {p['tint']}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.22)};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: {p['field']}; color: {p['text']}; border-color: {p['hairline']};
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
    border: 1px solid {p['hairline']}; border-radius: {RADIUS_SM}px;
    font-weight: 600;
}}

QCheckBox {{ spacing: {SPACE_SM}px; }}
QCheckBox:focus, QRadioButton:focus {{
    outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px;
}}
QScrollArea {{ border: none; background: {p['bg']}; }}

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

/* Progress bars (IV/V-scan sweeps) */
QProgressBar {{
    background: {p['disabled_bg']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_SM}px; text-align: center; color: {p['text']};
    min-height: 16px;
}}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: {RADIUS_SM - 1}px; margin: 1px; }}

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
    background: {PLOT_BG}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_MD}px;
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
QFrame#readoutCell {{
    background: {p['raised']}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_MD}px;
}}
QLabel#readoutCellTitle {{
    color: {p['faint']}; font-family: {MONO_FAMILY};
    font-size: {FONT_METRIC_LABEL_PX}px; font-weight: {WEIGHT_METRIC_LABEL};
    letter-spacing: {TRACKING_METRIC_LABEL_PX}px;
}}
QLabel#readoutCellValue {{
    color: {p['text']};
    font-family: {MONO_FAMILY};
    font-size: {FONT_VALUE_PX}px; font-weight: {WEIGHT_VALUE};
    letter-spacing: 0;
}}
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
    color: {p['muted']}; font-size: {FONT_XS}px; font-weight: {WEIGHT_BODY};
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
    background: {p['field']}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_LG}px;
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

/* Segmented control — exclusive preset buttons (e.g. jog step size) styled
   as one pill-shaped group with a clear selected segment. */
QFrame#segmented {{
    background: {p['field']}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_MD}px;
}}
QPushButton#segBtn {{
    background: transparent; border: none; border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS + 1}px {SPACE_SM + 2}px; color: {p['muted']}; font-weight: 600;
}}
QPushButton#segBtn:hover:!checked {{ background: {p['hover']}; color: {p['text']}; }}
QPushButton#segBtn:checked {{ background: {p['accent']}; color: {p['on_accent']}; }}
QPushButton#segBtn:disabled {{ color: {p['muted']}; background: transparent; }}
QPushButton#segBtn:focus {{ outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px; }}

/* Card wrapper matching QGroupBox's look, for non-groupbox panes that must
   sit visually level with group boxes (e.g. a live view beside a controls
   column). */
QFrame#cardPane {{
    background: {p['panel']}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_MD}px;
}}

/* Channel card — a cardPane variant used per scope channel.  The panel adds an
   inline coloured left border per channel; this is the shared base look. */
QFrame#channelCard {{
    background: {p['panel']}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_SM}px;
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
    font-size: {FONT_XS}px; font-weight: 700;
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
    font-size: {FONT_XS}px; font-weight: 700; color: {p['text']};
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
    """Apply the global stylesheet for *mode* ('light'|'dark'). Returns the mode."""
    palette = DARK if str(mode).lower() == "dark" else LIGHT
    app.setStyleSheet(build_qss(palette))
    _apply_pyqtgraph(palette)
    return "dark" if palette is DARK else "light"
