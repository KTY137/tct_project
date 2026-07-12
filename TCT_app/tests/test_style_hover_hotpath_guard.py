"""Guards for the 2026-07-12 regression triage (post-094f211 live review).

Two regression classes, one test file:

1. HOVER — "what's interactive must look interactive". In QML-shell mode the
   native tab bar is hidden (``gui/qml_shell.py``: ``tabs.tabBar().hide()``),
   so the Shell.qml pill shelf IS the app's tab bar — and it shipped without
   any hover state, which read as "tab hover highlighting is GONE" (and made
   the whole chrome feel laggy/inert). These tests pin the hover affordances
   in Shell.qml (source-level, same idiom as the zero-inline-hex QML test)
   and the QTabBar hover rule in the QSS.

2. HOT-PATH BORDERS — hard rule 3 (docs/design/cockpit_style_overhaul.md §1):
   no extra paint cost on hot-path widgets. Per-side border colors
   (``border-top-color`` machined edges) force Qt's slow four-edge border
   path on every repaint, so they are banned on the selectors that repaint at
   runtime rates: plot/camera containers (QGroupBox, cardPane, channelCard),
   live readouts (readoutCell, instrumentReadout), progress bars, and the
   scrolling multiline editors (QPlainTextEdit/QTextEdit — the log view).
   They stay allowed on static chrome (ribbon, dock titles) and
   interaction-only controls (buttons, tabs, segments).

Pure string/QSS checks — no QApplication needed, safe headless.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gui.style import DARK, LIGHT, build_qss

SHELL_QML = (Path(__file__).parent.parent / "gui" / "qml" / "Shell.qml").read_text(
    encoding="utf-8")


def _rules(qss: str) -> list[tuple[str, str]]:
    """Split a (flat, non-nested) QSS string into (selector, body) pairs.

    Comments are stripped first so prose mentioning a widget class (e.g. the
    rule-3 rationale comments in gui/style.py) never trips the selector match.
    """
    qss = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", qss)]


# --------------------------------------------------------------------------- #
# 1. Hover affordances                                                         #
# --------------------------------------------------------------------------- #

def test_pill_shelf_has_hover() -> None:
    """The pill shelf's MouseArea tracks hover and the pill binds it."""
    assert "id: pillArea" in SHELL_QML
    pill_area = SHELL_QML.split("id: pillArea", 1)[1][:200]
    assert "hoverEnabled: true" in pill_area, \
        "pill shelf MouseArea no longer tracks hover — tab hover is gone again"
    assert "pillArea.containsMouse" in SHELL_QML, \
        "pill visuals no longer bind hover — tab hover is gone again"


def test_shell_buttons_have_hover() -> None:
    """ShellButton and IconButton both carry a visible hover binding."""
    assert "btnArea.containsMouse" in SHELL_QML
    assert "iconArea.containsMouse" in SHELL_QML


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_qtabbar_hover_rule_visible(palette: dict) -> None:
    """Classic-shell tab hover exists and uses the strong hairline ring."""
    qss = build_qss(palette)
    hover = [body for sel, body in _rules(qss)
             if "QTabBar::tab:hover" in sel and "!selected" in sel]
    assert hover, "QTabBar::tab hover rule dropped from build_qss"
    assert palette["hairline_strong"] in hover[0]
    assert palette["field"] in hover[0]


# --------------------------------------------------------------------------- #
# 2. No per-side borders on hot-path selectors (hard rule 3)                   #
# --------------------------------------------------------------------------- #

# Widget classes that repaint at runtime rates (scan ticks, camera frames,
# metric updates, log lines). Substring match against each rule's selector.
_HOT_SELECTORS = [
    "QGroupBox",             # plot/camera container app-wide
    "QProgressBar",          # scan/sweep ticks
    "QFrame#cardPane",       # camera live view / stage view / FigureCard host
    "QFrame#channelCard",    # scope channel cards
    "QFrame#readoutCell",    # metric tiles (value updates + flash repolish)
    "QFrame#instrumentReadout",  # live position readout
    "QPlainTextEdit",        # scrolling log view / YAML editor
    "QTextEdit",
]

_PER_SIDE = re.compile(r"border-(top|bottom|left|right)-color")


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_no_per_side_borders_on_hot_paths(palette: dict) -> None:
    qss = build_qss(palette)
    offenders = []
    for sel, body in _rules(qss):
        if not _PER_SIDE.search(body):
            continue
        # A grouped selector poisons every widget class it names.
        for hot in _HOT_SELECTORS:
            if hot in sel:
                offenders.append(f"{hot}  (rule: {sel!r})")
    assert not offenders, (
        "per-side border colors (machined edges) reintroduced on hot-path "
        "selectors — Qt paints these with the slow four-edge path on every "
        "repaint (hard rule 3):\n  " + "\n  ".join(offenders))
