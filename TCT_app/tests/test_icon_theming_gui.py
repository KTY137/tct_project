"""Every icon in gui/ must be visible — in BOTH themes, in EVERY panel.

THE BUG (Mary's review of 4ca8331, 2026-07-14). The previous beat fixed the
frozen-black icon in ``gui/motor_panel.py`` and nowhere else. The same defect
was alive in **50 further call sites across 14 files**, because the shared
helper ``gui.status_widgets.set_button_icon`` still called ``qta.icon(name)``
with no colour.

``qta.icon(name)`` with no ``color=`` does not mean "inherit the theme": it
resolves qtawesome's default option, which is read from the **Qt palette** —
and this app themes through **QSS only** (``gui.style.apply_theme``; the app
palette carries nothing but the Window/WindowText backstop). So the glyph came
out the default light palette's **BLACK**, baked into a pixmap at construction
and never re-tinted on a theme switch. On the shipped dark default that is
1.11:1 against a panel and 1.37:1 against a field/raised surface — invisible.

Two guards live here:

* **pixels** — icons are rendered and their ink measured (not "the code path
  looks right"): not black, equal to the palette token, >= 3:1 against the
  surface they sit on (WCAG 1.4.11 — an icon is a non-text UI component), in
  both themes and back again after a toggle.
* **source** — an AST scan of ALL of ``gui/*.py`` (the old guard regexed one
  file, and even missed a call inside it). A colourless icon call is only
  allowed when its callee *proves at runtime* that it resolves a palette token
  by default; every other colourless call fails. The safe-helper set is
  measured, not hardcoded, so breaking ``set_button_icon``'s default instantly
  re-arms all ~50 call sites instead of quietly disarming the guard.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from tests.test_palette_contrast import AA_NON_TEXT, contrast

_GUI_DIR = Path(__file__).resolve().parent.parent / "gui"

# Module-level icon helpers. Value = index of the colour in the POSITIONAL
# argument list (callers may also pass it as a `color=`/`token=` keyword).
_ICON_HELPERS: dict[str, int] = {
    "_icon": 1,             # _icon(name, color)
    "_apply_icon": 2,       # _apply_icon(button, name, color)
    "set_button_icon": 2,   # set_button_icon(button, name, color)
}
_COLOUR_KWARGS = {"color", "token"}

# Hazard-class buttons whose icon sits on a red/amber fill: the "text" token
# would be the WRONG ink there, so these must keep passing an explicit colour.
# Their *glyph* (⏹ / ⇄ / …) lives in the button's LABEL TEXT and takes the QSS
# colour like any other text — that is why it was never affected by the bug,
# and it must never be "fixed" into a pixmap.
_HAZARD_ICON_BUTTONS = {
    "bias_panel.py":       {"_btn_off"},        # Output OFF (0 V) kill switch
    "multi_bias_panel.py": {"_btn_all_off"},    # ALL OUTPUTS OFF
    "scan_viewer_panel.py": {"_btn_abort"},     # Abort scan
    "calibration_panel.py": {"_btn_rep_stop"},  # Stop repeat run
}


# --------------------------------------------------------------------------- #
# The source scanner                                                           #
# --------------------------------------------------------------------------- #
def _gui_modules() -> list[Path]:
    return sorted(_GUI_DIR.glob("*.py"))


def _call_name(node: ast.Call) -> str | None:
    """'set_button_icon' for a bare call, 'qta.icon' for the qtawesome one.

    ``self._apply_icon()`` (gui/panel_kit.py's *method*) is deliberately NOT
    matched: it is a different callable with a different signature, and it
    already resolves its colour from the palette.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id if func.id in _ICON_HELPERS else None
    if isinstance(func, ast.Attribute) and func.attr == "icon":
        base = func.value
        if isinstance(base, ast.Name) and base.id in {"qta", "qtawesome"}:
            return "qta.icon"
    return None


def _carries_colour(node: ast.Call, name: str) -> bool:
    if any(kw.arg in _COLOUR_KWARGS for kw in node.keywords):
        return True
    idx = _ICON_HELPERS.get(name)
    return idx is not None and len(node.args) > idx


def _helper_defs(tree: ast.AST) -> set[ast.AST]:
    """The bodies of the icon helpers themselves. A colourless ``qta.icon``
    *inside* a helper is that helper's own plumbing — governed by the runtime
    contract probe below, not by the call-site rule (which is what actually
    protects: a helper that does not resolve a colour is simply never a legal
    colourless callee)."""
    return {n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name in _ICON_HELPERS}


def icon_call_sites() -> list[tuple[str, int, str, bool]]:
    """(file, line, callee, carries_colour) for every icon construction in
    gui/*.py, excluding the helpers' own internal plumbing."""
    out: list[tuple[str, int, str, bool]] = []
    for path in _gui_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        inner = {id(n) for d in _helper_defs(tree) for n in ast.walk(d)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or id(node) in inner:
                continue
            name = _call_name(node)
            if name is None:
                continue
            out.append((path.name, node.lineno, name, _carries_colour(node, name)))
    return out


def colourless_calls() -> list[tuple[str, int, str]]:
    return [(f, ln, name) for f, ln, name, coloured in icon_call_sites() if not coloured]


def _safe_helpers() -> set[str]:
    """Helpers that, called WITHOUT a colour, still hand qtawesome a real
    colour — measured, by monkeypatching ``qtawesome.icon`` and reading the
    kwarg that actually arrives. This is the whole guard's pivot: it cannot be
    satisfied by a comment or a signature, only by behaviour."""
    import qtawesome

    from PySide6.QtWidgets import QPushButton

    from gui import motor_panel, status_widgets

    _app()          # the probes build real QPushButtons
    seen: dict[str, object] = {}
    real = qtawesome.icon

    def recorder(*names, **kwargs):
        seen["color"] = kwargs.get("color")
        return real(*names, **kwargs)

    safe: set[str] = set()
    qtawesome.icon = recorder
    try:
        probes = (
            ("set_button_icon", lambda: status_widgets.set_button_icon(
                QPushButton(), "mdi.play")),
            # motor_panel keeps a local pair; they are only ever called through
            # _register_icon (which passes a token), but probe them anyway so
            # the guard knows whether a bare call to them would be legal.
            ("_icon", lambda: motor_panel._icon("fa5s.home")),
            ("_apply_icon", lambda: motor_panel._apply_icon(
                QPushButton(), "fa5s.home")),
        )
        for name, probe in probes:
            seen.clear()
            probe()
            colour = seen.get("color")
            if isinstance(colour, str) and colour:
                safe.add(name)
    finally:
        qtawesome.icon = real
    return safe


# --------------------------------------------------------------------------- #
# Source guard                                                                 #
# --------------------------------------------------------------------------- #
def test_the_scanner_actually_sees_the_icons():
    """Guards the guard #1: if the glob or the AST matcher breaks, every test
    below would vacuously "pass" while checking nothing. gui/ carries ~55 icon
    constructions; the exact number may drift, the order of magnitude may not."""
    sites = icon_call_sites()
    assert len({f for f, *_ in sites}) >= 12, "scanner is not reaching the panels"
    assert len(sites) >= 50, f"scanner only found {len(sites)} icon calls in gui/"


def test_the_guard_can_actually_fail():
    """Guards the guard #2: prove the predicate FLAGS things. With no helper
    trusted (the pre-fix world, where every helper fell through to qtawesome's
    black), the very same scan must light up the ~50 colourless call sites the
    review found. A guard that cannot fail is decoration."""
    flagged = colourless_calls()
    assert len(flagged) >= 45, (
        "with no token-defaulting helper, the scan should flag every colourless "
        f"call site (~50 across 14 files) — it only flagged {len(flagged)}")


def test_no_icon_is_built_without_a_colour():
    """THE guard, widened from one file to all of gui/*.py: every colourless
    icon call must land on a helper that RESOLVES a palette token by default.
    Any other colourless construction reaches qtawesome's palette-derived black
    and freezes it into a pixmap."""
    pytest.importorskip("qtawesome")
    safe = _safe_helpers()
    assert "set_button_icon" in safe, (
        "gui.status_widgets.set_button_icon no longer defaults its colour to a "
        "palette token — the colourless-icon bug is back, in ~50 call sites")
    stray = [(f, ln, name) for f, ln, name in colourless_calls() if name not in safe]
    assert not stray, (
        "icon(s) built with no colour, on a helper that does not resolve a "
        f"palette token — they will render qtawesome-default BLACK: {stray}")


def test_hazard_button_icons_still_carry_an_explicit_colour():
    """The kill switches (Output OFF / ALL OUTPUTS OFF / Abort / Stop) wear
    their icon on a red-or-amber FILL, where the "text" token would be wrong
    ink. They pass an explicit colour today; if a future sweep "simplifies"
    that away, the icon would silently follow the body-text token onto a red
    button. (Their ⏹/⇄ label glyphs are plain TEXT and take the QSS colour —
    they are not pixmaps and must never become pixmaps.)"""
    for path in _gui_modules():
        wanted = _HAZARD_ICON_BUTTONS.get(path.name)
        if not wanted:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) is None:
                continue
            if not node.args:
                continue
            target = node.args[0]
            attr = target.attr if isinstance(target, ast.Attribute) else None
            if attr in wanted:
                assert _carries_colour(node, _call_name(node)), (
                    f"{path.name}:{node.lineno} — hazard control {attr} lost its "
                    "explicit icon colour; it sits on a danger fill, not on the "
                    "body-text surface")


# --------------------------------------------------------------------------- #
# Pixel guard — the ink that actually gets painted                             #
# --------------------------------------------------------------------------- #
def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _ink(button) -> str:
    """Hex of the icon's ink: the first fully-opaque pixel it renders (a
    qtawesome glyph is antialiased, so most pixels are partial alpha)."""
    from PySide6.QtCore import QSize

    pixmap = button.icon().pixmap(QSize(32, 32))
    assert not pixmap.isNull(), "icon did not render"
    image = pixmap.toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() >= 250:
                return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())
    raise AssertionError("icon rendered no opaque pixel")


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_set_button_icon_defaults_to_the_palette_ink(mode):
    """The root fix: a call site that passes NO colour (all ~50 of them) now
    gets the button's own label ink, not qtawesome's black."""
    pytest.importorskip("qtawesome")
    from PySide6.QtWidgets import QPushButton

    from gui.status_widgets import set_button_icon
    from gui.style import apply_theme, palette

    app = _app()
    apply_theme(app, mode)
    btn = QPushButton("Live")
    set_button_icon(btn, "mdi.play")          # exactly as the panels call it
    assert _ink(btn) != "#000000", "icon is qtawesome-default BLACK"
    assert _ink(btn) == palette(mode)["text"].lower()


