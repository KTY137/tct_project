"""Theme editor + style override layer (gui/theme_editor.py, gui/style.py).

Covers the task contract:
- defaults are byte-identical with no user action (recompute == inline dicts);
- glass_amount parametrizes the chrome/strip/edge/edge_shade pre-blends,
  with 0.0 collapsing chrome/strip to opaque panel and both machined edges
  to the uniform hairline;
- safety tokens (danger/armed/sim/error + the crit/warn aliases) have no
  override path: the style setter raises, the dialog draft setter raises,
  no editable swatch exists for them, and a preset JSON that names one is
  REJECTED on load (round 2 — it used to be laundered);
- an accent override reaches the generated QSS and reset restores it;
- presets round-trip through QSettings JSON;
- persistence round-trips through save/load_theme_customization;
- headless construction + theme-switch smoke for the dialog.

Round 2 (Kaya 2026-07-13) additionally covers:
- window opacity is REAL (setWindowOpacity) and clamped to [0.80, 1.00] — a
  hostile hand-edited QSettings value is clamped, never obeyed (safety floor:
  HV chips and Abort must stay legible);
- the five built-in presets round-trip and none can touch a locked token;
- the renamed "Surface tint" slider still drives the same pre-blend.

All QSettings go through a throwaway INI file (never the real registry), and
every test restores the shipped defaults via the autouse fixture — the style
override layer is module-global state.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings

from gui import style


@pytest.fixture(autouse=True)
def _reset_style_state():
    yield
    style.reset_theme_customization()


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _tmp_settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "theme_test.ini"), QSettings.Format.IniFormat)


def _dialog(tmp_path, mode="dark"):
    _app()
    from gui.theme_editor import ThemeEditorDialog
    return ThemeEditorDialog(mode=mode, settings=_tmp_settings(tmp_path))


# --------------------------------------------------------------------------- #
# style.py override layer                                                     #
# --------------------------------------------------------------------------- #

def test_recompute_at_defaults_is_byte_identical():
    """With no overrides and the default glass amount, a recompute must
    reproduce the inline LIGHT/DARK definitions exactly — nothing changes
    visually without user action."""
    before_light, before_dark = dict(style.LIGHT), dict(style.DARK)
    style.set_glass_amount(style.DEFAULT_GLASS_AMOUNT)   # forces a recompute
    assert style.LIGHT == before_light
    assert style.DARK == before_dark


def test_glass_zero_collapses_to_opaque():
    style.set_glass_amount(0.0)
    for p in (style.LIGHT, style.DARK):
        assert p["chrome"] == p["panel"]        # no frosted wash
        assert p["strip"] == p["panel"]
        assert p["edge"] == p["hairline"]       # no specular machined edge
        assert p["edge_shade"] == p["hairline"]


def test_glass_amount_clamps_and_partial_blends():
    assert style.set_glass_amount(2.5) == 1.0
    ceiling = style.LIGHT["chrome"]
    assert style.set_glass_amount(-1.0) == 0.0
    opaque = style.LIGHT["chrome"]
    assert opaque == style.LIGHT["panel"]
    # 0.5 sits strictly between the opaque and full-glass chrome tones.
    style.set_glass_amount(0.5)
    assert style.LIGHT["chrome"] not in (ceiling, opaque)


def test_plot_canvas_fixed_at_any_glass_amount():
    """Hard rule: plots/camera stay on the fixed opaque instrument screen."""
    for amount in (0.0, 0.5, 1.0):
        style.set_glass_amount(amount)
        for p in (style.LIGHT, style.DARK):
            assert p["plot_grid"] == style.PLOT_GRID
            assert p["plot_overlay"] == style.PLOT_OVERLAY
    assert style.PLOT_BG == "#0a0b0d"  # untouched module constant


@pytest.mark.parametrize("token", sorted(style.SAFETY_TOKENS))
def test_setter_refuses_safety_tokens(token):
    with pytest.raises(ValueError):
        style.apply_theme_overrides({token: "#123456"}, "dark")
    # And nothing leaked into the stored overrides / live palette.
    assert token not in style.theme_overrides("dark")
    assert style.DARK[token] != "#123456"


def test_setter_refuses_unknown_token_and_bad_hex():
    with pytest.raises(ValueError):
        style.apply_theme_overrides({"bogus": "#112233"}, "dark")
    with pytest.raises(ValueError):
        style.apply_theme_overrides({"accent": "not-a-color"}, "dark")


def test_accent_override_reaches_qss_and_reset_restores():
    base_dark = dict(style.DARK)
    style.apply_theme_overrides({"accent": "#12ab34"}, "dark")
    assert style.DARK["accent"] == "#12ab34"
    # Derived tokens re-derive from the override, not the shipped accent.
    assert style.DARK["accent_strong"] == style._darken("#12ab34", 0.15)
    assert "#12ab34" in style.build_qss(style.palette("dark"))
    # LIGHT is untouched by a dark-mode override.
    assert style.LIGHT["accent"] == style.ACCENT_LIGHT
    style.reset_theme_customization()
    assert style.DARK == base_dark
    assert "#12ab34" not in style.build_qss(style.palette("dark"))


def test_sanitize_overrides_drops_safety_unknown_and_invalid():
    dirty = {"danger": "#00ff00", "sim": "#ff0000", "accent": "#445566",
             "bogus": "#000000", "text": "nope", "panel": 42}
    assert style.sanitize_overrides(dirty) == {"accent": "#445566"}
    assert style.sanitize_overrides("not-a-dict") == {}


def test_palette_identity_preserved_across_recompute():
    """apply_theme checks ``palette is DARK`` — in-place mutation must keep
    dict identity for every held reference."""
    light_ref, dark_ref = style.LIGHT, style.DARK
    style.apply_theme_overrides({"accent": "#22aa44"}, "light")
    style.set_glass_amount(0.3)
    assert style.LIGHT is light_ref
    assert style.DARK is dark_ref
    assert style.palette("dark") is dark_ref


def test_customization_persistence_roundtrip(tmp_path):
    s = _tmp_settings(tmp_path)
    style.apply_theme_overrides({"accent": "#3355aa"}, "dark")
    style.set_glass_amount(0.25)
    style.apply_typography(hinting="full", base_px=14)
    style.apply_radius_scale("l")
    style.save_theme_customization(s)

    style.reset_theme_customization()
    assert style.theme_overrides("dark") == {}
    assert style.get_glass_amount() == style.DEFAULT_GLASS_AMOUNT

    style.load_theme_customization(s)
    assert style.theme_overrides("dark") == {"accent": "#3355aa"}
    assert style.get_glass_amount() == 0.25
    assert style.FONT_HINTING == "full"
    assert style.FONT_MD == 14
    assert style.radius_scale() == "l"
    assert style.RADIUS_SM == style.RADIUS_SCALES["l"][0]


def test_load_from_empty_settings_resets_every_knob(tmp_path):
    """A load DEFINES the state — it must not inherit the previous one.

    Absent theme/* keys mean "shipped default", not "keep what is currently
    applied": otherwise glass amount, radius scale and typography survive a
    load from a *different* settings store, which is module-global state
    persisting across loads (and, in the suite, across tests).
    """
    style.set_glass_amount(0.2)
    style.apply_radius_scale("l")
    style.apply_typography(sans="Arial", base_px=style.base_typography()["base_px"] + 2)
    style.apply_theme_overrides({"accent": "#abcdef"}, "dark")

    style.load_theme_customization(_tmp_settings(tmp_path))   # empty store

    assert style.get_glass_amount() == style.DEFAULT_GLASS_AMOUNT
    assert style.radius_scale() == "m"
    assert style.RADIUS_SM == style.RADIUS_SCALES["m"][0]
    assert style.typography() == {"sans": None, "mono": None,
                                  "hinting": None, "base_px": None}
    assert style.FONT_MD == style.base_typography()["base_px"]
    assert style.theme_overrides("dark") == {}
    assert style.DARK["accent"] != "#abcdef"


def test_load_ignores_safety_override_in_registry(tmp_path):
    """A hand-edited theme/overrides blob cannot unlock the safety palette."""
    s = _tmp_settings(tmp_path)
    s.setValue("theme/overrides",
               json.dumps({"dark": {"danger": "#00ff00", "accent": "#556677"}}))
    s.sync()
    base_danger = style.DARK["danger"]
    style.load_theme_customization(s)
    assert style.DARK["danger"] == base_danger
    assert style.DARK["accent"] == "#556677"


def test_typography_choice_promotes_family_and_resets():
    style.apply_typography(sans="Arial", mono="Consolas")
    assert style.SANS_FAMILIES[0] == "Arial"
    assert "Arial" in style.SANS_FAMILY
    assert style.MONO_FAMILIES[0] == "Consolas"
    # Fallback stack survives behind the choice.
    assert "Segoe UI" in style.SANS_FAMILIES
    style.apply_typography(sans=None, mono=None)
    assert list(style.SANS_FAMILIES) == style.base_typography()["sans"]


def test_base_px_clamps_to_plus_minus_two():
    base = style.base_typography()["base_px"]
    style.apply_typography(base_px=base + 10)
    assert style.FONT_MD == base + 2
    style.apply_typography(base_px=base - 10)
    assert style.FONT_MD == base - 2


# --------------------------------------------------------------------------- #
# ThemeEditorDialog                                                           #
# --------------------------------------------------------------------------- #

def test_dialog_constructs_and_safety_tokens_not_editable(tmp_path):
    dlg = _dialog(tmp_path)
    # No editable swatch (no color-dialog path) for any safety token.
    assert not (set(dlg._swatches) & style.SAFETY_TOKENS)
    # The four canonical safety tokens render as locked read-only swatches.
    assert set(dlg._locked_swatches) == {"danger", "armed", "sim", "error"}
    for token in ("danger", "armed", "sim", "error"):
        with pytest.raises(ValueError):
            dlg._set_draft_color(token, "#123456")
    # Editable rows exist for every whitelisted group.
    assert set(dlg._swatches) == set(style.EDITABLE_TOKENS)


def test_dialog_apply_accent_and_reset_to_preset_restores(tmp_path):
    dlg = _dialog(tmp_path)
    base_dark = dict(style.DARK)
    dlg._set_draft_color("accent", "#12ab34")
    dlg._apply()
    assert style.DARK["accent"] == "#12ab34"
    assert "#12ab34" in style.build_qss(style.palette("dark"))
    # Reset to the built-in "Cockpit Dark" preset (selected by default).
    assert dlg._selected_preset()["name"] == "Cockpit Dark"
    dlg._reset_to_preset()
    assert style.DARK == base_dark
    assert "#12ab34" not in style.build_qss(style.palette("dark"))


def test_dialog_glass_slider_zero_yields_opaque_chrome(tmp_path):
    dlg = _dialog(tmp_path)
    dlg._glass_slider.setValue(0)
    dlg._apply()
    assert style.get_glass_amount() == 0.0
    assert style.DARK["chrome"] == style.DARK["panel"]
    assert style.LIGHT["chrome"] == style.LIGHT["panel"]


def test_dialog_presets_roundtrip_through_qsettings(tmp_path):
    from gui.theme_editor import load_user_presets
    settings = _tmp_settings(tmp_path)
    _app()
    from gui.theme_editor import ThemeEditorDialog
    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    dlg._set_draft_color("accent", "#336699")
    dlg._glass_slider.setValue(40)   # _save syncs the draft from the slider
    dlg._save_preset_named("My Bench")

    stored = load_user_presets(settings)
    assert [p["name"] for p in stored] == ["My Bench"]
    assert stored[0]["overrides"] == {"accent": "#336699"}
    assert stored[0]["glass"] == pytest.approx(0.40)

    # A fresh dialog over the same settings lists + loads the preset — the five
    # built-ins first (style.BUILTIN_PRESETS order), user presets after.
    dlg2 = ThemeEditorDialog(mode="dark", settings=settings)
    names = [dlg2._preset_list.item(i).text()
             for i in range(dlg2._preset_list.count())]
    assert names == [p["name"] for p in style.BUILTIN_PRESETS] + ["My Bench"]
    dlg2._preset_list.setCurrentRow(names.index("My Bench"))
    assert dlg2._draft_overrides == {"accent": "#336699"}
    assert dlg2._draft_glass == pytest.approx(0.40)


def test_malicious_preset_json_is_rejected_not_laundered(tmp_path):
    """Round 2 hardened this: a preset that NAMES a safety token is rejected
    outright (it never appears in the list), rather than being loaded with the
    offending key silently stripped. A theme that tries to repaint `danger` is
    not a theme with one bad key — laws 1/2/6."""
    from gui.theme_editor import PRESETS_KEY, load_user_presets
    settings = _tmp_settings(tmp_path)
    settings.setValue(PRESETS_KEY, json.dumps([{
        "name": "Evil", "mode": "dark",
        "overrides": {"danger": "#00ff00", "accent": "#445566"},
        "glass": 1.0, "radius": "m",
    }, {
        "name": "Fine", "mode": "dark",
        "overrides": {"accent": "#445566"},
        "glass": 1.0, "radius": "m",
    }]))
    settings.sync()
    _app()
    from gui.theme_editor import ThemeEditorDialog
    base_danger = style.DARK["danger"]

    # Rejected at the parsing layer — the good preset alongside it still loads.
    assert [p["name"] for p in load_user_presets(settings)] == ["Fine"]

    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    names = [dlg._preset_list.item(i).text()
             for i in range(dlg._preset_list.count())]
    assert "Evil" not in names
    dlg._preset_list.setCurrentRow(names.index("Fine"))
    dlg._apply()
    assert style.DARK["danger"] == base_danger
    assert style.DARK["accent"] == "#445566"
    assert "danger" not in style.theme_overrides("dark")


@pytest.mark.parametrize("token", sorted(style.SAFETY_TOKENS))
def test_no_preset_can_touch_any_locked_safety_token(tmp_path, token):
    """Every locked token, not just `danger` — including the crit/warn aliases
    that most QSS rules actually read."""
    from gui.theme_editor import _sanitize_preset
    assert _sanitize_preset({
        "name": "Evil", "mode": "dark",
        "overrides": {token: "#00ff00"}, "glass": 1.0, "radius": "m",
    }) is None


def test_dialog_theme_switch_smoke_and_mode_retarget(tmp_path):
    """Headless construction + theme-switch smoke (refresh_theme is what
    tct_gui._toggle_theme fans out to)."""
    dlg = _dialog(tmp_path, mode="dark")
    assert dlg._mode == "dark"
    dlg.refresh_theme("light")
    assert dlg._mode == "light"
    # Swatches re-resolved from the light palette.
    assert style.LIGHT["accent"] in dlg._swatches["accent"].styleSheet()
    dlg.refresh_theme("dark")
    assert dlg._mode == "dark"
    assert style.DARK["accent"] in dlg._swatches["accent"].styleSheet()


def test_same_mode_refresh_keeps_drafts(tmp_path):
    """The glass-preview round trip (applyRequested → _toggle_theme →
    refresh_theme with the SAME mode) must not stomp in-progress drafts."""
    dlg = _dialog(tmp_path, mode="dark")
    dlg._set_draft_color("accent", "#987654")
    dlg.refresh_theme("dark")
    assert dlg._draft_overrides == {"accent": "#987654"}


# =========================================================================== #
# ROUND 2 (Kaya 2026-07-13): real window opacity, 5 presets, honest naming     #
# =========================================================================== #

# --- window opacity: the safety clamp is the point ------------------------- #

def test_window_opacity_defaults_to_fully_opaque():
    assert style.get_window_opacity() == style.DEFAULT_WINDOW_OPACITY == 1.0
    assert style.MIN_WINDOW_OPACITY == 0.80


@pytest.mark.parametrize("value,expected", [
    (1.0, 1.0),
    (0.9, 0.9),
    (0.80, 0.80),
    (0.5, 0.80),        # below the floor -> clamped UP, never obeyed
    (0.0, 0.80),
    (-3.0, 0.80),
    (1.7, 1.0),         # above 1.0 is meaningless -> clamped down
])
def test_set_window_opacity_clamps_to_the_safety_band(value, expected):
    """The floor is a SAFETY rail: an HV-live chip and the Abort button must
    stay legible at every reachable setting, so no caller — slider, preset,
    registry, or code — can drive the cockpit to a ghost."""
    assert style.set_window_opacity(value) == pytest.approx(expected)
    assert style.get_window_opacity() == pytest.approx(expected)


@pytest.mark.parametrize("garbage", [None, "", "0.2abc", "nonsense", [0.2]])
def test_set_window_opacity_falls_back_to_opaque_on_garbage(garbage):
    """Unparseable input fails to the SAFE end (fully opaque), not to the floor
    and not to a crash."""
    assert style.set_window_opacity(garbage) == 1.0


def test_set_window_opacity_rejects_nan():
    assert style.set_window_opacity(float("nan")) == 1.0


def test_hostile_persisted_opacity_is_clamped_not_obeyed(tmp_path):
    """A hand-edited QSettings entry of 0.2 (the exact hostile case in the
    brief) must come back as the 0.80 floor."""
    settings = _tmp_settings(tmp_path)
    settings.setValue("theme/window_opacity", 0.2)
    settings.sync()

    style.load_theme_customization(settings)
    assert style.get_window_opacity() == pytest.approx(style.MIN_WINDOW_OPACITY)


def test_window_opacity_round_trips_through_qsettings(tmp_path):
    settings = _tmp_settings(tmp_path)
    style.set_window_opacity(0.88)
    style.save_theme_customization(settings)

    style.reset_theme_customization()
    assert style.get_window_opacity() == 1.0        # reset restores the default

    style.load_theme_customization(settings)
    assert style.get_window_opacity() == pytest.approx(0.88)


def test_absent_opacity_key_means_shipped_default(tmp_path):
    """An empty store must mean "opaque", not "keep whatever was set before"."""
    style.set_window_opacity(0.85)
    style.load_theme_customization(_tmp_settings(tmp_path))
    assert style.get_window_opacity() == 1.0


# Qt stores window opacity as an 8-bit alpha, so windowOpacity() reads back
# QUANTIZED to the nearest 1/255 (0.84 -> 214/255 == 0.83921...). Our own state
# (style.get_window_opacity) keeps the exact float; only the widget read-back is
# stepped. Compare Qt read-backs with this tolerance, never exactly.
_QT_ALPHA_STEP = 1.0 / 255.0


def test_apply_window_opacity_reaches_every_top_level_window():
    """Detached panels and dialogs INHERIT the opacity — one coherent cockpit,
    not an opaque slab floating over a translucent shell."""
    from PySide6.QtWidgets import QDialog, QMainWindow
    app = _app()
    win, dlg = QMainWindow(), QDialog()
    try:
        style.set_window_opacity(0.85)
        style.apply_window_opacity(app)
        assert win.windowOpacity() == pytest.approx(0.85, abs=_QT_ALPHA_STEP)
        assert dlg.windowOpacity() == pytest.approx(0.85, abs=_QT_ALPHA_STEP)

        # And the clamp holds through the apply path too: a hostile 0.1 lands on
        # the floor, not on a ghost cockpit.
        style.apply_window_opacity(app, opacity=0.1)
        assert style.get_window_opacity() == pytest.approx(style.MIN_WINDOW_OPACITY)
        assert win.windowOpacity() == pytest.approx(
            style.MIN_WINDOW_OPACITY, abs=_QT_ALPHA_STEP)
        # Never below the floor, even after quantization.
        assert win.windowOpacity() > style.MIN_WINDOW_OPACITY - _QT_ALPHA_STEP
    finally:
        win.deleteLater()
        dlg.deleteLater()


def test_menus_and_tooltips_are_not_faded():
    """Regression guard for a real trap: Qt's window TYPE is a value inside
    WindowType_Mask (Window=0x1, Popup=0x9), not an orthogonal bit — a naive
    `flags & Qt.WindowType.Popup` test classifies a plain QMainWindow AS a popup
    and skips the whole cockpit. Menus must be excluded, real windows must not."""
    from PySide6.QtWidgets import QMainWindow, QMenu
    app = _app()
    win, menu = QMainWindow(), QMenu()
    try:
        assert style._is_transient_window(menu) is True
        assert style._is_transient_window(win) is False

        style.set_window_opacity(0.85)
        style.apply_window_opacity(app)
        assert win.windowOpacity() == pytest.approx(0.85, abs=_QT_ALPHA_STEP)
        assert menu.windowOpacity() == 1.0          # untouched
    finally:
        win.deleteLater()
        menu.deleteLater()


def test_detached_panel_window_inherits_window_opacity():
    """gui/detachable_tabs._DetachedWindow is created AFTER the setting is
    applied, so it must pick the opacity up at construction."""
    from PySide6.QtWidgets import QLabel
    from gui.detachable_tabs import _DetachedWindow
    _app()
    style.set_window_opacity(0.84)
    win = _DetachedWindow(QLabel("panel"), "Motor Stage")
    try:
        assert win.windowOpacity() == pytest.approx(0.84, abs=_QT_ALPHA_STEP)
    finally:
        win.deleteLater()


def test_opacity_slider_cannot_express_a_ghost_cockpit(tmp_path):
    """The slider's own RANGE enforces the floor — the unsafe values are not
    merely clamped on commit, they are unreachable by dragging."""
    dlg = _dialog(tmp_path)
    assert dlg._opacity_slider.minimum() == 80
    assert dlg._opacity_slider.maximum() == 100
    assert dlg._opacity_slider.singleStep() == 1

    dlg._opacity_slider.setValue(0)     # Qt clamps to the range
    assert dlg._opacity_slider.value() == 80
    assert style.get_window_opacity() == pytest.approx(0.80)


def test_dialog_opacity_applies_and_persists(tmp_path):
    settings = _tmp_settings(tmp_path)
    _app()
    from gui.theme_editor import ThemeEditorDialog
    dlg = ThemeEditorDialog(mode="dark", settings=settings)

    dlg._opacity_slider.setValue(90)
    dlg._apply()

    assert style.get_window_opacity() == pytest.approx(0.90)
    style.reset_theme_customization()
    style.load_theme_customization(settings)
    assert style.get_window_opacity() == pytest.approx(0.90)


# --- the renamed knob still drives the SAME pre-blend ----------------------- #

def test_surface_tint_slider_still_drives_the_pre_blend(tmp_path):
    """Renaming "Glass amount" -> "Surface tint" is a copy change (law 8), not a
    behaviour change: the slider must still parametrize chrome/strip/edge."""
    dlg = _dialog(tmp_path)
    dlg._glass_slider.setValue(0)
    dlg._apply()
    assert style.get_glass_amount() == 0.0
    assert style.DARK["chrome"] == style.DARK["panel"]      # opaque collapse

    dlg._glass_slider.setValue(100)
    dlg._apply()
    assert style.get_glass_amount() == 1.0
    assert style.DARK["chrome"] != style.DARK["panel"]

    # ... and the two knobs are independent: tint never moves the real opacity.
    assert style.get_window_opacity() == 1.0


def test_material_card_labels_are_honest(tmp_path):
    """The UI copy is part of the contract here: the old name promised
    see-through and could not deliver it."""
    from PySide6.QtWidgets import QLabel
    dlg = _dialog(tmp_path)
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert "Surface tint" in texts
    assert "Window opacity" in texts
    assert "Glass amount" not in texts
    # The hint must say what it actually does and point at the real knob.
    hint = next(t for t in texts if "cannot blur" in t)
    assert "Window opacity" in hint


# --- the five built-in presets --------------------------------------------- #

def test_five_builtin_presets_are_shipped():
    from gui.theme_editor import builtin_presets
    _app()
    names = [p["name"] for p in builtin_presets()]
    assert names == ["Cockpit Dark", "Graphite", "Deep Violet",
                     "Lab Light", "Paper"]
    assert names[0] == "Cockpit Dark"                       # the default


def test_builtin_presets_carry_no_safety_token():
    """By construction: preset overrides are EDITABLE_TOKENS *groups*, and no
    safety token is a group. This pins it so a future token set cannot smuggle
    one in."""
    for preset in style.BUILTIN_PRESETS:
        assert not (set(preset["overrides"]) & set(style.SAFETY_TOKENS))
        for key in preset["overrides"]:
            assert key in style.EDITABLE_TOKENS


@pytest.mark.parametrize("preset", style.BUILTIN_PRESETS, ids=lambda p: p["name"])
def test_every_builtin_preset_leaves_the_safety_palette_untouched(preset):
    """Apply each preset for real and assert the locked colours (the four
    canonical names plus the crit/warn aliases most QSS rules actually read) are
    byte-identical afterwards."""
    _app()
    mode = preset["mode"]
    live = style.DARK if mode == "dark" else style.LIGHT
    before = {t: live[t] for t in style.SAFETY_TOKENS}

    style.apply_theme_overrides(dict(preset["overrides"]), mode, merge=False)
    style.set_glass_amount(preset["glass"])

    assert {t: live[t] for t in style.SAFETY_TOKENS} == before


@pytest.mark.parametrize("preset", style.BUILTIN_PRESETS, ids=lambda p: p["name"])
def test_every_builtin_preset_round_trips_through_qsettings(tmp_path, preset):
    """Save each built-in as a user preset and read it back — the token set and
    the tint amount must survive the QSettings JSON round trip intact."""
    from gui.theme_editor import (
        ThemeEditorDialog, load_user_presets, save_user_presets, _sanitize_preset,
    )
    _app()
    settings = _tmp_settings(tmp_path)
    stored = _sanitize_preset({
        "name": preset["name"] + " copy", "mode": preset["mode"],
        "overrides": dict(preset["overrides"]), "glass": preset["glass"],
        "radius": "m",
    })
    assert stored is not None                # never rejected: no safety key
    save_user_presets(settings, [stored])

    back = load_user_presets(settings)
    assert len(back) == 1
    assert back[0]["overrides"] == preset["overrides"]
    assert back[0]["glass"] == pytest.approx(preset["glass"])
    assert back[0]["mode"] == preset["mode"]

    # And it loads into the dialog's drafts.
    dlg = ThemeEditorDialog(mode=preset["mode"], settings=settings)
    names = [dlg._preset_list.item(i).text()
             for i in range(dlg._preset_list.count())]
    dlg._preset_list.setCurrentRow(names.index(preset["name"] + " copy"))
    assert dlg._draft_overrides == preset["overrides"]
    assert dlg._draft_glass == pytest.approx(preset["glass"])


@pytest.mark.parametrize("preset", style.BUILTIN_PRESETS, ids=lambda p: p["name"])
def test_selecting_a_builtin_preset_repaints_the_qss(tmp_path, preset):
    """End-to-end: pick the preset in the dialog, Apply, and the generated QSS
    must actually carry its accent (i.e. the token set reached the stylesheet)."""
    _app()
    from gui.theme_editor import ThemeEditorDialog
    dlg = ThemeEditorDialog(mode=preset["mode"], settings=_tmp_settings(tmp_path))
    names = [dlg._preset_list.item(i).text()
             for i in range(dlg._preset_list.count())]
    dlg._preset_list.setCurrentRow(names.index(preset["name"]))
    dlg._apply()

    live = style.DARK if preset["mode"] == "dark" else style.LIGHT
    expected_accent = preset["overrides"].get("accent", live["accent"])
    assert live["accent"].lower() == expected_accent.lower()
    assert expected_accent.lower() in style.build_qss(live).lower()


def test_shipped_presets_are_the_shipped_themes():
    """Cockpit Dark / Lab Light carry NO overrides on purpose — selecting them
    restores the app exactly as it ships (the ratified v5 look), not a near-copy
    of it."""
    by_name = {p["name"]: p for p in style.BUILTIN_PRESETS}
    assert by_name["Cockpit Dark"]["overrides"] == {}
    assert by_name["Lab Light"]["overrides"] == {}
    assert by_name["Cockpit Dark"]["glass"] == style.DEFAULT_GLASS_AMOUNT


def test_new_presets_carry_a_full_token_set():
    """Graphite / Deep Violet / Paper must each set every colour a theme needs —
    a preset that changes the canvas but forgets the well leaves a mismatched
    input recess."""
    needed = {"canvas", "panel", "text", "muted", "hairline", "accent", "well"}
    by_name = {p["name"]: p for p in style.BUILTIN_PRESETS}
    for name in ("Graphite", "Deep Violet", "Paper"):
        assert set(by_name[name]["overrides"]) == needed, name
