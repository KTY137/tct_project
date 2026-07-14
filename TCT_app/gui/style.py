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
import logging
import re
import weakref
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPalette

from gui import backdrop

logger = logging.getLogger(__name__)

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
# inputs / chips-adjacent small shapes; md = tiles / small nested surfaces;
# lg = large clusters / hero shells (NOT the card radius — see RADIUS_XL
# below, added for the v6 pass, before repointing anything at RADIUS_LG:
# it is already spoken for by QFrame#controlCluster, a "large cluster",
# per this very scale). xs (4) survives only for sub-element highlights
# (menu items, tooltips) that have no artifact counterpart; pill is the one
# intentionally larger shape.
RADIUS_XS = 4     # menu-item highlights / tooltips (sub-element only)
RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16
# v6 "Glass" material pass (Kaya-ratified A/B artifact,
# artifacts_claude/tct_bias_glass_ab.html): the artifact's own card radius
# moves 16 -> 20px. RADIUS_LG (16) is already consumed by a non-card
# surface (QFrame#controlCluster, "large clusters / hero shells" above) —
# reassigning it globally would silently resize that unrelated cluster too,
# so this is a NEW, dedicated step instead, wired only into the actual
# card/panel QSS rules (QGroupBox, QFrame#cardPane) below. Deliberately NOT
# part of the theme-editor's RADIUS_SCALES s/m/l density preset (that scale
# only ever covered sm/md/lg) — a fixed constant, consistent with how
# RADIUS_XS/RADIUS_PILL already sit outside that preset system too.
RADIUS_XL = 20
RADIUS_PILL = 999
RADIUS = {"xs": RADIUS_XS, "sm": RADIUS_SM, "md": RADIUS_MD,
          "lg": RADIUS_LG, "xl": RADIUS_XL, "pill": RADIUS_PILL}

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

FONT_METRIC_LABEL_PX = 11          # tiny tracked mono uppercase "instrument
WEIGHT_METRIC_LABEL = 600          # engraving" label (MetricTile/ReadoutCell
TRACKING_METRIC_LABEL_EM = 0.08    # title, chip text) — tracking is a MAXIMUM
TRACKING_METRIC_LABEL_PX = 0       # (<=.08em); Codex S1 audit (2026-07-13,
                                    # docs/design/codex_style_audit_20260713.md
                                    # item 1): 10px/1px tracked read as
                                    # over-engraved when the role repeats
                                    # across a whole panel; 11px/0px keeps the
                                    # tracked-mono-uppercase identity without
                                    # the etched look.

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
# WCAG pass (2026-07-14): the v5 light accent (#2A6FE0) is the ink of every
# outline button (Connect, "secondary") and of the info/busy chip, whose fill is
# an accent WASH — ink on a tint of itself. That pair measured 4.16:1, and the
# plain-surface pairs sat on the line at 4.51. Darkened by the smallest amount
# that lifts the whole accent family clear (tint 4.58, field 5.02, white-on-
# accent 5.25); hue preserved, and the DARK accent — the dominant theme — is
# untouched. Unlike the safety tokens this one stays user-overridable.
_ACCENT_LIGHT_V5 = "#2A6FE0"
ACCENT_LIGHT = _darken(_ACCENT_LIGHT_V5, 0.10)          # #2563c9
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

# ---------------------------------------------------------------------------
# LIGHT semantic accents — WCAG-AA CONTRAST PASS (2026-07-14).
#
# The v5 artifact's light hexes (``*_V5`` below, kept as the named source they
# are derived FROM — not deleted, so the derivation stays auditable) were
# measured against the surfaces they are actually painted on and FAILED WCAG AA
# (4.5:1) as text, systemically, and two of them are SAFETY tokens:
#
#     sim   #0C9FB0   3.18 on panel / 2.66 on canvas   (law 6: "SIMULATED")
#     warn  #B26F00   4.07 / 3.40                      (law 5: motion/homing)
#     crit  #DE434B   4.19 / 3.50                      (danger ink)
#     good  #128A63   4.34                             (near-miss)
#
# A status colour an operator cannot read is not a status colour. Each token is
# now DERIVED from its v5 hex with the module's own ``_darken`` primitive (house
# rule: derived, not sprinkled — a hand-picked "looks about right" hex is exactly
# how a palette drifts out of compliance again), at the SMALLEST amount that
# clears 4.5:1 on every surface it actually lands on, with margin.
#
# ``_darken`` scales R/G/B by one factor, so the HUE IS PRESERVED EXACTLY —
# this is a contrast fix, not a re-theme: amber stays amber, cyan stays cyan
# (sim's 186° vs good's 160° hue separation is byte-for-byte what it was, so
# law 6's "sim never borrows green" is untouched).
#
# Guard: tests/test_palette_contrast.py measures every pair, both themes.
# ---------------------------------------------------------------------------
_OK_GREEN_LIGHT_V5 = "#128A63"
_WARN_AMBER_LIGHT_V5 = "#B26F00"
_WARN_RED_LIGHT_V5 = "#DE434B"

OK_GREEN_LIGHT = _darken(_OK_GREEN_LIGHT_V5, 0.14)      # #0f7657 — 5.6 panel / 4.7 canvas
WARN_AMBER_LIGHT = _darken(_WARN_AMBER_LIGHT_V5, 0.18)  # #915b00 — 5.7 / 4.7
WARN_RED_LIGHT = _darken(_WARN_RED_LIGHT_V5, 0.22)      # #ad343a — 6.3 / 5.3

# NOTE for the reader of docs/design/glass_council/baldr.md: that note proposes
# ``crit_ink_light = #C22A33``, described as "WARN_RED_LIGHT darkened ~22%".
# It is NOT what ``_darken(WARN_RED_LIGHT, 0.22)`` produces — #C22A33's channel
# ratios are not uniform, so that hex was HSL-derived or hand-picked. The
# codebase's own primitive yields #AD343A, which measures BETTER (6.31/5.27/6.31
# vs 5.72/4.78/5.72). The derived value wins; the doc's arithmetic claim was the
# thing that was wrong, not the direction.

# Canonical spec names (§2) as their own constants/aliases, for new call
# sites (and the dict keys below) that want to say what they mean instead of
# reaching for the legacy OK_GREEN/WARN_AMBER/WARN_RED names.
GOOD_DARK, GOOD_LIGHT = OK_GREEN, OK_GREEN_LIGHT
ARMED_DARK, ARMED_LIGHT = WARN_AMBER, WARN_AMBER_LIGHT
DANGER_DARK, DANGER_LIGHT = WARN_RED, WARN_RED_LIGHT

# ---------------------------------------------------------------------------
# HAZARD FILL + ITS LABEL — the pair nobody had ever measured.
#
# ``crit`` has two incompatible jobs: it is the INK of a danger state (it must
# be bright to read on a DARK panel) and it was ALSO the FILL of the HV / scan-
# abort button, under a hardcoded ``color: white`` label. Those pull in opposite
# directions, and in the dark theme the fill won: white on #FF5A61 measures
# **3.05:1** — the Abort button's own label, below even the 3:1 non-text floor.
# (Light was 4.19 — also failing.) Nobody checked it because the QSS said the
# quiet word "white" instead of naming a token.
#
# So the two jobs are now two tokens. ``crit``/``danger`` stays the INK (bright
# in dark, darkened in light, above); ``danger_fill`` is the button BODY — dark
# enough in BOTH themes to carry a white label — and ``on_danger`` is that
# label, a real token instead of a literal. Both are LOCKED (SAFETY_TOKENS).
# Hover/pressed derive by darkening the fill further, so the label's contrast
# only ever IMPROVES as the button is pressed (monotone by construction — a
# later tweak to the hover amount cannot silently break the label).
# The dark fill is a NARROW window, and worth spelling out: it must be dark
# enough for a white label (>=4.5:1) yet light enough that the button BODY is
# still identifiable against the dark cluster surface it sits on (>=3:1, WCAG
# 1.4.11). That leaves relative luminance in roughly [0.163, 0.185] — 0.22 lands
# at white 4.80 / body 3.19, the only amount with margin on BOTH sides.
DANGER_FILL_LIGHT = WARN_RED_LIGHT                    # #ad343a — white 6.31, body 6.03
DANGER_FILL_DARK = _darken(WARN_RED, 0.22)            # #c6464b — white 4.80, body 3.19
ON_DANGER = "#FFFFFF"                                 # both themes: one danger language

# The motion command class (law 5) fills with ``armed`` while pressed, so it
# needs its own label ink: light "armed" is a dark ochre (white reads on it),
# dark "armed" is a bright amber (only a near-black ink reads on it — white
# would be 1.72:1). Derived from the armed token itself, so the pair tracks it.
ON_ARMED_LIGHT = "#FFFFFF"                            # on #915b00 — 5.68:1
ON_ARMED_DARK = _darken(WARN_AMBER, 0.86)             # on #FFB84D — 11.9:1

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
# WCAG pass (2026-07-14): the light sim cyan was the WORST token in the palette
# — 3.18:1 on a panel, 2.66:1 on the canvas, i.e. below even the 3:1 non-text
# floor for the StatusLamp dot. "This data is SIMULATED" is a law-6 safety
# claim; it has to be readable. Derived (see the LIGHT semantic block above);
# the hue is preserved exactly, so it is the same cyan, just legible.
_SIM_CYAN_LIGHT_V5 = "#0C9FB0"
SIM_PURPLE_LIGHT = _darken(_SIM_CYAN_LIGHT_V5, 0.28)    # #086f7b — 5.6 / 4.7
SIM_CYAN_DARK, SIM_CYAN_LIGHT = SIM_PURPLE, SIM_PURPLE_LIGHT
ERROR_ORANGE = "#ff8a1f"
_ERROR_ORANGE_LIGHT_V5 = "#d96c00"
ERROR_ORANGE_LIGHT = _darken(_ERROR_ORANGE_LIGHT_V5, 0.28)   # #9c4d00 — 6.0 / 5.1

# General amber token (distinct from the warn status colour): matches the
# bias axis-rail hue so a "bias" accent is amber everywhere. Unchanged by the
# v5 token pass — axis-rail semantics are D1 (Planner) territory.
AMBER_LIGHT = "#C67F14"
AMBER_DARK = "#E8A33D"

# ---------------------------------------------------------------------------
# v6 "Glass" material pass — Kaya-ratified A/B artifact side B
# (artifacts_claude/tct_bias_glass_ab.html's ``.skin-glass`` block; side A in
# that file is byte-identical to the pre-v6 DARK tokens below, side B is the
# target). QWidgets-honest pre-blend only: the ratified Prometheus finding is
# that real MultiEffect/ShaderEffect backdrop-blur does not render on the
# software/RDP path, so "glass" here means ``_blend`` colour-mix against the
# real canvas, never translucency/QGraphicsEffect.
#
# Two artifact recipes, applied as literal ``_blend`` foregrounds (DARK
# only — the artifact is dark-committed by design, "Einseitig dunkel mit
# Absicht"; LIGHT has no artifact literal to borrow, see below):
#   --card-bg rgba(16,23,36,0.42)  -> panel/material (the "card" surface)
#   --well-bg rgba(4,7,12,0.55)    -> well/sunk/pressed/disabled_bg (deeper
#     recess; well/sunk COLLAPSE onto one value here, matching the
#     pre-existing theme-editor override fanout
#     ``_OVERRIDE_FANOUT["well"] = ("well", "sunk")`` further down this file
#     — a user override already treats them as one concept, so the shipped
#     v6 default does too).
#
# "raised" is deliberately left UNCHANGED: the artifact page never exercises
# a ``--raised``-keyed element (only .card/.chip/.tile/.trough/.spark/.dwell
# — the last four key off --chip-bg/--well-bg, not --raised), so moving it
# would be an invented number, not a translated one. Leaving it in place also
# widens the panel<->raised gap as panel recedes toward canvas — a
# legitimate side effect in the artifact's own spirit ("cards recede toward
# the canvas; in-card controls read more distinctly raised"). "chrome"/
# "strip" need no separate formula change: both are already DERIVED from
# raised/panel/sunk (see the inline definitions below and
# ``_recompute_palettes``), so they inherit the new panel/well values
# automatically when recomputed with the SAME literal args
# ``_recompute_palettes`` would use — keeping
# ``test_recompute_at_defaults_is_byte_identical`` (tests/test_theme_editor.py)
# green. "tint"/"active" (accent-over-panel washes) are likewise re-pointed
# at the new panel value below for the same reason: ``_recompute_palettes``
# always derives them from the LIVE "panel" key, so the inline literal has
# to track it or the byte-identical-at-defaults guarantee breaks.
_GLASS_CARD_ALPHA = 0.42
_GLASS_WELL_ALPHA = 0.55
_GLASS_CARD_FG_DARK = "#101724"   # artifact --card-bg fg rgb(16,23,36), verbatim
_GLASS_WELL_FG_DARK = "#04070C"   # artifact --well-bg fg rgb(4,7,12), verbatim
_DARK_PANEL_V6 = _blend(_GLASS_CARD_FG_DARK, "#0A0D13", _GLASS_CARD_ALPHA)
_DARK_WELL_V6 = _blend(_GLASS_WELL_FG_DARK, "#0A0D13", _GLASS_WELL_ALPHA)