def test_set_button_icon_retints_on_a_theme_toggle_in_BOTH_directions():
    """A pixmap is not restyled by QSS — the icon must be REBUILT on a theme
    switch. Toggle both ways and require the pixels to actually move."""
    pytest.importorskip("qtawesome")
    from PySide6.QtWidgets import QPushButton

    from gui.status_widgets import set_button_icon
    from gui.style import apply_theme, palette

    app = _app()
    apply_theme(app, "light")
    btn = QPushButton("Live")
    set_button_icon(btn, "mdi.play")
    light_ink = _ink(btn)

    apply_theme(app, "dark")
    dark_ink = _ink(btn)
    apply_theme(app, "light")
    back_to_light = _ink(btn)

    assert light_ink == palette("light")["text"].lower()
    assert dark_ink == palette("dark")["text"].lower()
    assert light_ink != dark_ink, "icon ink is frozen across the toggle"
    assert back_to_light == light_ink, "icon did not follow the theme back"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_default_icon_ink_is_legible_on_every_button_surface(mode):
    """WCAG 1.4.11: an icon is a non-text UI component -> 3:1 against the
    surface it sits on. These are the exact surfaces the review measured the
    black glyph against (1.11 / 1.37 / 1.29 : 1 on the dark default)."""
    from gui.style import palette

    p = palette(mode)
    for surface in ("panel", "field", "raised", "chrome"):
        got = contrast(p["text"], p[surface])
        assert got >= AA_NON_TEXT, (
            f"[{mode}] default icon ink {p['text']} is {got:.2f}:1 against "
            f"'{surface}' ({p[surface]}) — below the 3:1 non-text floor")


