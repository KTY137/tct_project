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

# Corner-radius scale (px)
RADIUS_XS = 4     # menus / tooltips
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 10
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

MONO_FAMILY = '"Consolas", "Cascadia Mono", "Courier New", monospace'

# ---------------------------------------------------------------------------
# Shared accent — scope-cyan (was blue #2d7ff9).  Reads as an oscilloscope
# trace; ``accent_strong`` is the deeper hover/pressed/default-fill variant.
# ---------------------------------------------------------------------------
ACCENT_LIGHT = "#0d8ba6"
ACCENT_LIGHT_STRONG = "#0a6b80"
ACCENT_DARK = "#33c8ff"
ACCENT_DARK_STRONG = "#12a7e0"

# Status accents (shared by both themes — readable on either base).  Kept as
# the historical names *and* exposed through the palette as good/warn/crit.
OK_GREEN = "#27ae60"
WARN_AMBER = "#d98c17"
WARN_RED = "#c0392b"

# General amber token (distinct from the warn status colour): matches the
# bias axis-rail hue so a "bias" accent is amber everywhere.
AMBER_LIGHT = "#C67F14"
AMBER_DARK = "#E8A33D"

LIGHT = {
    "accent": ACCENT_LIGHT, "accent_strong": ACCENT_LIGHT_STRONG,
    "amber": AMBER_LIGHT,
    "good": OK_GREEN, "warn": WARN_AMBER, "crit": WARN_RED,
    "bg": "#f4f6f9", "panel": "#ffffff", "border": "#d6dbe3",
    "text": "#1f2a37", "muted": "#6b7280",
    "pressed": "#e6f4f8", "disabled_bg": "#f0f1f3",
}