# LIGHT has no artifact literal (dark-committed reference), and — unlike
# dark — cannot reuse the SAME 0.42 card-alpha grammar on its own panel: dark
# had real headroom between canvas and raised for a 0.42 blend to land
# cleanly in between; light's panel is ALREADY the brightness ceiling (pure
# white), only 7-8 hex units above "raised" (#F8FAFD), so ANY blend toward
# the darker canvas that reads as a visible step pulls panel BELOW raised —
# inverting the card/control elevation relationship (cards would read
# darker than the buttons/tiles sitting on them). Verified empirically: the
# 0.42 alpha needs >= ~0.83 just to stay non-inverted, at which point the
# "material" change is imperceptible anyway. So light panel/material get NO
# blend (stay pure white) — light's v6 identity comes through the tokens
# that DO have real headroom: well/sunk (a much gentler 0.08 ink wash, not
# dark's 0.55 — full-strength blending toward black reads muddy on a light
# surface), chip (below), and specular/edge (bumped separately above) —
# "brighter toplight, softer hairline", not "as deep/dark as dark's card".
_LIGHT_WELL_ALPHA = 0.08
_LIGHT_PANEL_V6 = "#FFFFFF"
_LIGHT_WELL_V6 = _blend("#000000", "#E6EBF3", _LIGHT_WELL_ALPHA)

LIGHT = {
    "accent": ACCENT_LIGHT, "accent_strong": ACCENT_LIGHT_STRONG,
    "amber": AMBER_LIGHT,
    "good": OK_GREEN_LIGHT, "warn": WARN_AMBER_LIGHT, "crit": WARN_RED_LIGHT,
    "sim": SIM_PURPLE_LIGHT, "error": ERROR_ORANGE_LIGHT,
    # Canonical spec names (§2) — same values as good/warn/crit/sim above,
    # added so new code can read/write the name the design contract actually
    # uses instead of the legacy good/warn/crit vocabulary.
    "danger": DANGER_LIGHT, "armed": ARMED_LIGHT,
    # Hazard FILL + its label ink (see the DANGER_FILL_* block above): a filled
    # danger/armed control is a different job from the danger INK, and conflating
    # them is what put a 3.05:1 label on the dark theme's Abort button.
    "danger_fill": DANGER_FILL_LIGHT, "on_danger": ON_DANGER,
    "on_armed": ON_ARMED_LIGHT,
    # Codex S1 audit (2026-07-13) item 2: canvas nudged one step darker so
    # panel/raised/well read as a real material ladder instead of a flat pale
    # grey stack; bg/material_strong stay byte-synced to canvas (pre-existing
    # alias convention — see their own comments).
    "canvas": "#E6EBF3", "bg": "#E6EBF3",
    # material/material_strong: toolbar/menu/status-bar chrome. Synced to
    # panel/canvas (v5) rather than a third hand-picked tone, so the ribbon
    # reads as the SAME surface ladder as every card instead of a separately
    # drifting grey.
    # v6 glass pass: material/panel now read the pre-blended _LIGHT_PANEL_V6
    # (see the module comment above LIGHT) instead of pure white — the
    # "card" surface loses its flat paper-white ceiling and picks up a
    # faint canvas-tinted glass reveal.
    "material": _LIGHT_PANEL_V6, "material_strong": "#E6EBF3",
    "panel": _LIGHT_PANEL_V6,
    # border/border_strong: kept as their own keys for existing call sites,
    # synced 1:1 to hairline/hairline_strong (the two concepts were already
    # near-identical pre-v5; DARK even had them byte-equal).
    "border": "#D9DFEA", "border_strong": "#BFC9DA",
    "hairline": "#D9DFEA", "hairline_strong": "#BFC9DA",
    # v6 glass pass: 0.85 -> 0.92 — a proportionate light-theme equivalent of
    # the dark specular bump (see DARK["specular"] below), reasoned rather
    # than copied: light's highlight was already near its practical ceiling
    # (a hairline this close to white barely has room to brighten further
    # without flattening into a solid opaque line), so the same "brighter
    # toplight" direction gets a much smaller absolute step than dark's.
    "specular": "rgba(255, 255, 255, 0.92)",
    "toplight": "#F8FAFD",
    # ── INK LADDER ────────────────────────────────────────────────────────
    # text  — body/value ink.
    # muted — THE quiet-text ink: captions, chip labels, group titles, table
    #         headers, stale readouts. Certified for text on every surface in
    #         both themes (worst opaque pair 4.64, worst GLASS pair 4.91 —
    #         Baldr's scrim floor, docs/design/glass_council/baldr.md §1.2).
    # faint — RETIRED FOR TEXT (2026-07-14 WCAG pass). It measures 2.73:1 on a
    #         panel and 2.28:1 on the canvas — below even the 3:1 non-text
    #         floor — and there is NO fix: a third grey that clears 4.5:1 in
    #         light mode necessarily collapses onto `muted` (the arithmetic is
    #         in tests/test_palette_contrast.py). So the token survives ONLY
    #         for ink that WCAG 1.4.3 explicitly exempts — the text of an
    #         INACTIVE (disabled) control — and for non-text decoration (the
    #         jog pad's decorative crosshair). Caption hierarchy is carried by
    #         size/weight/case instead of by contrast we cannot afford.
    #         Guard: test_faint_is_never_used_as_text_ink_in_the_qss.
    "text": "#131A28", "muted": "#525D72", "faint": "#949DB0",
    "on_accent": "#ffffff",
    # tint/active: accent-tinted wash, blended (see ``_blend``) at the
    # spec's "--accent-soft" alpha (0.10 light / 0.13 dark — see DARK below)
    # against "panel" instead of a separately hand-picked hex that could
    # drift from "accent" — and, unlike a raw ``_rgba()`` string, still a
    # plain hex ``gui/qml_theme.py``'s ``Theme.tint`` QColor property can
    # parse directly (see ``_blend``'s docstring).
    "tint": _blend(ACCENT_LIGHT, _LIGHT_PANEL_V6, 0.10),
    "active": _blend(ACCENT_LIGHT, _LIGHT_PANEL_V6, 0.10),
    # field: v5 evidence (tct_cockpit_design_v4_final.html's `.btn` rule) —
    # a DEFAULT BUTTON/CHIP surface is "panel-2" (raised), not a sunken
    # input well; that raised tone is what "field" already meant here
    # (QPushButton/QToolButton/QComboBox/statusChip all key off it). Genuine
    # input wells (QLineEdit/QSpinBox/...) are repointed to "well" directly
    # at their own QSS rule below instead of overloading this token.
    "field": "#F8FAFD",
    # pressed/disabled_bg: a control being pushed in / greyed out both read
    # as "recessed" — the spec's "sunk" surface, rather than two more
    # one-off hand-picked tones. v6: tracks the new _LIGHT_WELL_V6 (below).
    "pressed": _LIGHT_WELL_V6, "disabled_bg": _LIGHT_WELL_V6,
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
    # Codex S1 audit item 2: raised (+its panel_2/field/hover/toplight/chrome
    # aliases, kept byte-synced by convention) and well nudged for material
    # contrast against the darker canvas above.
    "panel_2": "#F8FAFD", "raised": "#F8FAFD", "panel_3": "#eef0f4",
    # v6 glass pass: well/sunk COLLAPSE onto the single deeper _LIGHT_WELL_V6
    # (see the module comment above LIGHT) — matches the existing
    # theme-editor override fanout, which already treats well/sunk as one
    # concept.
    "sunk": _LIGHT_WELL_V6, "well": _LIGHT_WELL_V6,
    "hover": "#F8FAFD",
    # chip: the artifact's ``--chip-bg`` glass grammar (status pill resting
    # surface) — a translucency-EQUIVALENT wash, not a copy of "raised": a
    # low-alpha ink blend over the new v6 "panel" so the chip reads as a
    # touch recessed against the card instead of sharing panel's own tone.
    # Same magnitude as DARK's 0.065 white-over-panel blend (see below),
    # mirrored to black since light chips read as a soft shadow, not a
    # highlight, against a bright card.
    "chip": _blend("#000000", _LIGHT_PANEL_V6, 0.06),
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
    # chrome/strip: unchanged FORMULA (raised/well blended over panel at the
    # same 0.74/0.55 ratios) but now resolve against the new v6 panel/well
    # values above — the exact args ``_recompute_palettes`` would use at
    # defaults, so the byte-identical-at-defaults guarantee keeps holding.
    "chrome": _blend("#F8FAFD", _LIGHT_PANEL_V6, 0.74),
    "strip": _blend(_LIGHT_WELL_V6, _LIGHT_PANEL_V6, 0.55),
    # edge: 0.85 -> 0.92, unified with the specular bump above (both
    # approximate the SAME artifact "inset highlight" cue, just via two
    # rendering paths — QSS border-top-color here, a QML rectangle for
    # specular — so they now share one number instead of two that happened
    # to already coincide before this pass).
    "edge": _blend("#FFFFFF", "#D9DFEA", 0.92),
    "edge_shade": _blend("#000000", "#D9DFEA", 0.16),
    # Plot chrome tokens (grid/overlay) — kept identical in both dicts on
    # purpose, same idiom as good/warn/crit above: the plot canvas itself
    # (PLOT_BG/PLOT_FG, below) is a fixed dark "instrument screen" in BOTH
    # themes, so its grid/overlay accents don't repaint on a theme switch
    # either. Present in both dicts so FigureCard/panels can resolve them
    # via palette(mode) without a fixed-vs-per-theme special case.
    "plot_grid": None, "plot_overlay": None, "plot_accent": None,
}