def test_an_explicit_colour_is_never_overridden_or_retinted():
    """Panels that own their icon ink (a fixed safety token like WARN_AMBER, or
    a colour a panel re-resolves inside its own refresh_theme — bias/multi-bias/
    laser/calibration/scan-viewer) keep owning it: the shared helper applies it
    verbatim and the theme watcher must not fight them for it."""
    pytest.importorskip("qtawesome")
    from PySide6.QtWidgets import QPushButton

    from gui.status_widgets import set_button_icon
    from gui.style import WARN_AMBER, apply_theme

    app = _app()
    apply_theme(app, "light")
    btn = QPushButton("Laser ON")
    set_button_icon(btn, "mdi.power-plug", color=WARN_AMBER)
    assert _ink(btn) == WARN_AMBER.lower()

    apply_theme(app, "dark")
    assert _ink(btn) == WARN_AMBER.lower(), "caller-owned icon ink was hijacked"
    apply_theme(app, "light")
    assert _ink(btn) == WARN_AMBER.lower()


def test_icon_ink_helper_resolves_tokens_not_hex():
    """The tokenized entry point panels should reach for instead of a literal
    (tests/test_no_inline_hex_gui.py)."""
    from gui.status_widgets import icon_ink
    from gui.style import palette

    assert icon_ink("text", "dark") == palette("dark")["text"]
    assert icon_ink("on_danger", "light") == palette("light")["on_danger"]


