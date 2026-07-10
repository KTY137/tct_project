"""
Application-wide visual style — light and dark themes.

A single QSS template is rendered against a palette dict, so light/dark share
exactly the same layout/spacing and only the colours differ.  Applied via
``apply_theme(app, mode)`` from ``main.py`` and toggled live from the View menu.

This module is the design-system foundation (Milestone 2.1).  Components should
reference the shared *tokens* below (accent/status colours, spacing, radius and
type scales, axis-rail palette) instead of hardcoding magic numbers or colours.
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

# Type scale (px)
FONT_XS = 11
FONT_SM = 12
FONT_MD = 13
FONT_LG = 16
FONT_XL = 20
FONT = {"xs": FONT_XS, "sm": FONT_SM, "md": FONT_MD, "lg": FONT_LG, "xl": FONT_XL}

MONO_FAMILY = '"Consolas", "Cascadia Mono", "Cascadia Code", "Courier New", monospace'

# ---------------------------------------------------------------------------
# Shared accent — scope-cyan (was blue #2d7ff9).  Reads as an oscilloscope
# trace; ``accent_strong`` is the deeper hover/pressed/default-fill variant.
# ---------------------------------------------------------------------------
ACCENT_LIGHT = "#0e7fa6"
ACCENT_LIGHT_STRONG = "#0a678a"
ACCENT_DARK = "#41c8f0"
ACCENT_DARK_STRONG = "#2fa8cd"

# Status accents. The exported names remain available for existing panel code
# that imports a single fixed semantic colour; the palette below uses theme-
# tuned light/dark values for the global QSS.
OK_GREEN = "#30d158"
WARN_AMBER = "#ffa01e"
WARN_RED = "#ff4f47"
OK_GREEN_LIGHT = "#1e9e46"
WARN_AMBER_LIGHT = "#c77000"
WARN_RED_LIGHT = "#d93a32"

# Device-manager status accents (gui/device_panel.py's ``_STATUS_STYLE``) —
# two more fixed-both-themes status colours alongside OK_GREEN/WARN_AMBER/
# WARN_RED above: "simulated" (purple — matches the existing
# ``statusChip``/``statusLamp[state="simulated"]`` hue in ``build_qss``
# below) and "error" (a hard device error, distinct from the general
# WARN_AMBER "warn" look).
SIM_PURPLE = "#bf8cff"
SIM_PURPLE_LIGHT = "#7d55d8"
ERROR_ORANGE = "#ff8a1f"
ERROR_ORANGE_LIGHT = "#d96c00"

# General amber token (distinct from the warn status colour): matches the
# bias axis-rail hue so a "bias" accent is amber everywhere.
AMBER_LIGHT = "#C67F14"
AMBER_DARK = "#E8A33D"

LIGHT = {
    "accent": ACCENT_LIGHT, "accent_strong": ACCENT_LIGHT_STRONG,
    "amber": AMBER_LIGHT,
    "good": OK_GREEN_LIGHT, "warn": WARN_AMBER_LIGHT, "crit": WARN_RED_LIGHT,
    "sim": SIM_PURPLE_LIGHT, "error": ERROR_ORANGE_LIGHT,
    "canvas": "#eef0f4", "bg": "#eef0f4",
    "material": "#ffffff", "material_strong": "#ffffff",
    "panel": "#ffffff", "border": "#d6dbe3",
    "hairline": "#dfe4ec", "hairline_strong": "#b9c2cf",
    "toplight": "#ffffff",
    "text": "#1b1d22", "muted": "#5c626e", "faint": "#9aa0ab",
    "on_accent": "#ffffff", "tint": "#d9edf3",
    "field": "#f2f4f7", "pressed": "#e4e8ee", "disabled_bg": "#eceff3",
    # Cockpit kit (Phase 0, docs/design/cockpit_style_overhaul.md §2) —
    # additive layering/emphasis tokens. panel_2/panel_3 step progressively
    # deeper than "panel" (nested card bodies); "sunk" is a recessed/inset
    # surface (input wells, dial recesses); "border_strong" is an emphasized
    # border for hover/active/focus rings; "hover"/"active" are neutral
    # interaction washes distinct from the accent-tinted "pressed" above.
    "panel_2": "#f6f7f9", "panel_3": "#eef0f4", "sunk": "#e8ebf0",
    "border_strong": "#b9c2cf", "hover": "#e8ebf0", "active": "#d9edf3",
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
    "canvas": "#131316", "bg": "#131316",
    "material": "#1e1e22", "material_strong": "#18181b",
    "panel": "#1d1d21", "border": "#33343a",
    "hairline": "#33343a", "hairline_strong": "#4a4d56",
    "toplight": "#292a2f",
    "text": "#f2f3f5", "muted": "#a3a8b3", "faint": "#63676f",
    "on_accent": "#04222c", "tint": "#18343d",
    "field": "#2a2b31", "pressed": "#30323a", "disabled_bg": "#25262b",
    # See the matching comment in LIGHT above.
    "panel_2": "#242429", "panel_3": "#2b2b31", "sunk": "#0f1012",
    "border_strong": "#4a4d56", "hover": "#2c2d34", "active": "#18343d",
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


def _rgba(hex_color: str, alpha: float) -> str:
    """Hex ``#rrggbb`` -> ``rgba(r,g,b,alpha)`` for translucent QSS fills."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _darken(hex_color: str, amount: float = 0.15) -> str:
    """Hex ``#rrggbb`` darkened toward black by *amount* (0..1).

    Used for hover/pressed shades of solid accent buttons (connect/disconnect/
    danger) so those states derive from the same token instead of a separately
    hand-picked hex — one source of truth per colour.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = max(0, min(255, int(r * (1 - amount))))
    g = max(0, min(255, int(g * (1 - amount))))
    b = max(0, min(255, int(b * (1 - amount))))
    return f"#{r:02x}{g:02x}{b:02x}"


def build_qss(p: dict) -> str:
    return f"""