DARK = {
    "accent": ACCENT_DARK, "accent_strong": ACCENT_DARK_STRONG,
    "amber": AMBER_DARK,
    "good": OK_GREEN, "warn": WARN_AMBER, "crit": WARN_RED,
    "sim": SIM_PURPLE, "error": ERROR_ORANGE,
    "danger": DANGER_DARK, "armed": ARMED_DARK,
    # See LIGHT. The dark theme is where the danger-button label was WORST
    # (white on the bright #FF5A61 fill = 3.05:1), so the fill darkens here
    # while the danger INK stays bright for chips/lamps/hero values.
    "danger_fill": DANGER_FILL_DARK, "on_danger": ON_DANGER,
    "on_armed": ON_ARMED_DARK,
    "canvas": "#0A0D13", "bg": "#0A0D13",
    # v6 glass pass: material/panel now read the pre-blended _DARK_PANEL_V6
    # (see the module comment above LIGHT) — the artifact's own
    # ``--card-bg:rgba(16,23,36,0.42)`` composited over the real canvas hex
    # instead of the flat opaque #121824 slate tone.
    "material": _DARK_PANEL_V6, "material_strong": "#0A0D13",
    "panel": _DARK_PANEL_V6,
    # Codex S1 audit item 2: dark hairline/border nudged lighter for material
    # separation against panel; hairline_strong unchanged.
    "border": "#27344A", "border_strong": "#334159",
    "hairline": "#27344A", "hairline_strong": "#334159",
    # v6 glass pass: 0.045 -> 0.14 — the artifact's own card-shadow inset
    # value (``0 1px 0 rgba(255,255,255,0.14) inset``), applied verbatim.
    "specular": "rgba(255, 255, 255, 0.14)",
    "toplight": "#1B253A",
    # See the INK LADDER comment in LIGHT. `faint` is retired for text here too
    # — 3.23:1 on a panel, and only 2.61 on `raised`, the surface the metric
    # tiles actually use.
    "text": "#E9EDF5", "muted": "#98A1B5", "faint": "#5B657A",
    "on_accent": "#04222c",
    "tint": _blend(ACCENT_DARK, _DARK_PANEL_V6, 0.13),
    "active": _blend(ACCENT_DARK, _DARK_PANEL_V6, 0.13),
    "field": "#1B253A",
    # v6 glass pass: tracks the new _DARK_WELL_V6 (below) — see the module
    # comment above LIGHT for the artifact's --well-bg recipe.
    "pressed": _DARK_WELL_V6, "disabled_bg": _DARK_WELL_V6,
    # See the matching comments in LIGHT above. Codex S1 audit item 2: raised
    # (+aliases) and well nudged for material contrast against panel/canvas.
    # v6: "raised" is intentionally UNCHANGED (see the module comment above
    # LIGHT — the artifact never exercises a --raised-keyed element); well/
    # sunk collapse onto the single deeper _DARK_WELL_V6.
    "panel_2": "#1B253A", "raised": "#1B253A", "panel_3": "#2b2b31",
    "sunk": _DARK_WELL_V6, "well": _DARK_WELL_V6,
    "hover": "#1B253A",
    # chip: the artifact's ``--chip-bg`` glass grammar (status pill resting
    # surface) — a translucency-equivalent wash: white at the artifact's own
    # 0.065 alpha over the new v6 "panel" (not "raised"/"field" — chip reads
    # as its own, slightly-lifted resting surface, distinct from a button).
    "chip": _blend("#FFFFFF", _DARK_PANEL_V6, 0.065),
    # Round-2 material tokens — see the matching comments in LIGHT above.
    # chrome/strip: unchanged FORMULA (raised/well blended over panel at the
    # same 0.74/0.55 ratios) but now resolve against the new v6 panel/well
    # values above — the exact args ``_recompute_palettes`` would use at
    # defaults, so the byte-identical-at-defaults guarantee keeps holding.
    # Dark "edge" alpha (0.10 -> 0.14) is now UNIFIED with the specular bump
    # above — both approximate the SAME artifact "inset highlight" cue (a 1px
    # QSS border-top-color here, a QML rectangle for specular), so they share
    # one number instead of two that used to diverge (0.045 vs 0.10).
    # "edge_shade" (the INVERSE cue, for sunken surfaces) is intentionally
    # left at its existing alpha — the artifact gives no evidence for moving
    # it, and it is a distinct concept from the specular highlight.
    "chrome": _blend("#1B253A", _DARK_PANEL_V6, 0.74),
    "strip": _blend(_DARK_WELL_V6, _DARK_PANEL_V6, 0.55),
    "edge": _blend("#FFFFFF", "#27344A", 0.14),
    "edge_shade": _blend("#000000", "#27344A", 0.30),
    "plot_grid": None, "plot_overlay": None, "plot_accent": None,
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



# Backdrop canvas passthrough (glass-gap fix, 2026-07-13): how much the
# window's OWN unclaimed background (the QMainWindow/QDialog/#mainShell
# canvas fill immediately below) lets a REAL DWM backdrop material (Mica/
# Acrylic — gui/backdrop.py) show through once one is active. Deliberately
# NOT extended to QFrame#cardPane/#channelCard (the "panel" role) or any
# readout/text/plot/camera/danger surface — those keep painting fully
# opaque QSS exactly as gui/backdrop.py's own module docstring already
# documents ("every panel surface keep painting through their own opaque
# QSS ... only the window's own unclaimed background shows the OS backdrop
# material"); a QSS selector cannot tell a plot-hosting card from a plain
# one, so touching the panel role risks the "content stays opaque" hard
# rule for the widgets that actually matter. See
# docs/design/glass_gap_findings.md for the full barrier list and why this
# stays canvas-only. Tunable live via the theme editor's Material section
# (set_backdrop_canvas_alpha) — this constant is the SHIPPED DEFAULT, and the
# module reads the mutable ``_canvas_alpha`` below (which starts here).
BACKDROP_CANVAS_ALPHA = 0.82
# Safety clamp on the canvas alpha (Baldr's scrim-floor / worst-case-contrast
# contract, docs/design/glass_council/baldr.md §1.2): every glass alpha ships
# with a clamped legal range so a hand-edited settings file / an over-eager
# slider can never wash a glass surface out below WCAG-AA legibility. The floor
# 0.80 was picked with the panel-glass floor (0.50) so the WORST combined
# corner — the most-translucent legal canvas AND panel, over a pure-white or
# pure-black desktop, dark OR light theme — still clears 4.5:1 for muted text
# (measured 4.90:1 at 0.80/0.50; the shipped 0.82/0.55 default is 5.16:1).
MIN_BACKDROP_CANVAS_ALPHA = 0.80
MAX_BACKDROP_CANVAS_ALPHA = 1.0


# Panel-glass opt-in (experimental, Kaya-ratified 2026-07-13): how translucent
# a REGISTERED "safe" pane's own surface becomes when the theme editor's
# "Panel glass (experimental)" switch is on, so a real DWM backdrop can bleed
# through the CARD itself (not just the window's unclaimed canvas). Driven by a
# per-instance ``glassPane=true`` dynamic property (QSS below) set ONLY on panes
# explicitly opted in via ``gui.panel_kit.register_glass_pane`` — deliberately
# NOT a blanket ``QFrame#cardPane`` selector, which cannot tell a plot/camera/
# danger-well pane from a plain one and so would violate the "content stays
# opaque" hard rule for the widgets that actually matter (live readouts). Like
# BACKDROP_CANVAS_ALPHA this is the SHIPPED DEFAULT; the glassPane QSS reads the
# mutable ``_panel_glass_alpha`` below, tunable live via the theme editor's
# Material section (set_panel_glass_alpha).
PANEL_GLASS_ALPHA = 0.55
# Safety clamp on the panel-glass alpha — same scrim-floor contract as the
# canvas clamp above (Baldr §1.2). Floor 0.50 keeps the worst combined corner
# (canvas at its 0.80 floor too) at 4.90:1 for muted text on a glass pane over
# a pure-white/black desktop; the shipped 0.55 default measures 5.16:1. The
# readouts that MUST stay legible (Z4 hero tiles/wells) are opaque regardless —
# these panes only ever carry chrome/labels (Baldr Z-ladder), never live values.
MIN_PANEL_GLASS_ALPHA = 0.50
MAX_PANEL_GLASS_ALPHA = 1.0


def _canvas_fill(p: dict) -> str:
    """The GLASS canvas fill — an ``rgba()`` alpha fill so a real DWM material
    can show through the window's own unclaimed background, or the opaque
    ``p['bg']`` when no material is the user's persisted preference at all.

    UNDERLAY LAW (2026-07-13, beat G-B1): this value is NOT what the plain
    ``QMainWindow, QDialog`` / ``#mainShell`` rules paint. Those always paint the
    opaque ``p['bg']`` token pre-blend; the rgba fill below only ever applies
    behind the ``[glassCanvas="true"]`` attribute selector, and
    ``gui.backdrop`` sets that property on a window ONLY while a material is
    verifiably attached to its current HWND. Painting rgba on every window just
    because the *preference* was set is exactly how a window whose DWM
    attributes had died (a recreated HWND, a layered window, a path-D window)
    ended up as an alpha hole over nothing — the BLACK Kaya reported when he
    closed and reopened the theme editor. See ``gui/backdrop.py``'s
    CANVAS_GLASS_PROPERTY. Guard: tests/test_theme_editor.py's canvas-passthrough
    tests + tests/test_backdrop_event_spine.py's underlay-law tests."""
    if get_window_backdrop() == "none":
        return p["bg"]
    return _rgba(p["bg"], _canvas_alpha)


def _glass_canvas_qss(p: dict) -> str:
    """The property-gated glass-canvas rules (underlay law, see
    :func:`_canvas_fill`). Empty string while the shipped "none" backdrop is
    active — with no material anywhere, the rules would be dead weight and the
    QSS stays byte-identical to the pre-glass build."""
    if get_window_backdrop() == "none":
        return ""
    fill = _canvas_fill(p)
    return f"""
/* Glass canvas (underlay law) — ONLY on a window whose DWM material is
   verifiably attached to its CURRENT HWND right now. gui.backdrop sets
   glassCanvas="true" after both DWM calls returned S_OK on that handle, and
   clears it again on every loss/reset path (HWND recreated, attach failed,
   material reset). The unqualified rules above keep painting the opaque token
   pre-blend, so a lost material degrades to "looks like token glass" and can
   never degrade to a translucent hole over nothing (black). */
QMainWindow[glassCanvas="true"], QDialog[glassCanvas="true"] {{ background: {fill}; }}
QWidget#mainShell[glassCanvas="true"] {{ background: {fill}; }}
"""


def build_qss(p: dict) -> str:
    glass_canvas = _glass_canvas_qss(p)
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
   Guard: tests/test_style_no_label_box.py.
   HISTORY (2026-07-13, the glass-gap fix, then the underlay law the same
   night): these two rules paint the OPAQUE `p['bg']` token pre-blend —
   always, in every backdrop state. The rgba() alpha fill that actually lets a
   DWM material through lives in a separate, property-gated rule
   (`_glass_canvas_qss`, emitted right below) that only matches a window whose
   material `gui.backdrop` has verified on its current HWND. The first version
   of the glass-gap fix put the rgba fill HERE, unconditionally, for every
   QMainWindow/QDialog the moment the preference was set — so any window that
   did not actually get the material (recreated HWND, layered window,
   GL-hosting window) painted an alpha hole over nothing, i.e. BLACK. Never
   put an alpha fill in an unqualified canvas rule again. */
QMainWindow, QDialog {{ background: {p['bg']}; }}
QWidget#mainShell {{ background: {p['bg']}; }}
{glass_canvas}

/* Text-ish widgets are transparent — they sit ON a surface, they are not one.
   Explicit (not merely "inherited by omission") so that re-introducing a
   blanket rule above cannot silently put the box back: these three still win.
   Chips/marks/pills keep their own fill — ID and class selectors outrank a
   type selector (QLabel#statusChip, QLabel#ribbonMark, ...). */
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}

/* (The QScrollArea#ribbonScroll rule is gone with the scroll area itself: the
   ribbon WRAPS now instead of scrolling — a fixed-height scroll strip was
   silently clipping the MOTION chip off the right edge. See tct_gui.py.) */
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
/* Ribbon group caption ("DEVICES", "BIAS", "MOTION", ...). WCAG pass: was
   `faint` (2.73:1 — unreadable); the ink ladder's quiet-text token is `muted`
   (6.34:1 on the ribbon group's own surface). The caption still reads as
   quieter than the chips beside it — through size (11px) and case, not through
   contrast we cannot afford. */
QLabel#ribbonLabel {{
    color: {p['muted']}; font-size: {FONT_XS}px; font-weight: 600; letter-spacing: 0;
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
/* v6 "Glass" material pass: card radius 16 -> 20px (RADIUS_XL, see its own
   comment near RADIUS_LG) — QGroupBox IS the app's "card" surface. */