DARK = {
    "accent": ACCENT_DARK, "accent_strong": ACCENT_DARK_STRONG,
    "amber": AMBER_DARK,
    "good": OK_GREEN, "warn": WARN_AMBER, "crit": WARN_RED,
    "bg": "#1f242b", "panel": "#272d36", "border": "#3a424d",
    "text": "#e6e9ee", "muted": "#9aa4b2",
    "pressed": "#243743", "disabled_bg": "#2b313a",
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


def build_qss(p: dict) -> str:
    return f"""
* {{
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
    font-size: {FONT_MD}px;
    color: {p['text']};
}}

QMainWindow, QDialog, QWidget {{ background: {p['bg']}; }}

/* Group boxes: card-like with breathing room */
QGroupBox {{
    background: {p['panel']};
    border: 1px solid {p['border']};
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
    font-weight: 600;
}}

/* Inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p['panel']};
    border: 1px solid {p['border']};
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS}px {SPACE_SM}px;
    selection-background-color: {p['accent']};
    selection-color: white;
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p['panel']};
    border: 1px solid {p['border']};
    selection-background-color: {p['accent']};
    selection-color: white;
}}

/* Buttons */
QPushButton {{
    background: {p['panel']};
    border: 1px solid {p['border']};
    border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS + 2}px {SPACE_LG - 2}px;
}}
QPushButton:hover {{ border-color: {p['accent']}; }}
QPushButton:pressed {{ background: {p['pressed']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['disabled_bg']}; }}
QPushButton:default {{
    background: {p['accent']}; color: white; border: 1px solid {p['accent_strong']};
}}
QPushButton:default:hover {{ background: {p['accent_strong']}; }}
QPushButton[state="busy"] {{
    background: {_rgba(p['accent'], 0.16)}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.55)};
}}
QPushButton[state="good"] {{
    background: {_rgba(p['good'], 0.16)}; color: {p['good']};
    border: 1px solid {_rgba(p['good'], 0.55)};
}}
QPushButton[state="warn"], QPushButton#armedBtn {{
    background: {_rgba(p['warn'], 0.18)}; color: {p['warn']};
    border: 1px solid {_rgba(p['warn'], 0.65)};
    font-weight: 700;
}}
QPushButton[state="crit"] {{
    background: {_rgba(p['crit'], 0.16)}; color: {p['crit']};
    border: 1px solid {_rgba(p['crit'], 0.55)};
}}

/* Accent buttons by objectName (toolbar Connect/Disconnect) */
QPushButton#connectBtn, QToolButton#connectBtn {{
    background: {p['good']}; color: white; border: 1px solid {p['good']};
}}
QPushButton#disconnectBtn, QToolButton#disconnectBtn {{
    background: {p['crit']}; color: white; border: 1px solid {p['crit']};
}}
QPushButton#connectBtn:disabled, QToolButton#connectBtn:disabled,
QPushButton#disconnectBtn:disabled, QToolButton#disconnectBtn:disabled {{
    background: {p['disabled_bg']}; color: {p['muted']}; border: 1px solid {p['border']};
}}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid {p['border']}; border-radius: {RADIUS_MD}px; top: -1px; background: {p['bg']};
}}
QTabBar::tab {{
    background: transparent; padding: {SPACE_SM}px {SPACE_LG}px; margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: {RADIUS_SM + 1}px; border-top-right-radius: {RADIUS_SM + 1}px;
    color: {p['muted']};
}}
QTabBar::tab:selected {{
    background: {p['panel']}; color: {p['text']};
    border: 1px solid {p['border']}; border-bottom-color: {p['panel']}; font-weight: 600;
}}
QTabBar::tab:hover:!selected {{ color: {p['text']}; }}

/* Menu / toolbar */
QMenuBar {{ background: {p['panel']}; border-bottom: 1px solid {p['border']}; }}
QMenuBar::item:selected {{ background: {p['accent']}; color: white; border-radius: {RADIUS_XS}px; }}
QMenu {{ background: {p['panel']}; border: 1px solid {p['border']}; }}
QMenu::item:selected {{ background: {p['accent']}; color: white; }}
QToolBar {{ background: {p['panel']}; border-bottom: 1px solid {p['border']}; spacing: {SPACE_SM - 2}px; padding: {SPACE_XS}px; }}

/* Status bar + dock titles */
QStatusBar {{ background: {p['panel']}; border-top: 1px solid {p['border']}; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {p['panel']}; padding: {SPACE_SM - 2}px {SPACE_MD - 2}px;
    border: 1px solid {p['border']}; border-radius: {RADIUS_SM}px;
}}

QCheckBox {{ spacing: {SPACE_SM}px; }}
QScrollArea {{ border: none; background: {p['bg']}; }}
QToolTip {{
    background: {p['text']}; color: {p['bg']}; border: none;
    padding: {SPACE_XS}px {SPACE_SM}px; border-radius: {RADIUS_XS}px;
}}

/* Danger action button (STOP / immediate hardware abort). Same red language
   as the toolbar Disconnect button, under its own name so any panel can mark
   an "abort now" control this way without borrowing the connect/disconnect
   semantics. */
QPushButton#dangerBtn {{
    background: {p['crit']}; color: white; border: 1px solid {p['crit']};
    font-weight: 700;
}}
QPushButton#dangerBtn:hover {{ background: #a93226; border-color: #a93226; }}
QPushButton#dangerBtn:pressed {{ background: #922b21; }}
QPushButton#dangerBtn:disabled {{
    background: {p['disabled_bg']}; color: {p['muted']}; border: 1px solid {p['border']};
}}

/* Digital readout (e.g. motor position) — a dark instrument screen like the
   plot canvas, so live numbers read as an instrument display rather than a
   plain label. Values use a monospace face for tabular alignment. */
QFrame#instrumentReadout {{
    background: {PLOT_BG}; border: 1px solid {p['border']}; border-radius: {RADIUS_MD}px;
}}
QLabel#readoutAxis {{ color: {PLOT_FG}; font-size: {FONT_XS}px; font-weight: 700; }}
QLabel#readoutValue {{
    color: {p['accent']};
    font-family: {MONO_FAMILY};
    font-size: {FONT_XL}px; font-weight: 600;
}}
QFrame#readoutCell {{
    background: {PLOT_BG}; border: 1px solid {p['border']}; border-radius: {RADIUS_SM}px;
}}
QLabel#readoutCellTitle {{
    color: {PLOT_FG}; font-size: {FONT_XS}px; font-weight: 700;
}}
QLabel#readoutCellValue {{
    color: {p['accent']}; font-family: {MONO_FAMILY};
    font-size: {FONT_SM}px; font-weight: 700;
}}

/* Recessed control cluster — groups related buttons (e.g. a jog pad) into
   one visual unit inside a QGroupBox, the way a physical jog controller
   reads as a single control rather than loose buttons in a form. */
QFrame#controlCluster {{
    background: {p['bg']}; border: 1px solid {p['border']}; border-radius: {RADIUS_LG}px;
}}
QLabel#clusterCaption {{ color: {p['muted']}; font-size: {FONT_XS}px; font-weight: 700; }}

/* Jog pad buttons — compact, square-ish directional keys inside a cluster. */
QPushButton#jogBtn {{
    min-width: 34px; min-height: 30px; font-weight: 700;
    padding: {SPACE_XS}px;
}}
QPushButton#jogBtn:hover {{ border-color: {p['accent']}; color: {p['accent']}; }}
QPushButton#jogBtn:pressed {{ background: {p['pressed']}; }}

/* Segmented control — exclusive preset buttons (e.g. jog step size) styled
   as one pill-shaped group with a clear selected segment. */
QFrame#segmented {{
    background: {p['panel']}; border: 1px solid {p['border']}; border-radius: {RADIUS_MD}px;
}}
QPushButton#segBtn {{
    background: transparent; border: none; border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS + 1}px {SPACE_SM + 2}px; color: {p['muted']}; font-weight: 600;
}}
QPushButton#segBtn:hover:!checked {{ background: {p['pressed']}; color: {p['text']}; }}
QPushButton#segBtn:checked {{ background: {p['accent']}; color: white; }}
QPushButton#segBtn:disabled {{ color: {p['muted']}; background: transparent; }}

/* Card wrapper matching QGroupBox's look, for non-groupbox panes that must
   sit visually level with group boxes (e.g. a live view beside a controls
   column). */
QFrame#cardPane {{
    background: {p['panel']}; border: 1px solid {p['border']}; border-radius: {RADIUS_MD}px;
}}

/* Channel card — a cardPane variant used per scope channel.  The panel adds an
   inline coloured left border per channel; this is the shared base look. */
QFrame#channelCard {{
    background: {p['panel']}; border: 1px solid {p['border']}; border-radius: {RADIUS_SM}px;
}}

/* Eyebrow — a small caption label above a heading/value.  QSS cannot
   uppercase text, so the panel should pass already-uppercased text; this
   styles it small, muted and bold. */
QLabel#eyebrow {{
    color: {p['muted']}; font-size: {FONT_XS}px; font-weight: 700;
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
    background: {p['pressed']}; color: {p['muted']};
    border: 1px solid {p['border']};
}}
QLabel#statusChip[state="neutral"] {{
    background: {p['pressed']}; color: {p['muted']}; border: 1px solid {p['border']};
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
    background: {_rgba(p['accent'], 0.14)}; color: {p['accent']};
    border: 1px solid {_rgba(p['accent'], 0.50)};
}}
QLabel#statusChip[state="armed"] {{
    background: {_rgba(p['warn'], 0.20)}; color: {p['warn']};
    border: 1px solid {_rgba(p['warn'], 0.70)};
}}
QLabel#statusChip[state="simulated"] {{
    background: rgba(142, 68, 173, 0.16); color: #8e44ad;
    border: 1px solid rgba(142, 68, 173, 0.55);
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
QFrame#statusLamp[state="simulated"] {{ background: #8e44ad; }}

QFrame#statusPill {{
    background: {p['panel']}; border: 1px solid {p['border']};
    border-radius: {RADIUS_PILL}px;
}}
QFrame#statusPill[state="good"] {{ border-color: {_rgba(p['good'], 0.55)}; }}
QFrame#statusPill[state="warn"], QFrame#statusPill[state="armed"] {{ border-color: {_rgba(p['warn'], 0.60)}; }}
QFrame#statusPill[state="crit"] {{ border-color: {_rgba(p['crit'], 0.60)}; }}
QFrame#statusPill[state="info"], QFrame#statusPill[state="busy"] {{ border-color: {_rgba(p['accent'], 0.55)}; }}
QFrame#statusPill[state="simulated"] {{ border-color: rgba(142, 68, 173, 0.60); }}
QLabel#statusPillText {{
    font-size: {FONT_XS}px; font-weight: 700; color: {p['text']};
}}

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
    letter-spacing: 0.06em; padding: 2px {SPACE_XS + 2}px; border-radius: {RADIUS_XS}px;
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
    letter-spacing: 0.04em; padding: 2px {SPACE_SM}px; border-radius: {RADIUS_PILL}px;
}}
"""


# Plot canvas: a dark "instrument screen" in BOTH themes so the plot area never
# blends into the (white) light UI and reads clearly as a plot even when empty.
PLOT_BG = "#0e1116"
PLOT_FG = "#c8cdd6"


def _apply_pyqtgraph(p: dict) -> None:
    """Give pyqtgraph plots a dark canvas + grid so they're always visible."""
    try:
        import pyqtgraph as pg
        from PySide6.QtWidgets import QApplication
    except Exception:
        return
    pg.setConfigOption("background", PLOT_BG)   # default for plots built later
    pg.setConfigOption("foreground", PLOT_FG)
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        if isinstance(w, pg.PlotWidget):
            try:
                w.setBackground(PLOT_BG)
                w.showGrid(x=True, y=True, alpha=0.25)   # empty plot still looks like a plot
            except Exception:
                pass


def apply_theme(app, mode: str = "light") -> str:
    """Apply the global stylesheet for *mode* ('light'|'dark'). Returns the mode."""
    palette = DARK if str(mode).lower() == "dark" else LIGHT
    app.setStyleSheet(build_qss(palette))
    _apply_pyqtgraph(palette)
    return "dark" if palette is DARK else "light"