* {{
    font-family: "Segoe UI", "Inter var", "Inter", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
    font-size: {FONT_MD}px;
    color: {p['text']};
}}

QMainWindow, QDialog, QWidget {{ background: {p['bg']}; }}

/* Group boxes: card-like with breathing room. The title is a section header —
   a touch heavier and a hair tighter in tracking than body text so it reads
   as a designed heading rather than a bigger label (size is unchanged). */
QGroupBox {{
    background: {p['panel']};
    border: 1px solid {p['hairline']};
    border-radius: {RADIUS_MD}px;
    margin-top: {SPACE_LG - 2}px;
    padding: {SPACE_MD}px {SPACE_MD}px {SPACE_SM + 2}px {SPACE_MD}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {SPACE_MD}px;
    padding: 2px {SPACE_SM - 2}px;
    color: {p['muted']};
    font-weight: 700;
    letter-spacing: 0;
}}

/* Inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p['field']};
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS}px {SPACE_SM}px;
    selection-background-color: {p['accent']};
    selection-color: {p['on_accent']};
}}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {p['border_strong']}; background: {p['hover']}; }}
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

/* Buttons */
QPushButton {{
    background: {p['field']};
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS + 2}px {SPACE_LG - 2}px;
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

/* Accent buttons by objectName (toolbar Connect/Disconnect). Hover/pressed
   shades are derived from the same good/crit token via _darken() so there is
   one source of truth per colour instead of a separately hand-picked hex. */
QPushButton#connectBtn, QToolButton#connectBtn {{
    background: {p['good']}; color: white; border: 1px solid {p['good']};
}}
QPushButton#connectBtn:hover, QToolButton#connectBtn:hover {{
    background: {_darken(p['good'], 0.12)}; border-color: {_darken(p['good'], 0.12)};
}}
QPushButton#connectBtn:pressed, QToolButton#connectBtn:pressed {{
    background: {_darken(p['good'], 0.22)};
}}
QPushButton#disconnectBtn, QToolButton#disconnectBtn {{
    background: {p['crit']}; color: white; border: 1px solid {p['crit']};
}}
QPushButton#disconnectBtn:hover, QToolButton#disconnectBtn:hover {{
    background: {_darken(p['crit'], 0.12)}; border-color: {_darken(p['crit'], 0.12)};
}}
QPushButton#disconnectBtn:pressed, QToolButton#disconnectBtn:pressed {{
    background: {_darken(p['crit'], 0.22)};
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
    color: {p['muted']};
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
    font-weight: 700; font-size: {FONT_XS}px; letter-spacing: 0;
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

/* Digital readout (e.g. motor position) — a dark instrument screen like the
   plot canvas, so live numbers read as an instrument display rather than a
   plain label. Values use a monospace face for tabular alignment. */