QGroupBox {{
    background: {p['panel']};
    border: 1px solid {p['hairline']};
    border-radius: {RADIUS_XL}px;
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
   (no fill change), padding 8/16 vs the artifact's 9/16.
   Codex S1 audit (2026-07-13, item 4): the base rule below is denser
   (w540, padding 6/12) so default/secondary/ghost buttons read less like a
   stock Qt control; primary/motion/danger commands keep the ORIGINAL larger
   affordance via an explicit padding/weight override right after their
   colour rule, so the higher-stakes actions do not shrink. */
QPushButton {{
    background: {p['field']};
    border: 1px solid {p['hairline_strong']};
    border-top-color: {p['edge']};
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_SM - 2}px {SPACE_MD}px;
    font-weight: 540;
}}
QPushButton:hover {{ border-color: {p['accent']}; background: {p['hover']}; }}
QPushButton:pressed {{ background: {p['active']}; }}
QPushButton:focus {{ outline: 2px solid {_rgba(p['accent'], 0.30)}; outline-offset: 1px; }}
QPushButton:disabled {{
    color: {p['faint']}; background: {p['disabled_bg']}; border-color: {p['hairline']};
}}
QPushButton:default, QPushButton[state="primary"] {{
    background: {p['accent']}; color: {p['on_accent']}; border: 1px solid {p['accent']};
    padding: {SPACE_SM - 1}px {SPACE_LG}px; font-weight: 560;
}}
QPushButton:default:hover, QPushButton[state="primary"]:hover {{ background: {p['accent_strong']}; }}
QPushButton[state="primary"]:pressed {{ background: {_darken(p['accent_strong'], 0.15)}; }}
QPushButton[state="busy"] {{
    background: {p['tint']}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.55)};
}}
/* State buttons: the same ink/fill decoupling as QLabel#statusChip below (see
   the long comment there) — coloured fill + coloured border, `text` label. */
QPushButton[state="good"] {{
    background: {_rgba(p['good'], 0.16)}; color: {p['text']};
    border: 1px solid {_rgba(p['good'], 0.55)};
}}
QPushButton[state="warn"], QPushButton#armedBtn, QPushButton[state="armed"] {{
    background: {_rgba(p['warn'], 0.16)}; color: {p['text']};
    border: 1px solid {_rgba(p['warn'], 0.65)};
    font-weight: 700;
}}
QPushButton[state="crit"] {{
    background: {_rgba(p['crit'], 0.16)}; color: {p['text']};
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
/* Pressed FILLS instead of deepening the accent wash under an accent label
   (that wash reached 0.18 — accent ink on a 0.18 tint of itself is ~4.2:1).
   An outline button that fills on press is the stronger affordance anyway, and
   `on_accent` on `accent` is a measured pair. Same move as the motion key. */
QPushButton[state="secondary"]:pressed {{
    background: {p['accent']}; color: {p['on_accent']}; border-color: {p['accent']};
}}
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
/* WCAG pass: the motion button is the ONE place the armed ink survives on a
   plain surface (it is the law-5 command class — a stage move must READ as
   amber, not as a neutral button), which is exactly why the light `armed` token
   was darkened until it clears 4.5:1 there (5.43 on a control cluster).
   Its hover/pressed feedback may NOT be an armed wash, though: ink on a tint of
   itself caps out around 4.3 even at 0.14 (see the statusChip comment). So hover
   is border-only — which is the artifact's own `.btn:hover` recipe anyway — and
   pressed FILLS with armed and flips to the `on_armed` label ink (white in
   light, near-black on dark's bright amber). A motion key that lights up when
   you push it is a better affordance than a wash, and it is AA in both themes. */
QPushButton[state="motion"] {{
    background: transparent; color: {p['armed']};
    border: 1.5px solid {_rgba(p['armed'], 0.55)}; font-weight: 620;
    padding: {SPACE_SM - 1}px {SPACE_LG}px;
}}
QPushButton[state="motion"]:hover {{
    background: transparent; border-color: {p['armed']};
}}
QPushButton[state="motion"]:pressed {{
    background: {p['armed']}; color: {p['on_armed']}; border-color: {p['armed']};
}}
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
/* Fills on press (see QPushButton[state="secondary"]:pressed): a CHECKED
   toolbutton carries accent ink, so an accent wash underneath it was ink on a
   tint of itself. */
QToolButton:pressed {{ background: {p['accent']}; color: {p['on_accent']}; }}
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
QToolButton#detachTabButton:pressed {{
    background: {p['accent']}; color: {p['on_accent']};
}}

/* Connect/Disconnect toolbar buttons (objectName set by tct_gui.py after
   building the QToolBar action widgets — "objectNames for the green/red QSS
   accents", now stale naming: neither carries a state colour any more).
   State-color census D4 rank-1 fix (docs/design/state_color_census.md):
   this used to be tonal good/crit (green/red) chrome — colour encoding a
   COMMAND, the exact thing council_v5_paul.md §3 rules out for the Device
   Manager's own Connect All ("neutral/accent — NOT green: colour encodes
   state, never a command") and the QML rail's Shell.qml ShellButton already
   gets right (Connect All = "accent" tone, Disconnect All = "quiet"/neutral
   — "a bulk disconnect is a neutral, safe action — never red"). Connect
   reuses the QPushButton[state="secondary"] accent-outline recipe above (a
   primary-quiet affordance, not a status light); Disconnect drops to plain
   neutral chrome — it is an ordinary reversible action, not a
   hardware-dangerous one (see CLAUDE.md's confirmation-required list), so it
   never borrows dangerBtn's red. */
QPushButton#connectBtn, QToolButton#connectBtn {{
    background: {p['field']}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.55)}; font-weight: 600;
}}
QPushButton#connectBtn:hover, QToolButton#connectBtn:hover {{
    background: {p['tint']}; border-color: {p['accent']};
}}
QPushButton#connectBtn:pressed, QToolButton#connectBtn:pressed {{
    background: {p['accent']}; color: {p['on_accent']}; border-color: {p['accent']};
}}
QPushButton#disconnectBtn, QToolButton#disconnectBtn {{
    background: {p['field']}; color: {p['text']};
    border: 1px solid {p['hairline_strong']}; font-weight: 600;
}}
QPushButton#disconnectBtn:hover, QToolButton#disconnectBtn:hover {{
    background: {p['hover']}; border-color: {p['border_strong']};
}}
QPushButton#disconnectBtn:pressed, QToolButton#disconnectBtn:pressed {{
    background: {p['active']};
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

/* Tables (device/monitor panels). Codex S1 audit (2026-07-13, item 5): header
   background moved from `material` (same tone as the surrounding chrome, so
   the header read as flush with the toolbar rather than as part of the
   table) to `strip` (the recessed status-strip wash), giving the header a
   distinct row-grammar tone. */
QHeaderView::section {{
    background: {p['strip']}; color: {p['muted']};
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
/* Codex S1 audit item 5: richer row grammar — more breathing room per item,
   and a neutral `raised` hover wash (no accent tint: hover is "you are
   here", not a state) instead of the button-toned `field`. */
QTreeWidget::item, QListWidget::item {{ padding: 4px 6px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {p['raised']}; }}

/* Danger action button (STOP / immediate hardware abort). Same red language
   as the toolbar Disconnect button, under its own name so any panel can mark
   an "abort now" control this way without borrowing the connect/disconnect
   semantics. QPushButton[state="danger"] (gui/panel_kit.py ActionBar) is
   folded into the same selectors byte-for-byte — an opt-in via the state
   property reaches the identical look instead of a second danger language
   (cockpit_style_overhaul.md §1 rule 2: one danger visual language). */
/* WCAG pass (2026-07-14) — THE worst finding of the audit. This rule used to
   read ``background: {{crit}}; color: white``. Nobody ever measured that pair,
   because the QSS said the quiet word "white" instead of naming a token: white
   on the DARK theme's bright #FF5A61 is **3.05:1** — the label of the HV /
   scan-abort button, below even the 3:1 non-text floor. Light was 4.19, also
   failing. An Abort button you cannot read is a hazard, not a control.
   The fill is now its own token (``danger_fill`` — dark enough in BOTH themes to
   carry a label) and the label is ``on_danger``, so the pair is a thing that can
   be, and is, measured (tests/test_palette_contrast.py). ``crit``/``danger``
   stays the bright INK for chips/lamps/hero values — the two jobs are no longer
   one token. Hover/pressed darken the FILL, so the label only ever gets MORE
   readable as the button is pressed. */
QPushButton#dangerBtn, QPushButton[state="danger"] {{
    background: {p['danger_fill']}; color: {p['on_danger']};
    border: 1px solid {p['danger_fill']};
    font-weight: 700;
    padding: {SPACE_SM - 1}px {SPACE_LG}px;
}}
QPushButton#dangerBtn:hover, QPushButton[state="danger"]:hover {{
    background: {_darken(p['danger_fill'], 0.12)};
    border-color: {_darken(p['danger_fill'], 0.12)};
}}
QPushButton#dangerBtn:pressed, QPushButton[state="danger"]:pressed {{
    background: {_darken(p['danger_fill'], 0.22)};
}}
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
/* The value ink is the FIXED instrument-screen accent, not the theme accent:
   this label sits on PLOT_BG (a dark screen in BOTH themes), so painting the
   LIGHT theme's accent on it gave 4.17:1 — a failing pair on a real hardware
   readout (stage position). See PLOT_ACCENT. */
QLabel#readoutValue {{
    color: {p['plot_accent']};
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
/* Stale ink (law 4: "staleness is designed"). WCAG pass: this used to desaturate
   to `faint` ON the recessed `well` surface — 1.91:1 in light, the single worst
   pair in the app, on the LAST KNOWN VALUE of a live instrument. An operator has
   to be able to READ a stale reading (that is the whole point of showing it) and
   see that it is stale. Staleness now reads through the recessed surface + the
   dropped weight + the caption ("value aged Ns"), and the ink stays legible. */
QLabel#readoutCellValue[stale="true"] {{ color: {p['muted']}; font-weight: 400; }}
QLabel#readoutCellTitle[stale="true"] {{ color: {p['muted']}; }}
QFrame#readoutCell[stale="true"] {{ background: {p['well']}; }}
/* MetricTile caption (gui/panel_kit.py) — the law-4 "why" line under a stale
   tile ("not connected" / "no run" / "value aged Ns"), and any live tile's
   short body caption (e.g. an "avg x N" chip). Sentence-case body ink (law
   3: "Explanations: sentence-case sans. Never uppercase prose."), never the
   tracked-mono-uppercase label treatment above. */
QLabel#metricTileCaption {{
    color: {p['muted']}; font-size: {FONT_XS}px; font-weight: {WEIGHT_BODY};
}}
QLabel#metricTileCaption[stale="true"] {{ color: {p['muted']}; }}
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
/* v6 "Glass" material pass: card radius 16 -> 20px (RADIUS_XL) — cardPane is
   a Card's own surface (gui/panel_kit.py), the same "card" concept as
   QGroupBox above. */
QFrame#cardPane {{
    background: {p['panel']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_XL}px;
}}

/* Channel card — a cardPane variant used per scope channel.  The panel adds an
   inline coloured left border per channel; this is the shared base look. */
QFrame#channelCard {{
    background: {p['panel']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_SM}px;
}}

/* Panel glass (experimental, OPT-IN) — a per-instance ``glassPane=true``
   dynamic property (set only by gui.panel_kit.set_panel_glass on panes
   REGISTERED via register_glass_pane, driven by the theme editor's "Panel
   glass" switch) trades a safe pane's opaque fill for an rgba() tint of the
   active "panel" colour, so a DWM backdrop bleeds through the card itself.
   Attribute selectors outrank the bare #cardPane / QGroupBox rules above, so
   this wins wherever the property is set and is completely inert (no widget
   carries it) otherwise. HARD exclusion by construction: nothing registers a
   plot/camera/danger-well pane (a FigureCard is refused outright), so those
   never get the property — guard: tests/test_panel_kit_cockpit.py. See
   PANEL_GLASS_ALPHA / docs/design/glass_gap_findings.md §6. */
QFrame#cardPane[glassPane="true"] {{ background: {_rgba(p['panel'], _panel_glass_alpha)}; }}
QGroupBox[glassPane="true"] {{ background: {_rgba(p['panel'], _panel_glass_alpha)}; }}

/* Eyebrow — a small caption label above a heading/value.  QSS cannot
   uppercase text, so the panel should pass already-uppercased text; letter-
   spacing gives it the tracking real small-caps captions need to read
   comfortably at this size instead of looking merely "shrunk". */