# --------------------------------------------------------------------------- #
# Panel-level proof: the scope panel's own icons (it had a second colourless    #
# helper of its own, now deleted in favour of the shared one)                  #
# --------------------------------------------------------------------------- #
def _scope_panel():
    from devices.oscilloscope import Oscilloscope
    from gui.scope_panel import ScopePanel

    _app()
    return ScopePanel(Oscilloscope(simulation=True))


def test_scope_panel_icons_are_token_bound_and_legible_in_both_themes():
    pytest.importorskip("qtawesome")
    from gui.style import apply_theme, palette

    app = _app()
    panel = _scope_panel()
    try:
        for mode in ("dark", "light"):
            apply_theme(app, mode)
            p = palette(mode)
            for btn in (panel._btn_live, panel._btn_single):
                assert _ink(btn) != "#000000"
                assert _ink(btn) == p["text"].lower()
                assert contrast(_ink(btn), p["field"]) >= AA_NON_TEXT
    finally:
        panel.shutdown()
        app.processEvents()


def test_scope_live_button_keeps_following_the_theme_after_the_stop_swap():
    """``_toggle_live`` swaps the glyph (play <-> stop) at runtime — the new
    pixmap must be registered under the same token, or the icon would be frozen
    at the colour it had the moment Live was pressed."""
    pytest.importorskip("qtawesome")
    from gui.style import apply_theme, palette

    app = _app()
    panel = _scope_panel()
    try:
        apply_theme(app, "light")
        panel._btn_live.setChecked(True)          # -> _toggle_live -> mdi.stop
        assert _ink(panel._btn_live) == palette("light")["text"].lower()
        apply_theme(app, "dark")
        assert _ink(panel._btn_live) == palette("dark")["text"].lower()
    finally:
        panel._btn_live.setChecked(False)
        panel.shutdown()
        app.processEvents()
