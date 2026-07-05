"""
Application-wide visual style — light and dark themes.

A single QSS template is rendered against a palette dict, so light/dark share
exactly the same layout/spacing and only the colours differ.  Applied via
``apply_theme(app, mode)`` from ``main.py`` and toggled live from the View menu.
"""
from __future__ import annotations

# Shared accent
ACCENT = "#2d7ff9"
ACCENT_DARK = "#1b66d6"

LIGHT = {
    "accent": ACCENT, "accent_dark": ACCENT_DARK,
    "bg": "#f4f6f9", "panel": "#ffffff", "border": "#d6dbe3",
    "text": "#1f2a37", "muted": "#6b7280",
    "pressed": "#eef4ff", "disabled_bg": "#f0f1f3",
}

DARK = {
    "accent": ACCENT, "accent_dark": ACCENT_DARK,
    "bg": "#1f242b", "panel": "#272d36", "border": "#3a424d",
    "text": "#e6e9ee", "muted": "#9aa4b2",
    "pressed": "#2f3a4d", "disabled_bg": "#2b313a",
}

# Status accents (shared by both themes — readable on either base)
OK_GREEN = "#27ae60"
WARN_RED = "#c0392b"


def build_qss(p: dict) -> str:
    return f"""
* {{
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
    font-size: 13px;
    color: {p['text']};
}}

QMainWindow, QDialog, QWidget {{ background: {p['bg']}; }}

/* Group boxes: card-like with breathing room */
QGroupBox {{
    background: {p['panel']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 12px 10px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 2px 6px;
    color: {p['muted']};
    font-weight: 600;
}}

/* Inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p['panel']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 4px 8px;
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
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {p['accent']}; }}
QPushButton:pressed {{ background: {p['pressed']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['disabled_bg']}; }}
QPushButton:default {{
    background: {p['accent']}; color: white; border: 1px solid {p['accent_dark']};
}}
QPushButton:default:hover {{ background: {p['accent_dark']}; }}

/* Accent buttons by objectName (toolbar Connect/Disconnect) */
QPushButton#connectBtn, QToolButton#connectBtn {{
    background: {OK_GREEN}; color: white; border: 1px solid {OK_GREEN};
}}
QPushButton#disconnectBtn, QToolButton#disconnectBtn {{
    background: {WARN_RED}; color: white; border: 1px solid {WARN_RED};
}}
QPushButton#connectBtn:disabled, QToolButton#connectBtn:disabled,
QPushButton#disconnectBtn:disabled, QToolButton#disconnectBtn:disabled {{
    background: {p['disabled_bg']}; color: {p['muted']}; border: 1px solid {p['border']};
}}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid {p['border']}; border-radius: 8px; top: -1px; background: {p['bg']};
}}
QTabBar::tab {{
    background: transparent; padding: 8px 16px; margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: 7px; border-top-right-radius: 7px;
    color: {p['muted']};
}}
QTabBar::tab:selected {{
    background: {p['panel']}; color: {p['text']};
    border: 1px solid {p['border']}; border-bottom-color: {p['panel']}; font-weight: 600;
}}
QTabBar::tab:hover:!selected {{ color: {p['text']}; }}

/* Menu / toolbar */
QMenuBar {{ background: {p['panel']}; border-bottom: 1px solid {p['border']}; }}
QMenuBar::item:selected {{ background: {p['accent']}; color: white; border-radius: 4px; }}
QMenu {{ background: {p['panel']}; border: 1px solid {p['border']}; }}
QMenu::item:selected {{ background: {p['accent']}; color: white; }}
QToolBar {{ background: {p['panel']}; border-bottom: 1px solid {p['border']}; spacing: 6px; padding: 4px; }}

/* Status bar + dock titles */
QStatusBar {{ background: {p['panel']}; border-top: 1px solid {p['border']}; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {p['panel']}; padding: 6px 10px;
    border: 1px solid {p['border']}; border-radius: 6px;
}}

QCheckBox {{ spacing: 8px; }}
QScrollArea {{ border: none; background: {p['bg']}; }}
QToolTip {{
    background: {p['text']}; color: {p['bg']}; border: none;
    padding: 4px 8px; border-radius: 4px;
}}

/* Danger action button (STOP / immediate hardware abort). Same red language
   as the toolbar Disconnect button, under its own name so any panel can mark
   an "abort now" control this way without borrowing the connect/disconnect
   semantics. */
QPushButton#dangerBtn {{
    background: {WARN_RED}; color: white; border: 1px solid {WARN_RED};
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
    background: {PLOT_BG}; border: 1px solid {p['border']}; border-radius: 8px;
}}
QLabel#readoutAxis {{ color: {PLOT_FG}; font-size: 11px; font-weight: 700; }}
QLabel#readoutValue {{
    color: {p['accent']};
    font-family: "Consolas", "Cascadia Mono", "Courier New", monospace;
    font-size: 20px; font-weight: 600;
}}

/* Recessed control cluster — groups related buttons (e.g. a jog pad) into
   one visual unit inside a QGroupBox, the way a physical jog controller
   reads as a single control rather than loose buttons in a form. */
QFrame#controlCluster {{
    background: {p['bg']}; border: 1px solid {p['border']}; border-radius: 10px;
}}
QLabel#clusterCaption {{ color: {p['muted']}; font-size: 11px; font-weight: 700; }}

/* Segmented control — exclusive preset buttons (e.g. jog step size) styled
   as one pill-shaped group with a clear selected segment. */
QFrame#segmented {{
    background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 8px;
}}
QPushButton#segBtn {{
    background: transparent; border: none; border-radius: 6px;
    padding: 5px 10px; color: {p['muted']}; font-weight: 600;
}}
QPushButton#segBtn:hover:!checked {{ background: {p['pressed']}; color: {p['text']}; }}
QPushButton#segBtn:checked {{ background: {p['accent']}; color: white; }}
QPushButton#segBtn:disabled {{ color: {p['muted']}; background: transparent; }}

/* Card wrapper matching QGroupBox's look, for non-groupbox panes that must
   sit visually level with group boxes (e.g. a live view beside a controls
   column). */
QFrame#cardPane {{
    background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 8px;
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