/* font-family deliberately stays on the shared sans stack — see the
   matching comment on QLabel#clusterCaption above (this selector has the
   exact same "reused for punctuation-bearing captions" risk: eyebrow_title
   AND form_row's per-field caption both key off it). */
QLabel#eyebrow {{
    color: {p['muted']};
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
   neutral pill.
   v6 "Glass" material pass: the resting (neutral/unknown) surface now reads
   ``p['chip']`` instead of ``p['field']`` — the artifact's own
   ``--chip-bg`` grammar, a translucency-equivalent wash distinct from the
   button/field material (see the "chip" token comment in LIGHT/DARK). */
QLabel#statusChip {{
    padding: 2px {SPACE_SM + 2}px;
    border-radius: {RADIUS_PILL}px;
    font-size: {FONT_XS}px; font-weight: 600;
    background: {p['chip']}; color: {p['muted']};
    border: 1px solid {p['hairline']};
}}
QLabel#statusChip[state="neutral"] {{
    background: {p['chip']}; color: {p['muted']}; border: 1px solid {p['hairline']};
}}
QLabel#statusChip[state="disconnected"] {{
    background: transparent; color: {p['muted']}; border: 1px solid {p['hairline']};
}}
QLabel#statusChip[state="unknown"] {{
    background: {p['chip']}; color: {p['muted']};
    border: 1px dashed {p['hairline_strong']};
}}
/* ── WHY THE STATE CHIPS' LABEL IS `text`, NOT THE STATE COLOUR ──────────────
   (WCAG pass, 2026-07-14 — this is the structural half of the palette fix.)

   A state chip paints ``rgba(token, 0.16)`` over its parent surface and then
   put a label ON it IN THE SAME TOKEN: ink on a wash OF ITSELF. That wash pulls
   the background toward the ink, so the pair is capped far below where the
   token's own plain-surface contrast suggests — light `good` on its own chip
   measured 3.53:1, `warn` 3.35, `sim` 2.78. Darkening the tokens does not
   rescue it: to clear 4.5:1 at these alphas the light hues have to go 25-36%
   darker, at which point amber is brown, sim's cyan collapses toward good's
   green (law 6!), and it IS the re-theme Kaya ruled out.

   So the ink and the fill are decoupled: the chip keeps its coloured FILL and
   its coloured BORDER — the colour language an operator reads at a glance is
   untouched — and the LABEL takes the neutral `text` ink, which clears 10.3:1
   (light) / 6.4:1 (dark) on EVERY one of these washes at EVERY alpha. That is
   also robust by construction: a future tweak to a fill alpha cannot make a
   label unreadable. State is never colour-alone anyway (the chip's own text
   names it — house rule), so nothing is lost from the redundant channel.  */
QLabel#statusChip[state="good"] {{
    background: {_rgba(p['good'], 0.16)}; color: {p['text']};
    border: 1px solid {_rgba(p['good'], 0.55)};
}}
QLabel#statusChip[state="warn"], QLabel#statusChip[state="fault"] {{
    background: {_rgba(p['warn'], 0.16)}; color: {p['text']};
    border: 1px solid {_rgba(p['warn'], 0.55)};
}}
QLabel#statusChip[state="crit"] {{
    background: {_rgba(p['crit'], 0.16)}; color: {p['text']};
    border: 1px solid {_rgba(p['crit'], 0.55)};
}}
/* The accent family is the ONE exception: `tint` is a fixed 0.10/0.13 wash
   computed at palette-build time (not a per-rule rgba), and the darkened light
   accent clears it at 4.58:1 — so info/busy keep their accent ink. */
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
/* The busy pulse used to swing the FILL to rgba(accent, 0.30) — a wash that
   deep drags the accent label down to 3.3:1 on the beat. The pulse now lives
   entirely in the BORDER (law 8 is satisfied by any visible periodic change),
   so the label's contrast is constant across both phases instead of dipping
   every second. */
QLabel#statusChip[state="busy"][pulsePhase="1"] {{
    background: {p['tint']}; border: 1px solid {p['accent']};
}}
/* armed / simulated / the motion-pulse chips: same ink/fill decoupling as the
   good/warn/crit block above (these carry the DEEPEST washes — 0.20 armed,
   0.24 at pulse phase 1 — so they were the worst offenders of the lot). The
   sim chip keeps its dashed cyan ring: law 6's "sim can never pass as real"
   never rested on the ink colour alone. */
QLabel#statusChip[state="armed"] {{
    background: {_rgba(p['warn'], 0.20)}; color: {p['text']};
    border: 1px solid {_rgba(p['warn'], 0.70)};
}}
QLabel#statusChip[state="simulated"] {{
    background: {_rgba(p['sim'], 0.12)}; color: {p['text']};
    border: 1px dashed {_rgba(p['sim'], 0.70)};
}}
QLabel#statusChip[motionPulse="laser"][motionPulsePhase="0"] {{
    background: {_rgba(p['crit'], 0.14)}; color: {p['text']};
    border: 1px solid {_rgba(p['crit'], 0.42)};
}}
QLabel#statusChip[motionPulse="laser"][motionPulsePhase="1"] {{
    background: {_rgba(p['crit'], 0.24)}; color: {p['text']};
    border: 1px solid {_rgba(p['crit'], 0.78)};
}}
QLabel#statusChip[motionPulse="hv"][motionPulsePhase="0"] {{
    background: {_rgba(p['warn'], 0.14)}; color: {p['text']};
    border: 1px solid {_rgba(p['warn'], 0.42)};
}}
QLabel#statusChip[motionPulse="hv"][motionPulsePhase="1"] {{
    background: {_rgba(p['warn'], 0.24)}; color: {p['text']};
    border: 1px solid {_rgba(p['warn'], 0.78)};
}}
QLabel#statusChip[motionPulse="scan"][motionPulsePhase="0"] {{
    background: {_rgba(p['accent'], 0.14)}; color: {p['text']};
    border: 1px solid {_rgba(p['accent'], 0.42)};
}}
QLabel#statusChip[motionPulse="scan"][motionPulsePhase="1"] {{
    background: {_rgba(p['accent'], 0.24)}; color: {p['text']};
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
/* WCAG pass: a StatusLamp is a 9px dot with NO label — its colour is the SOLE
   carrier of the state, so it owes 3:1 (WCAG 1.4.11), and `faint` gave it
   2.72:1 in light / 2.61 on a dark card. "Disconnected" and "unknown" are
   law-7 states (never lie about hardware); an invisible one lies by omission.
   Both move to `muted` — still the quiet, colourless end of the ladder, but a
   dot you can actually see (6.63:1). */
QFrame#statusLamp[state="disconnected"] {{
    background: transparent; border: 1px solid {p['muted']};
}}
QFrame#statusLamp[state="unknown"] {{
    background: {p['muted']}; border: 1px dashed {p['hairline_strong']};
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
# PLOT_ACCENT — accent ink ON the instrument screen, fixed in both themes for
# exactly the same reason as PLOT_BG/PLOT_FG above. WCAG pass (2026-07-14): the
# motor position LCD (``QLabel#readoutValue``) painted the *theme* accent on
# this fixed dark canvas, so in LIGHT mode it was the light accent on near-black
# — 4.17:1, a failing pair on a genuine instrument readout (stage position). The
# plot canvas does not repaint on a theme switch, so its ink must not depend on
# the theme either: the dark accent is the only one that belongs here (8.02:1).
PLOT_ACCENT = ACCENT_DARK
for _p in (LIGHT, DARK):
    _p["plot_grid"] = PLOT_GRID
    _p["plot_overlay"] = PLOT_OVERLAY
    _p["plot_accent"] = PLOT_ACCENT
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
#   edge       = _blend(#fff, hairline, (0.92 light / 0.14 dark) * g)
#                                                 — specular machined top edge
#   edge_shade = _blend(#000, hairline, (0.16 light / 0.30 dark) * g)
#                                                 — shaded top edge of sunken wells
# g == 1.0 (DEFAULT) reproduces today's v6 glass ceiling byte-for-byte;
# g == 0.0 is fully opaque: chrome/strip collapse to plain "panel" and both
# machined edges collapse to the uniform hairline. PLOT_BG/PLOT_FG are
# deliberately NOT parametrized: plots/camera keep the fixed opaque
# instrument screen at ANY glass amount (design law 8 / "nothing translucent
# over a plot").
# v6 glass pass (Kaya-ratified A/B artifact side B): "edge" alpha moves to
# 0.14 dark / 0.92 light, UNIFIED with the DARK/LIGHT "specular" token bump
# right above — both approximate the same artifact inset-highlight cue via
# two different rendering paths (a QSS border-top-color here, a QML
# rectangle for specular). "edge_shade" is untouched — a distinct, inverse
# cue with no artifact evidence to move it.
_GLASS_BLEND_ALPHAS = {
    "light": {"chrome": 0.74, "strip": 0.55, "edge": 0.92, "edge_shade": 0.16},
    "dark":  {"chrome": 0.74, "strip": 0.55, "edge": 0.14, "edge_shade": 0.30},
}

# Safety palette — LOCKED (laws 1/2/6: quiet nominal / command classes / sim
# can never pass as real). "crit"/"warn" are the legacy byte-alias keys of
# "danger"/"armed" (see the palette dicts): locking "danger" while leaving
# "crit" writable would be a bypass, since most QSS rules read p['crit'].
# There is NO override path — apply_theme_overrides raises, and
# sanitize_overrides silently drops these on any preset-JSON load.
# WCAG pass (2026-07-14): "danger_fill"/"on_danger"/"on_armed" join the lock.
# They ARE the hazard surfaces (the HV/abort button body and the ink on it, the
# pressed motion key) — a user-editable "on_danger" would let a preset paint the
# Abort label in any colour it liked, including one that vanishes into the fill.
SAFETY_TOKENS = frozenset({"danger", "armed", "sim", "error", "crit", "warn",
                           "danger_fill", "on_danger", "on_armed"})

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
# BUILT-IN PRESETS (Kaya round 2: "ich will mehr theme presets"; the Glass
# family below is round 3, Kaya 2026-07-13: "mehr Presets, angeführt von
# einem 1:1 Glass-Preset")
#
# The first five (Cockpit Dark/Graphite/Deep Violet/Lab Light/Paper) are
# ported verbatim from the v5 playground's `P` map
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
# nine presets, by construction.
#
# "Cockpit Dark" and "Lab Light" carry NO overrides on purpose: they ARE the
# shipped themes (the ratified v5 look), so selecting them restores the app
# exactly as it ships rather than a near-copy. The playground's own glass values
# for those two are likewise not ported — the shipped default is the reference.
# `well` reproduces the playground's derivation (blend(bg, panel, 0.6)) instead
# of a hand-typed value, so the wells track their preset's canvas/panel.
def _preset_well(canvas: str, panel: str) -> str:
    return _blend(canvas, panel, 0.6)


# ---------------------------------------------------------------------------
# Glass family (round 3): Glass · Plasma · Aurora · Spatial Light — headlined
# by "Glass", a 1:1 derivation of the Kaya-ratified A/B artifact's side B
# (artifacts_claude/tct_bias_glass_ab.html, ``.skin-glass``), same
# QWidgets-honest "flat ``_blend`` pre-blend, no live translucency" law as the
# shipped v6 pass above (_DARK_PANEL_V6 etc.) — these are ordinary presets,
# not a new material mechanism.
#
# The artifact renders its card material with REAL backdrop-blur floating
# over a fixed ambient backdrop: the page base ``body{background:#05070C}``
# plus four radial glow gradients (``.ambient``). A flat QSS token can't
# reproduce a per-pixel radial gradient, so the SAME move the shipped v6 pass
# already makes (composite a literal artifact colour over the real canvas via
# ``_blend`` instead of live blur) is applied one level up: each preset's
# CANVAS becomes the artifact's page base biased by a FAINT wash of one
# ambient glow colour, and panel/well/hairline then use the artifact's own
# card/well/border recipes composited over THAT canvas — so the whole
# material ladder shifts together, not just one token.
#
# ``_GLASS_FAMILY_AMBIENT_ALPHA = 0.08`` is deliberately far below any single
# gradient's own peak alpha (0.32/0.16/0.20 in the artifact): each gradient
# is a concentrated hot-spot covering roughly a third of one page corner
# (``radial-gradient(38% 45% at 12% 20%, ...)`` etc.), not present at full
# strength across an entire panel — a flat token has to stand in for the
# AVERAGE ambient presence a panel actually sits in, so "faint... bias" per
# the task brief, not a flat wash at the gradient's own peak. The SAME alpha
# is shared by every dark member of the family (only the ambient hue
# rotates) so the "material depth" reads consistent across the set — a
# deliberate normalisation, since the artifact's own three glow alphas differ
# for reasons (page-composition emphasis) that don't apply to a single-hue
# preset canvas.
_GLASS_FAMILY_PAGE_BASE = "#05070C"     # artifact body{background} verbatim
_GLASS_FAMILY_AMBIENT_ALPHA = 0.08      # shared "faint" bias, see comment above
_GLASS_FAMILY_HAIRLINE_ALPHA = 0.10     # artifact --card-border: rgba(255,255,255,0.10)