QFrame#instrumentReadout {{
    background: {PLOT_BG}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_MD}px;
}}
QLabel#readoutAxis {{
    color: {PLOT_FG}; font-size: {FONT_XS}px; font-weight: 700; letter-spacing: 0;
}}
QLabel#readoutValue {{
    color: {p['accent']};
    font-family: {MONO_FAMILY};
    font-size: {FONT_XL}px; font-weight: 600;
}}
QFrame#readoutCell {{
    background: {PLOT_BG}; border: 1px solid {p['hairline']}; border-radius: {RADIUS_SM}px;
}}
QLabel#readoutCellTitle {{
    color: {PLOT_FG}; font-size: {FONT_XS}px; font-weight: 700; letter-spacing: 0;
}}
QLabel#readoutCellValue {{
    color: {p['accent']}; font-family: {MONO_FAMILY};
    font-size: {FONT_SM}px; font-weight: 700;
}}
/* Tri-state (+ "armed") value-colour hook — drive with a dynamic ``state``
   property in {{good, warn, crit}} via gui.status_widgets.ReadoutCell.set_state()
   (or {{normal, warn, armed}} via gui.panel_kit.MetricTile, which is built on
   ReadoutCell and reuses this exact hook). "normal"/no property falls through
   to the bare rule above, the same graceful-unknown idiom as statusChip. */
QLabel#readoutCellValue[state="good"] {{ color: {p['good']}; }}
QLabel#readoutCellValue[state="warn"] {{ color: {p['warn']}; }}
QLabel#readoutCellValue[state="crit"] {{ color: {p['crit']}; }}
QLabel#readoutCellValue[state="armed"] {{ color: {p['warn']}; font-weight: 800; }}
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
QLabel#clusterCaption {{
    color: {p['muted']}; font-size: {FONT_XS}px; font-weight: 700; letter-spacing: 0;
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
QLabel#eyebrow {{
    color: {p['faint']}; font-size: {FONT_XS}px; font-weight: 700; letter-spacing: 0;
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
   dynamic property ``state`` in {{neutral, good, warn, crit}}.  To restyle live
   after changing the property, unpolish THEN polish (polish alone can keep the
   old look when transitioning between two non-default states):
       chip.setProperty("state", "good")
       chip.style().unpolish(chip); chip.style().polish(chip)
   Any unlisted state value falls through to the quiet neutral pill. */
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
QLabel#statusChip[state="good"] {{
    background: {_rgba(p['good'], 0.16)}; color: {p['good']};
    border: 1px solid {_rgba(p['good'], 0.55)};
}}
QLabel#statusChip[state="warn"] {{
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
QLabel#statusChip[state="armed"] {{
    background: {_rgba(p['warn'], 0.20)}; color: {p['warn']};
    border: 1px solid {_rgba(p['warn'], 0.70)};
}}
QLabel#statusChip[state="simulated"] {{
    background: {_rgba(p['sim'], 0.16)}; color: {p['sim']};
    border: 1px solid {_rgba(p['sim'], 0.55)};
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

QFrame#statusLamp {{
    min-width: 9px; max-width: 9px; min-height: 9px; max-height: 9px;
    border-radius: 4px; background: {p['muted']};
}}
QFrame#statusLamp[state="neutral"] {{ background: {p['muted']}; }}
QFrame#statusLamp[state="good"] {{ background: {p['good']}; }}
QFrame#statusLamp[state="warn"], QFrame#statusLamp[state="armed"] {{ background: {p['warn']}; }}
QFrame#statusLamp[state="crit"] {{ background: {p['crit']}; }}
QFrame#statusLamp[state="info"], QFrame#statusLamp[state="busy"] {{ background: {p['accent']}; }}
QFrame#statusLamp[state="simulated"] {{ background: {p['sim']}; }}

QFrame#statusPill {{
    background: {p['material']}; border: 1px solid {p['hairline']};
    border-radius: {RADIUS_PILL}px;
}}
QFrame#statusPill[state="good"] {{ border-color: {_rgba(p['good'], 0.55)}; }}
QFrame#statusPill[state="warn"], QFrame#statusPill[state="armed"] {{ border-color: {_rgba(p['warn'], 0.60)}; }}
QFrame#statusPill[state="crit"] {{ border-color: {_rgba(p['crit'], 0.60)}; }}
QFrame#statusPill[state="info"], QFrame#statusPill[state="busy"] {{ border-color: {_rgba(p['accent'], 0.55)}; }}
QFrame#statusPill[state="simulated"] {{ border-color: {_rgba(p['sim'], 0.60)}; }}
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