def _glass_family_canvas(ambient_fg: str) -> str:
    """Faint *ambient_fg* bias over the artifact's page base — the preset's
    own "lab ambient" canvas, see the module comment above."""
    return _blend(ambient_fg, _GLASS_FAMILY_PAGE_BASE, _GLASS_FAMILY_AMBIENT_ALPHA)


def _glass_family_panel(canvas: str) -> str:
    """The artifact's own ``--card-bg`` recipe (_GLASS_CARD_FG_DARK at
    _GLASS_CARD_ALPHA, both already defined for the shipped v6 pass above),
    composited over *this preset's* ambient-biased canvas instead of the
    shipped app canvas."""
    return _blend(_GLASS_CARD_FG_DARK, canvas, _GLASS_CARD_ALPHA)


def _glass_family_well(canvas: str) -> str:
    """The artifact's own ``--well-bg`` recipe, same treatment as
    ``_glass_family_panel`` above."""
    return _blend(_GLASS_WELL_FG_DARK, canvas, _GLASS_WELL_ALPHA)


def _glass_family_hairline(canvas: str) -> str:
    """The artifact's own ``--card-border: rgba(255,255,255,0.10)``, white
    over *this preset's* canvas — the same "white/black over the backing
    surface" idiom ``_recompute_palettes`` already uses to derive
    chrome/edge from panel/hairline."""
    return _blend("#FFFFFF", canvas, _GLASS_FAMILY_HAIRLINE_ALPHA)


# "Glass" — the 1:1 preset: literal artifact ambient (its DOMINANT glow, the
# first/largest/highest-alpha gradient, rgba(42,111,224,0.32), positioned
# top-left) plus the artifact's own text/muted/accent literals verbatim. All
# three of those already equal the shipped DARK tokens (the v6 pass above
# already carries them), so Glass reproduces them exactly rather than
# re-deriving — only canvas/panel/well/hairline actually move, because only
# those read differently against this preset's own ambient-biased canvas.
_GLASS_CANVAS = _glass_family_canvas("#2A6FE0")

# "Plasma" — same grammar, the artifact's THIRD gradient
# (rgba(120,80,255,0.20), the "Vision-Pro-dashboard" violet family in
# design_assets/) standing in for the ambient bias. Accent is Deep Violet's
# own literal (task brief: "violet accent ≈ #8f7aff family") rather than the
# raw ambient hex — same split the artifact itself uses (--accent is a
# separate, brighter/more-legible token from any one ambient glow).
_PLASMA_CANVAS = _glass_family_canvas("#7850FF")
_PLASMA_ACCENT = "#8f7aff"

# "Aurora" — same grammar again, but the artifact's own CYAN gradient
# (rgba(65,216,228,0.16)) is #41D8E4 — byte-identical to SIM_PURPLE, the
# locked "simulated" safety token (law 6: sim can never pass as real). Reusing
# it verbatim would let an Aurora accent chip read as the SIM badge, so the
# ambient/accent hue here is that SAME cyan rotated -25° (same HLS lightness/
# saturation, only hue moves) — verified >55 RGB-distance from BOTH
# SIM_PURPLE and OK_GREEN (the other border it must not drift into) in
# tests/test_theme_editor.py. Accent is a lighter/more-saturated variant of
# the rotated hue, matching the "ambient glow vs. legible accent" split
# Glass/Plasma already use.
_AURORA_CANVAS = _glass_family_canvas("#41e4ac")
_AURORA_ACCENT = "#63eebe"

# "Spatial Light" — the one LIGHT member (bright frosted-white "Apple Spatial
# UI" reference in design_assets/): a cool pale ambient standing in for the
# artifact's dark backdrop. LIGHT has NO artifact literal to borrow (same gap
# noted above _LIGHT_PANEL_V6) and the SAME ladder-inversion risk applies:
# panel is already the brightness ceiling, so it stays pure white — UNCHANGED,
# never blended toward canvas — while canvas/well/hairline carry the "material"
# via the gentler ink-wash grammar the shipped LIGHT v6 pass already uses
# (``_LIGHT_WELL_V6 = _blend("#000000", canvas, alpha)``), not the dark
# family's card-alpha blend (0.42/0.55 would invert the ladder here exactly
# as reasoned above _LIGHT_PANEL_V6). `well` reuses `_preset_well` (the same
# helper Graphite/Deep Violet/Paper already use) for that reason — it IS the
# ceiling-safe recipe already, no new one needed.
_SPATIAL_LIGHT_CANVAS = _blend("#2A6FE0", "#FFFFFF", 0.10)
_SPATIAL_LIGHT_HAIRLINE = _blend("#000000", _SPATIAL_LIGHT_CANVAS, 0.05)
_SPATIAL_LIGHT_ACCENT = "#1c87e8"


BUILTIN_PRESETS: tuple[dict, ...] = (
    {"name": "Cockpit Dark", "mode": "dark", "glass": DEFAULT_GLASS_AMOUNT,
     "overrides": {}},
    {"name": "Glass", "mode": "dark", "glass": DEFAULT_GLASS_AMOUNT, "overrides": {
        "canvas": _GLASS_CANVAS,
        "panel": _glass_family_panel(_GLASS_CANVAS),
        "well": _glass_family_well(_GLASS_CANVAS),
        "hairline": _glass_family_hairline(_GLASS_CANVAS),
        "text": "#E9EDF5", "muted": "#98A1B5", "accent": "#5AA9FF",
    }},
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
    {"name": "Plasma", "mode": "dark", "glass": DEFAULT_GLASS_AMOUNT, "overrides": {
        "canvas": _PLASMA_CANVAS,
        "panel": _glass_family_panel(_PLASMA_CANVAS),
        "well": _glass_family_well(_PLASMA_CANVAS),
        "hairline": _glass_family_hairline(_PLASMA_CANVAS),
        "text": "#E9EDF5", "muted": "#98A1B5", "accent": _PLASMA_ACCENT,
    }},
    {"name": "Aurora", "mode": "dark", "glass": DEFAULT_GLASS_AMOUNT, "overrides": {
        "canvas": _AURORA_CANVAS,
        "panel": _glass_family_panel(_AURORA_CANVAS),
        "well": _glass_family_well(_AURORA_CANVAS),
        "hairline": _glass_family_hairline(_AURORA_CANVAS),
        "text": "#E9EDF5", "muted": "#98A1B5", "accent": _AURORA_ACCENT,
    }},
    {"name": "Lab Light", "mode": "light", "glass": DEFAULT_GLASS_AMOUNT,
     "overrides": {}},
    {"name": "Paper", "mode": "light", "glass": 0.55, "overrides": {
        "canvas": "#f2efe9", "panel": "#fffdf8", "text": "#1c1a15",
        "muted": "#5d5850", "hairline": "#e2ddd2", "accent": "#3e6b8f",
        "well": _preset_well("#f2efe9", "#fffdf8"),
    }},
    {"name": "Spatial Light", "mode": "light", "glass": DEFAULT_GLASS_AMOUNT,
     "overrides": {
        "canvas": _SPATIAL_LIGHT_CANVAS, "panel": _LIGHT_PANEL_V6,
        "well": _preset_well(_SPATIAL_LIGHT_CANVAS, _LIGHT_PANEL_V6),
        "hairline": _SPATIAL_LIGHT_HAIRLINE,
        "text": "#0f1b2e", "muted": "#4a5568", "accent": _SPATIAL_LIGHT_ACCENT,
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
_SETTINGS_CANVAS_ALPHA_KEY = "theme/canvas_alpha"
_SETTINGS_PANEL_GLASS_ALPHA_KEY = "theme/panel_glass_alpha"

# Live customization state (module-level; reset via reset_theme_customization).
_glass_amount: float = DEFAULT_GLASS_AMOUNT
_window_opacity: float = DEFAULT_WINDOW_OPACITY
# Glass alphas — the two material dials the theme editor's Material section
# exposes (Baldr T3 "mechanism-tunable" tokens). Mutable so a live slider can
# retune them; the QSS builder / _canvas_fill read these, not the DEFAULT
# constants above. Clamped on every write to the scrim-floor legal range.
_canvas_alpha: float = BACKDROP_CANVAS_ALPHA
_panel_glass_alpha: float = PANEL_GLASS_ALPHA
# Windows 11 DWM system backdrop material — see gui/backdrop.py. Preference
# state only; whether it actually renders is decided at apply time by
# backdrop.is_backdrop_supported(). "none" everywhere else in the module.
_window_backdrop: str = "none"
# The theme mode ("dark"/"light") of the last apply_theme call. Authoritative
# after the first apply_theme (which always runs at startup, main.py). Read by
# apply_window_backdrop_to so the DWM material's immersive-dark tint matches the
# active theme (gui.backdrop.DWMWA_USE_IMMERSIVE_DARK_MODE) — the cockpit is
# dark-first, so "dark" is the safe pre-first-apply fallback.
_active_mode: str = "dark"
# The backdrop kind the CURRENTLY INSTALLED app stylesheet was built with (None
# before the first apply_theme). The glass-canvas rules (_glass_canvas_qss) exist
# in the QSS only while a material is preferred, so flipping the preference
# LIVE changes the stylesheet — and nothing on the theme editor's backdrop path
# (set_window_backdrop → apply_window_backdrop → apply_window_opacity) used to
# rebuild it. Result (Mary, G-B1 review, BUG 1): after a live none → acrylic
# toggle, gui.backdrop dutifully set glassCanvas="true" on the windows whose
# material attached, but the QSS carried NO rule behind that selector, so the
# window kept painting the opaque p['bg'] — the alpha hole never opened and Kaya
# saw no glass. apply_window_backdrop() now compares this against the resolved
# kind and rebuilds the QSS first. NOT part of the user's customization (it
# describes the installed stylesheet, not a preference), so
# reset_theme_customization does not touch it — apply_theme is its only writer.
_qss_backdrop: str | None = None
# Windows currently inside a backdrop re-assert — the re-entrancy guard for
# _apply_window_backdrop_to (see its docstring: our own palette write delivers
# PaletteChange back into the event filter that called us). WeakSet so a closed
# window is never kept alive by this module.
_reasserting_windows: "weakref.WeakSet" = weakref.WeakSet()
# True while a deferred post-toggle re-assert is already queued — see
# _schedule_post_toggle_reassert (coalesced: at most one pending pass).
_post_toggle_pending: bool = False
# Injectable "is a scan running right now?" predicate — see
# set_scan_active_provider. Presentation must never import controller/, so the
# run-state source is WIRED IN by the composition root (tct_gui) instead.
_scan_active_provider: "Callable[[], bool] | None" = None
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


def set_backdrop_canvas_alpha(value) -> float:
    """Set how much the window-canvas fill lets a DWM backdrop through and
    return the value actually set — CLAMPED to
    [MIN_BACKDROP_CANVAS_ALPHA, MAX_BACKDROP_CANVAS_ALPHA] (the scrim-floor
    safety rail, Baldr §1.2). Garbage (None, "", NaN) fails to the fully-opaque
    end. Does NOT recompute palettes (the alpha only affects _canvas_fill's QSS,
    never the palette dicts); the caller still regenerates + reapplies the QSS
    (apply_theme) and re-runs apply_window_backdrop to repaint."""
    global _canvas_alpha
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = MAX_BACKDROP_CANVAS_ALPHA
    if value != value:                      # NaN — clamp to the opaque end
        value = MAX_BACKDROP_CANVAS_ALPHA
    _canvas_alpha = max(MIN_BACKDROP_CANVAS_ALPHA,
                        min(MAX_BACKDROP_CANVAS_ALPHA, value))
    return _canvas_alpha


def get_backdrop_canvas_alpha() -> float:
    return _canvas_alpha


def set_panel_glass_alpha(value) -> float:
    """Set the opted-in panel-glass tint alpha and return the value actually
    set — CLAMPED to [MIN_PANEL_GLASS_ALPHA, MAX_PANEL_GLASS_ALPHA] (scrim
    floor, Baldr §1.2). Garbage / NaN fails opaque. Only affects the glassPane
    QSS rule, so no palette recompute; caller reapplies the QSS to repaint."""
    global _panel_glass_alpha
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = MAX_PANEL_GLASS_ALPHA
    if value != value:                      # NaN — clamp to the opaque end
        value = MAX_PANEL_GLASS_ALPHA
    _panel_glass_alpha = max(MIN_PANEL_GLASS_ALPHA,
                             min(MAX_PANEL_GLASS_ALPHA, value))
    return _panel_glass_alpha


def get_panel_glass_alpha() -> float:
    return _panel_glass_alpha


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


def effective_window_opacity() -> float:
    """The opacity a window must ACTUALLY carry right now.

    A DWM system backdrop material and a LAYERED window (``setWindowOpacity``
    < 1 ⇒ ``WS_EX_LAYERED``) are mutually exclusive: the uniform per-window
    alpha suppresses the material outright (Kaya's live 98 % was the proof the
    acrylic "vanished"). So while a material is the active preference, every
    window is pinned to fully opaque; the stored preference
    (:func:`get_window_opacity`) is untouched and returns the moment the
    backdrop goes back to "none".

    Extracted from :func:`apply_window_opacity` (beat G-B1) because the
    CONSTRUCTION paths — ``_DetachedWindow``, ``ThemeEditorDialog``,
    ``SettingsWindow``, ``TCTMainWindow`` — used to push the RAW stored value
    onto a brand-new window and so layered every satellite created while a
    material was live. A detached panel could therefore never show glass: it
    laid ``WS_EX_LAYERED`` over its own material microseconds after attaching
    it. Every one of those call sites now goes through
    :func:`reassert_window_backdrop`, which applies this pin."""
    return 1.0 if _window_backdrop != "none" else _window_opacity


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
    # The WS_EX_LAYERED pin — see effective_window_opacity() for the mechanism
    # and gui/theme_editor.py for the matching UI clamp + visible note.
    effective = effective_window_opacity()
    for w in app.topLevelWidgets():
        if w.isWindow() and not _is_transient_window(w):
            w.setWindowOpacity(effective)
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


def set_scan_active_provider(provider: "Callable[[], bool] | None") -> None:
    """Wire the presentation layer to the app's run-state source — WITHOUT
    importing it (Mary, G-B1 review, RISK 5).

    ``gui.backdrop.nudge_repaint`` heals a stale surface with a REAL 1-px resize
    + restore of the top-level, and the backdrop spine calls it on every
    successful re-assert of a live-material window (Show, WinIdChange,
    WindowStateChange, post-toggle, the deferred theme pass). A resize is not
    cosmetic work: it forces a full relayout of the dock tree, every pyqtgraph
    plot and the camera view on the GUI thread — of an app that is already
    CPU-bound during an acquisition. A minimize→restore or an OS theme flip mid
    scan would therefore stall the run's UI for a purely visual repair. Not data
    loss (the workers own acquisition + HDF5), but a self-inflicted freeze, and
    "scan-aware deferral" is a named element of the glass synthesis
    (docs/design/glass_council/SYNTHESIS.md §136/§179/§610).

    The predicate is INJECTED rather than read, because ``gui/style.py`` must
    never import ``controller/`` (presentation stays decoupled from the state
    machine — see docs/design/gui_architecture_plan.md's composition-root rule).
    The composition root (``tct_gui.TCTMainWindow``) wires it to the existing
    run-state source; unset (every test, every script, any embedding that has no
    scan) means "not scanning", so the behaviour is unchanged by default.
    Pass ``None`` to unwire (teardown / test isolation)."""
    global _scan_active_provider
    _scan_active_provider = provider


def scan_is_active() -> bool:
    """True only while the wired-in provider says a run is in flight.

    Fails SAFE for the cosmetic caller: no provider, or a provider that raises,
    means "no scan" — the repaint nudge is a repair, and suppressing it forever
    because a predicate broke would resurrect the stale-surface bug it exists to
    fix. (The reverse failure — one skipped nudge during a run — costs at most a
    stale frame until the next re-assert.)"""
    provider = _scan_active_provider
    if provider is None:
        return False
    try:
        return bool(provider())
    except Exception:
        logger.debug("scan-active provider raised; assuming no scan",
                     exc_info=True)
        return False


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
    change THAT ACTUALLY CHANGES THE QSS (a real mode/colour/glass/
    typography edit) goes through :func:`apply_theme`'s
    ``app.setStyleSheet(...)``, and a stylesheet change unconditionally
    re-polishes the whole widget tree regardless of ``WA_SetPalette``
    (confirmed the same way: toggling to the other mode right after this
    reset still updates the window). A SAME-MODE re-assert is skipped by
    apply_theme's identical-QSS guard (Phase-0 fix 26538a4) — a no-op
    with nothing to repaint, so the skip cannot strand a
    ``WA_SetPalette``'d window.

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

    Theme-editor button corruption fix (2026-07-13): every ``_toggle_theme``
    call re-runs this for EVERY top-level window, unconditionally, even when
    the resolved kind is unchanged from what is already applied — the DWM
    reissue is deliberate (see the apply-order-contract tests in
    ``tests/test_backdrop.py``/``tests/test_theme_editor.py``, which assert
    the native calls fire on every apply, not just the first). While a real
    material is active, that reissue calls ``gui.backdrop._prepare_window_canvas``
    again, which re-touches ``WA_TranslucentBackground`` and replaces the
    window's OWN QPalette (Window role forced transparent) on an ALREADY
    shown, live-composited window. Nothing after that re-touch tells Qt to
    repaint: unlike the "none" branch below (whose ``_reassert_window_palette``
    forces an immediate :func:`repolish` specifically so a reset "never has to
    wait for some unrelated event to trigger the repaint that clears a stray
    default-Qt-grey frame" — the C1 risk note), the active-material branch had
    no equivalent safety net. On Windows, resetting a layered window's
    translucency attribute/palette can make DWM rebuild the surface; without a
    forced repaint request the widget tree already painted moments earlier (by
    ``apply_theme``'s stylesheet set, which always runs first) has no
    guarantee of being redrawn into that new surface before the next
    unrelated paint event — a stale/garbled frame (exactly "corrupted
    styling") until the user interacts with it. ``window.update()`` (not
    :func:`repolish` — ``tests/test_backdrop.py::
    test_backdrop_reassert_never_runs_while_a_real_material_is_applied`` pins
    that ``repolish`` must never fire on this branch, since THAT primitive is
    reserved for the palette-reset case) schedules the missing repaint without
    touching the palette the DWM material needs to show through.
    """
    return _apply_window_backdrop_to(window, kind, reason="apply")


def _apply_window_backdrop_to(window, kind: str | None = None, *,
                              reason: str = "apply") -> str:
    """:func:`apply_window_backdrop_to` with the truth-log ``reason`` tag the
    event spine passes ("show", "winidchange", "themechange", ...).

    RE-ENTRANCY (the loop this function must not close): the work below writes
    the window's palette (``_reassert_window_palette``) and repolishes it, and Qt
    delivers ``PaletteChange`` for exactly that — synchronously, to the very
    window whose event filter then wants to re-assert again. Without this guard
    the "none" branch recurses until the stack dies. A window already inside a
    re-assert simply skips the nested one: it is redundant by definition, the
    outer pass is mid-flight and will finish the job."""
    resolved = _window_backdrop if kind is None else kind
    if window in _reasserting_windows:
        return resolved
    _reasserting_windows.add(window)
    try:
        return _apply_window_backdrop_to_impl(window, resolved, reason)
    finally:
        _reasserting_windows.discard(window)


def _apply_window_backdrop_to_impl(window, resolved: str, reason: str) -> str:
    # Guard EVERY window this ever touches (idempotent): the DWM attributes are
    # per-HWND state, and Qt re-creates HWNDs behind our back — see
    # gui.backdrop._BackdropGuard. Installed even for kind == "none" so that
    # switching a material on later needs no second wiring pass.
    backdrop.install_backdrop_guard(
        window, _guard_reassert, _schedule_post_toggle_reassert)
    # Assert the DWM material's immersive-dark tint from the live theme mode so
    # Mica/Acrylic composes dark under the dark cockpit theme instead of DWM's
    # light default ("komplett weiss"). backdrop.py stays theme-blind; this is
    # where style.py — which owns the mode — relays it. Re-asserted on every
    # theme switch (apply_window_backdrop's fan-out runs after apply_theme in
    # _toggle_theme), so a dark<->light flip re-tints the material explicitly
    # rather than relying on a stylesheet-repolish side effect the identical-QSS
    # perf guard can skip.
    had_material = backdrop.window_has_material(window)
    applied = backdrop.reassert_backdrop(
        window, resolved, dark=(_active_mode == "dark"), reason=reason)
    if resolved == "none":
        # The palette resync exists for the material → "none" TRANSITION (the C1
        # risk-note fix). A spine-triggered re-assert (Show, WinIdChange, ...) on
        # a window that has no material and is not being switched has nothing to
        # undo — so it must not repolish. That keeps the event spine a TRUE no-op
        # in the shipped default configuration (backdrop "none"): zero repolish
        # churn on every show, zero risk to a suite that never asked for glass.
        if reason == "apply" or had_material:
            _reassert_window_palette(window)
            _repaint_central_widget(window)
    elif applied:
        window.update()
        _repaint_central_widget(window)
        # Stale-surface heal (Frigg/W4): a re-assert that follows an HWND or
        # surface recreation needs a REAL repaint, not just an update() — the
        # window can otherwise keep compositing the old backing store. Inert
        # headless and while the window is not on screen.
        #
        # SCAN GATE (Mary, G-B1 review, RISK 5): nudge_repaint resizes the
        # top-level by 1 px and back, which relayouts the whole dock tree, every
        # plot and the camera view on the GUI thread. A cosmetic repair must
        # never preempt a run — during a scan we skip it and let the NEXT
        # re-assert (the run ends, the user shows/restores a window, the next
        # theme touch) do the healing. Worst case while gated: one stale frame,
        # already opaque-by-construction under the underlay law.
        if scan_is_active():
            logger.debug(
                "glass: skipping the repaint nudge on %s — a scan is running "
                "(a cosmetic relayout must not preempt a run)",
                type(window).__name__)
        else:
            backdrop.nudge_repaint(window)
    return resolved


def prepare_window_surface(window) -> bool:
    """Call this as the FIRST line of a material-capable top-level's ``__init__``
    (before it builds children), so the window is guaranteed an alpha-capable
    native surface — on every material-capable HOST, regardless of the current
    backdrop PREFERENCE.

    Qt fixes a top-level's surface alpha when the native window is created. Any
    child that realizes the HWND first (``winId()``, a ``QQuickWidget``, an early
    ``show()``) permanently locks that window out of per-pixel alpha, and from
    then on the material attaches with S_OK and composites NOTHING — the failure
    that made the cockpit look glass-less while the freshly-built theme dialog
    looked fine (GL-island spike, finding 2).

    NO PREFERENCE GATE (Mary, G-B1 review, BUG 2 — this is the fix): gating the
    surface prep on ``_window_backdrop != "none"`` made the LIVE toggle
    unreachable by construction. With the shipped default ("none") every window
    was realized without ``WA_TranslucentBackground`` ⇒ ``alphaBufferSize == -1``
    for the life of that HWND. Picking "acrylic" in the theme editor then hit
    ``backdrop._renegotiate_alpha_surface``, which correctly REFUSES to destroy
    and re-create the native handle of a VISIBLE window (that would take the
    cockpit's native children with it) — so the already-open window could never
    gain alpha, and the user got nothing but a developer-facing log line. The
    surface is now negotiated up front for every window that COULD carry a
    material, and only the PIXELS stay gated on DWM success.

    That is safe by the module's own underlay law
    (``gui/backdrop.py:_set_glass_canvas``): "a translucent-capable surface
    painted with an opaque fill is simply an opaque window — harmless". In the
    shipped "none" default the QSS emits no ``[glassCanvas="true"]`` rule at all,
    ``gui.backdrop`` sets no ``glassCanvas`` property, and the unqualified canvas
    rule paints the OPAQUE ``p['bg']`` — so the window looks byte-identical; it
    merely *could* now show a material if one were ever attached. Pinned by
    ``tests/test_backdrop.py::
    test_default_backdrop_stays_visually_inert_even_though_the_surface_has_alpha``.

    ``gui.backdrop.prepare_surface`` still gates on
    :func:`gui.backdrop.is_backdrop_supported`, so Linux, macOS, pre-22H2
    Windows and the whole offscreen test suite are untouched.

    :func:`reassert_window_backdrop` runs the same prep, so a window that is
    still unrealized when it calls that is already safe; this exists for the ones
    that build a heavy child tree first (the cockpit, the device manager, a
    torn-off panel)."""
    return backdrop.prepare_surface(window)


def reassert_window_backdrop(window, *, reason: str = "apply") -> str:
    """THE single entry point for putting a top-level window into the material
    state the app is currently in: DWM chain first, then the WS_EX_LAYERED
    opacity pin — in that order, which is the apply-order contract.

    Every material-capable top-level goes through exactly this function — the
    cockpit (``tct_gui.TCTMainWindow``), the theme editor, the settings window,
    the device-manager window, and every torn-off panel
    (``gui.detachable_tabs._DetachedWindow``) — at construction, and again from
    the event spine whenever the window's native state could have dropped the
    attributes (``gui.backdrop._BackdropGuard``).

    Before this existed, each of those call sites hand-rolled
    ``apply_window_backdrop_to(w)`` + ``w.setWindowOpacity(get_window_opacity())``
    — and that second line pushed the RAW stored opacity, layering the window
    and killing the material it had just attached (see
    :func:`effective_window_opacity`).

    The re-entrancy lock spans BOTH steps: creating the native window (``winId``
    inside the DWM chain) delivers ``WinIdChange`` synchronously, straight back
    into this window's event filter. A nested pass that skipped the DWM chain
    (already locked) but still pushed ``setWindowOpacity`` would land the
    opacity BEFORE the material — inverting the apply-order contract from the
    inside."""
    if window in _reasserting_windows:
        return _window_backdrop
    _reasserting_windows.add(window)
    try:
        resolved = _apply_window_backdrop_to_impl(window, _window_backdrop, reason)
        window.setWindowOpacity(effective_window_opacity())
        return resolved
    finally:
        _reasserting_windows.discard(window)


def _guard_reassert(window, reason: str) -> None:
    """Callback injected into ``gui.backdrop``'s event filter — keeps that
    module theme-blind (it never imports style.py; the dependency runs one way
    only)."""
    reassert_window_backdrop(window, reason=reason)


def _repaint_central_widget(window) -> None:
    """Schedule a repaint of a ``QMainWindow``'s central widget (``#mainShell``)
    after its translucent-canvas prep was (re)touched by
    ``gui.backdrop._prepare_window_canvas`` / ``_clear_window_canvas`` — the
    opaque child that actually covers a QMainWindow client, mirroring the
    top-level ``window.update()`` belt-and-braces (9cdc970). ``window.update()``
    alone does not repaint children, so an already-shown ``#mainShell`` needs
    its own nudge to redraw into the now-translucent (or now-opaque again)
    surface. A no-op on a plain ``QWidget``/``QDialog`` (no ``centralWidget``)
    or a ``QMainWindow`` that has none yet."""
    getter = getattr(window, "centralWidget", None)
    if not callable(getter):
        return
    central = getter()
    if central is not None:
        central.update()


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

    TWO fixes from Mary's G-B1 review live here:

    * **BUG 1 — the QSS rebuild.** The glass-canvas rules
      (:func:`_glass_canvas_qss`) are emitted only while a material is preferred,
      so a LIVE ``none → acrylic`` flip genuinely changes the stylesheet. Nothing
      on the theme editor's backdrop path rebuilt it, so ``gui.backdrop`` set
      ``glassCanvas="true"`` on windows whose material had attached while the
      installed QSS had no rule behind that selector — the alpha hole never
      opened and the window kept painting the opaque ``p['bg']``. Glass only
      appeared if something *else* happened to rebuild the QSS (a dark/light
      toggle, a preset, a slider) or after a restart; ``scripts/glass_probe.py``
      hand-added an ``apply_theme`` call and so measured glass the product path
      could not show. The rebuild below runs BEFORE the per-window fan-out, so
      the rule exists by the time any window claims the property. It is skipped
      when the installed QSS was already built with this kind, and
      :func:`apply_theme`'s identical-QSS guard makes a redundant call
      (mica → acrylic: same rules) cost only a string build + compare.
    * **the opacity pin folded in.** The fan-out now goes through
      :func:`reassert_window_backdrop` — the SAME single entry point every
      construction site uses — so it applies the ``WS_EX_LAYERED`` pin itself
      instead of relying on every caller to remember a separate
      :func:`apply_window_opacity`. Callers still call it (harmless: the same
      effective value, and it also covers windows this fan-out skipped), but the
      invariant no longer rests on caller discipline.
    """
    from PySide6.QtWidgets import QApplication

    kind = _window_backdrop
    app = app if app is not None else QApplication.instance()
    if app is None:
        return kind
    if _qss_backdrop != kind:
        # The glass rule appears/disappears with the kind — rebuild first (see
        # BUG 1 above). Same mode: this is a backdrop change, not a theme change.
        apply_theme(app, _active_mode)
    for w in app.topLevelWidgets():
        if w.isWindow() and not _is_transient_window(w):
            reassert_window_backdrop(w)
    _schedule_post_toggle_reassert()
    return kind


def _schedule_post_toggle_reassert() -> None:
    """Re-assert the whole fan-out ONE event-loop turn later (Fenrir rider 2).

    Qt's own palette/colour-scheme heuristic can write
    ``DWMWA_USE_IMMERSIVE_DARK_MODE`` on a window AFTER we do, during the
    stylesheet repolish that a theme switch kicks off — last writer wins, and on
    that path the loser is our explicitly-asserted tint. Scheduling one more
    pass after the current event-loop turn puts us last.

    Three gates, all load-bearing:

    * no material preferred (the shipped default) ⇒ nothing to re-assert;
    * no real compositor (``is_backdrop_supported``) ⇒ nothing to re-assert —
      this is what keeps the headless suite from ever queueing a timer;
    * COALESCED — at most one pass may be pending. Without this, a caller that
      re-applies the backdrop in a loop (the theme editor's live preview; a test
      sweeping presets) queues one full fan-out per call, and the next
      ``processEvents()`` drains them all across every window that exists.

    The deferred pass calls the per-window apply directly — it never re-enters
    this function, so it cannot reschedule itself."""
    global _post_toggle_pending
    if _window_backdrop == "none" or not backdrop.is_backdrop_supported():
        return
    if _post_toggle_pending:
        return
    _post_toggle_pending = True
    QTimer.singleShot(0, _reassert_all_top_levels)


def _reassert_all_top_levels() -> None:
    global _post_toggle_pending
    _post_toggle_pending = False

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        try:
            if w.isWindow() and not _is_transient_window(w):
                reassert_window_backdrop(w, reason="post-toggle")
        except RuntimeError:        # window destroyed between turns
            continue


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
    global _canvas_alpha, _panel_glass_alpha, _post_toggle_pending
    _overrides["light"] = {}
    _overrides["dark"] = {}
    _glass_amount = DEFAULT_GLASS_AMOUNT
    _window_opacity = DEFAULT_WINDOW_OPACITY
    _window_backdrop = "none"
    _canvas_alpha = BACKDROP_CANVAS_ALPHA
    _panel_glass_alpha = PANEL_GLASS_ALPHA
    # The coalescing latch (Mary, G-B1 review, RISK 3). It is set BEFORE the
    # QTimer.singleShot that clears it, so if that timer never fires — shutdown,
    # or a caller/test that never drains the event loop — the flag latches True
    # and every future post-toggle re-assert is suppressed for the life of the
    # process. It is not a user preference, but this IS the "put the module back
    # to a known state" function (and the suite's autouse fixture), so a leaked
    # latch dies here instead of silently disarming the spine for later tests.
    _post_toggle_pending = False
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
    s.setValue(_SETTINGS_CANVAS_ALPHA_KEY, float(_canvas_alpha))
    s.setValue(_SETTINGS_PANEL_GLASS_ALPHA_KEY, float(_panel_glass_alpha))
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
    global _canvas_alpha, _panel_glass_alpha
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
    # Glass alphas go through their clamped setters, so a hand-edited registry
    # value below the scrim floor is raised to the floor, never obeyed (same
    # fail-safe philosophy as the opacity clamp). Absent -> shipped default.
    raw_canvas_alpha = s.value(_SETTINGS_CANVAS_ALPHA_KEY, None)
    if raw_canvas_alpha is None:
        _canvas_alpha = BACKDROP_CANVAS_ALPHA
    else:
        set_backdrop_canvas_alpha(raw_canvas_alpha)
    raw_panel_alpha = s.value(_SETTINGS_PANEL_GLASS_ALPHA_KEY, None)
    if raw_panel_alpha is None:
        _panel_glass_alpha = PANEL_GLASS_ALPHA
    else:
        set_panel_glass_alpha(raw_panel_alpha)
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
    canvas rule names shells instead of blanket-painting every QWidget.

    Idempotent by design: ``QApplication.setStyleSheet`` unconditionally
    re-polishes the ENTIRE live widget tree of every top-level window on every
    call — even when handed the byte-identical stylesheet it already has
    installed (measured: ~9 s for one such no-op set once ~13k widgets exist in
    the process). ``apply_theme`` is deliberately called as a same-mode
    *re-assert* in hot paths — once at boot after ``main.py`` already applied it,
    and again on every ``_reload_config`` soft-reload inside ``_build_central`` —
    where the resolved QSS is unchanged. So skip the set when the freshly-built
    QSS equals what is already installed: a genuine theme change (mode toggle,
    theme-editor override, glass/typography edit) always yields a *different*
    QSS and still triggers the full repolish exactly as before, while a pure
    re-assert costs only the (microsecond) string build+compare. Newly-built
    panels are unaffected — an app-level stylesheet applies to descendants when
    they are polished/shown regardless of whether ``setStyleSheet`` was re-called,
    so no panel loses its styling. This turns the repeated-soft-reload path from
    O(cumulative-tree) per cycle into O(new-subtree), the root fix for the
    QML-shell repeated-reload regression (bench PHASE 0)."""
    global _active_mode, _qss_backdrop
    palette = DARK if str(mode).lower() == "dark" else LIGHT
    _active_mode = "dark" if palette is DARK else "light"
    _apply_app_font(app)
    _apply_app_palette(app, palette)
    qss = build_qss(palette)
    if app.styleSheet() != qss:
        app.setStyleSheet(qss)
    # Remember which backdrop kind THIS stylesheet carries the glass rules for —
    # apply_window_backdrop compares against it and rebuilds when a live toggle
    # makes them appear/disappear (Mary, G-B1 review, BUG 1). Recorded even when
    # the identical-QSS guard skipped the set: the installed sheet still matches
    # this kind (that is exactly why it was identical).
    _qss_backdrop = _window_backdrop
    _apply_pyqtgraph(palette)
    return _active_mode
