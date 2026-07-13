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

import gui.backdrop as backdrop
from gui import app_settings, style


@pytest.fixture(autouse=True)
def _reset_style_state():
    yield
    style.reset_theme_customization()


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _install_recording_dwm(monkeypatch: pytest.MonkeyPatch, extend_hr: int = 0,
                            attr_hr: int = 0) -> list[tuple]:
    """Local copy of tests/test_backdrop.py's ``_recording_dwm`` helper — the
    Backdrop-combo tests below need it too, and duplicating ~12 lines beats
    importing one test module from another."""
    calls: list[tuple] = []

    def fake_extend(hwnd):
        calls.append(("extend", hwnd))
        return extend_hr

    def fake_set_attr(hwnd, attribute, value):
        calls.append(("set_attr", attribute, value))
        return attr_hr

    monkeypatch.setattr(backdrop, "_dwm_extend_frame", fake_extend)
    monkeypatch.setattr(backdrop, "_dwm_set_window_attribute", fake_set_attr)
    return calls


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


def test_footer_buttons_stay_enabled_and_current_after_two_theme_toggles(tmp_path, monkeypatch):
    """C3 guard pattern (2026-07-13 "theme window buttons" bug report):
    construct the dialog, toggle theme twice (mirroring tct_gui._toggle_theme:
    apply_theme + apply_window_backdrop + apply_window_opacity +
    refresh_theme, exercised here with a real active backdrop material so the
    apply_window_backdrop_to reapply-without-repaint fix in gui/style.py is
    actually on the code path), and assert every footer button is still
    enabled, still fires its clicked signal, and every editable swatch still
    resolves its colour from the CURRENT (not stale) palette."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtTest import QTest

    _force_backdrop_supported(monkeypatch)
    _install_recording_dwm(monkeypatch)
    style.set_window_backdrop("mica")
    dlg = _dialog(tmp_path, mode="dark")
    dlg.show()

    def _toggle(mode):
        app = _app()
        style.apply_theme(app, mode)
        style.apply_window_backdrop(app)
        style.apply_window_opacity(app)
        dlg.refresh_theme(mode)

    _toggle("light")
    _toggle("dark")

    apply_clicks = []
    dlg._btn_apply.clicked.connect(lambda: apply_clicks.append(1))
    for name in ("_btn_apply", "_btn_save_preset", "_btn_reset", "_btn_close"):
        btn = getattr(dlg, name)
        assert btn.isEnabled(), name

    QTest.mouseClick(dlg._btn_apply, _Qt.MouseButton.LeftButton)
    assert apply_clicks == [1], "Apply button must still fire clicked after two toggles"

    p = style.palette("dark")
    for token, swatch in dlg._swatches.items():
        assert dlg._draft_overrides.get(token, p[token]) in swatch.styleSheet()
    style.reset_theme_customization()


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

def test_nine_builtin_presets_are_shipped():
    from gui.theme_editor import builtin_presets
    _app()
    names = [p["name"] for p in builtin_presets()]
    assert names == ["Cockpit Dark", "Glass", "Graphite", "Deep Violet",
                     "Plasma", "Aurora", "Lab Light", "Paper", "Spatial Light"]
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
    """Graphite / Deep Violet / Paper / the Glass family must each set every
    colour a theme needs — a preset that changes the canvas but forgets the
    well leaves a mismatched input recess."""
    needed = {"canvas", "panel", "text", "muted", "hairline", "accent", "well"}
    by_name = {p["name"]: p for p in style.BUILTIN_PRESETS}
    for name in ("Graphite", "Deep Violet", "Paper",
                 "Glass", "Plasma", "Aurora", "Spatial Light"):
        assert set(by_name[name]["overrides"]) == needed, name


# --------------------------------------------------------------------------- #
# Glass family (round 3, Kaya 2026-07-13): Glass · Plasma · Aurora ·          #
# Spatial Light — headlined by Glass, a 1:1 derivation of the ratified A/B    #
# artifact's glass side (artifacts_claude/tct_bias_glass_ab.html).            #
# --------------------------------------------------------------------------- #

_GLASS_FAMILY_ALL = ("Glass", "Plasma", "Aurora", "Spatial Light")


def _srgb_to_linear(c: int) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG 2.x contrast ratio — (L1 + 0.05) / (L2 + 0.05), L1 >= L2."""
    l_a, l_b = _relative_luminance(hex_a), _relative_luminance(hex_b)
    l_a, l_b = max(l_a, l_b), min(l_a, l_b)
    return (l_a + 0.05) / (l_b + 0.05)


@pytest.mark.parametrize("name", _GLASS_FAMILY_ALL)
def test_glass_family_text_and_muted_meet_the_contrast_floor(name):
    """House floor (task brief): text-vs-panel >= 4.5:1, muted-vs-panel >=
    3:1 — computed from the shipped hex, never eyeballed."""
    preset = next(p for p in style.BUILTIN_PRESETS if p["name"] == name)
    ov = preset["overrides"]
    assert _contrast_ratio(ov["text"], ov["panel"]) >= 4.5
    assert _contrast_ratio(ov["muted"], ov["panel"]) >= 3.0


def test_glass_preset_is_1to1_with_the_ratified_artifact():
    """"Glass" reproduces the ratified A/B artifact's side B exactly for the
    three tokens the artifact itself never varies (its --text/--muted/--accent
    custom properties are the SAME in both the Slate and Glass skins) — these
    must be verbatim, not merely close."""
    glass = next(p for p in style.BUILTIN_PRESETS if p["name"] == "Glass")
    ov = glass["overrides"]
    assert ov["text"].upper() == "#E9EDF5"
    assert ov["muted"].upper() == "#98A1B5"
    assert ov["accent"].upper() == "#5AA9FF"
    assert glass["glass"] == style.DEFAULT_GLASS_AMOUNT     # "the full tinted material"
    # canvas/panel/well/hairline are DERIVED (artifact literals over the
    # preset's own ambient-biased canvas) — pin the derivation itself rather
    # than a magic hex, so a future _blend/_GLASS_CARD_FG_DARK change can't
    # silently drift this preset out of sync with the shipped v6 pass it
    # borrows its card/well recipe from.
    canvas = style._glass_family_canvas("#2A6FE0")
    assert ov["canvas"].lower() == canvas.lower()
    assert ov["panel"].lower() == style._blend(
        style._GLASS_CARD_FG_DARK, canvas, style._GLASS_CARD_ALPHA).lower()
    assert ov["well"].lower() == style._blend(
        style._GLASS_WELL_FG_DARK, canvas, style._GLASS_WELL_ALPHA).lower()


def test_aurora_teal_is_visually_distinct_from_the_sim_safety_token():
    """The artifact's own cyan glow (rgba(65,216,228,·)) is byte-identical to
    SIM_PURPLE — Aurora must not reuse it verbatim (law 6: sim can never pass
    as real), and the distinctness must be more than a rounding difference."""
    aurora = next(p for p in style.BUILTIN_PRESETS if p["name"] == "Aurora")
    ov = aurora["overrides"]

    def _rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def _dist(a, b):
        ra, ga, ba = _rgb(a)
        rb, gb, bb = _rgb(b)
        return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5

    for token in ("accent", "canvas", "panel", "well"):
        assert ov[token].lower() != style.SIM_PURPLE.lower()
    assert _dist(ov["accent"], style.SIM_PURPLE) > 40
    assert _dist(ov["accent"], style.OK_GREEN) > 40


@pytest.mark.parametrize("name", _GLASS_FAMILY_ALL)
def test_glass_family_preset_loads_applies_and_builds_one_panel(tmp_path, name):
    """Load -> apply -> construct one panel smoke -> no crash, correct accent
    resolved (task brief). Uses gui.panel_kit.Card — the same lightweight
    cockpit-kit surface gui/theme_editor.py itself is built from — rather than
    a full device panel, so this stays independent of any panel-owning beat."""
    from gui.panel_kit import Card
    from gui.theme_editor import ThemeEditorDialog

    _app()
    preset = next(p for p in style.BUILTIN_PRESETS if p["name"] == name)
    dlg = ThemeEditorDialog(mode=preset["mode"], settings=_tmp_settings(tmp_path))
    names = [dlg._preset_list.item(i).text()
             for i in range(dlg._preset_list.count())]
    dlg._preset_list.setCurrentRow(names.index(name))
    dlg._apply()

    live = style.DARK if preset["mode"] == "dark" else style.LIGHT
    assert live["accent"].lower() == preset["overrides"]["accent"].lower()

    card = Card("Smoke")
    card.setStyleSheet(style.build_qss(live))
    assert card.objectName() == "cardPane"


# =========================================================================== #
# ROUND 3 (beat C2): the "Backdrop" combo — Windows 11 DWM system material    #
# =========================================================================== #
# The DWM/ctypes mechanics (support probe, native calls, apply/reset,
# app-wide fan-out, apply-order-vs-opacity, the C1 risk-note palette fix, and
# detached-window construction) are all covered in tests/test_backdrop.py,
# which already owns the _force_supported/_recording_dwm monkeypatch seams.
# This section is scoped to what is genuinely THIS dialog's own behaviour:
# the combo widget reacting to backdrop.is_backdrop_supported().

def _force_backdrop_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22621)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")


def _force_backdrop_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "offscreen")


def test_backdrop_combo_disabled_with_tooltip_when_unsupported(tmp_path, monkeypatch):
    """The real offscreen test host is already unsupported by construction,
    but force it explicitly so this stays true regardless of what CI happens
    to run on."""
    _force_backdrop_unsupported(monkeypatch)
    dlg = _dialog(tmp_path)
    assert dlg._backdrop_combo.isEnabled() is False
    tooltip = dlg._backdrop_combo.toolTip()
    assert "22H2" in tooltip or "22621" in tooltip
    assert tooltip.strip() != ""


def test_backdrop_combo_enabled_and_live_previewing_when_supported(tmp_path, monkeypatch):
    """When the probes say a real backdrop is available, the combo is
    enabled, its tooltip stops being the "why disabled" explanation, and
    picking a value live-previews through the SAME apply_window_backdrop
    fan-out the dialog's Apply button uses (no need to click Apply)."""
    _force_backdrop_supported(monkeypatch)
    _recording_dwm = _install_recording_dwm(monkeypatch)
    dlg = _dialog(tmp_path)
    assert dlg._backdrop_combo.isEnabled() is True
    assert "22H2" not in dlg._backdrop_combo.toolTip()

    idx = dlg._backdrop_combo.findData("mica")
    dlg._backdrop_combo.setCurrentIndex(idx)

    assert style.get_window_backdrop() == "mica"
    assert dlg._draft_backdrop == "mica"
    assert ("set_attr", 38, backdrop.DWMSBT_MAINWINDOW) in _recording_dwm
    style.reset_theme_customization()


def test_backdrop_combo_defaults_to_none_and_lists_the_three_kinds(tmp_path):
    dlg = _dialog(tmp_path)
    items = [dlg._backdrop_combo.itemData(i) for i in range(dlg._backdrop_combo.count())]
    assert items == ["none", "mica", "acrylic"]
    assert dlg._backdrop_combo.currentData() == "none"
    assert dlg._draft_backdrop == "none"


def test_backdrop_choice_persists_even_while_the_combo_is_disabled(tmp_path, monkeypatch):
    """Ship law: the pick is saved regardless of whether THIS host can render
    it — a laptop dev session must be able to configure the setting for the
    Win11 22H2 bench it will actually run on."""
    _force_backdrop_unsupported(monkeypatch)
    settings = _tmp_settings(tmp_path)
    from gui.theme_editor import ThemeEditorDialog
    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    assert dlg._backdrop_combo.isEnabled() is False

    idx = dlg._backdrop_combo.findData("acrylic")
    dlg._backdrop_combo.setCurrentIndex(idx)   # programmatic set still fires
    dlg._apply()

    assert style.get_window_backdrop() == "acrylic"
    style.reset_theme_customization()
    style.load_theme_customization(settings)
    assert style.get_window_backdrop() == "acrylic"
    style.reset_theme_customization()


def test_backdrop_combo_survives_headless_construction_and_theme_switch(tmp_path):
    """Same smoke shape as test_dialog_theme_switch_smoke_and_mode_retarget:
    headless construction + a real mode switch must not crash and must keep
    the combo in sync with the draft."""
    dlg = _dialog(tmp_path, mode="dark")
    style.set_window_backdrop("mica")
    dlg.refresh_theme("light")
    assert dlg._draft_backdrop == "mica"
    assert dlg._backdrop_combo.currentData() == "mica"
    dlg.refresh_theme("dark")
    assert dlg._backdrop_combo.currentData() == "mica"
    style.reset_theme_customization()


def test_backdrop_applied_before_opacity_from_the_dialogs_apply_button(tmp_path, monkeypatch):
    """_apply() must push backdrop before opacity too -- not just the
    tct_gui.py fan-out call sites tests/test_backdrop.py covers."""
    from PySide6.QtWidgets import QMainWindow

    _force_backdrop_supported(monkeypatch)
    calls = _install_recording_dwm(monkeypatch)
    orig_set_opacity = QMainWindow.setWindowOpacity

    def recording_set_opacity(self, value):
        calls.append(("opacity", value))
        return orig_set_opacity(self, value)

    monkeypatch.setattr(QMainWindow, "setWindowOpacity", recording_set_opacity)

    dlg = _dialog(tmp_path)
    win = QMainWindow()
    try:
        idx = dlg._backdrop_combo.findData("mica")
        dlg._backdrop_combo.setCurrentIndex(idx)
        dlg._opacity_slider.setValue(85)
        calls.clear()

        dlg._apply()

        kinds = [c[0] for c in calls]
        assert "set_attr" in kinds and "opacity" in kinds
        assert kinds.index("set_attr") < kinds.index("opacity")
    finally:
        win.deleteLater()
        style.reset_theme_customization()


# =========================================================================== #
# Beat C3-mini: the dialog's OWN construction closes the "C2 risk note" gap — #
# it must inherit the cockpit's live backdrop/opacity too, not just           #
# gui.detachable_tabs._DetachedWindow (see test_backdrop.py::                 #
# test_detached_window_construction_applies_current_backdrop for that one).   #
# =========================================================================== #

def test_dialog_construction_applies_current_backdrop_and_opacity(tmp_path, monkeypatch):
    """ThemeEditorDialog.__init__ must call style.apply_window_backdrop_to()
    and style.get_window_opacity() (feeding setWindowOpacity) on itself, in
    that order — mirrors _DetachedWindow's construction-time contract.
    Monkeypatches the two style entry points directly (not the DWM ctypes
    layer test_backdrop.py owns): this only needs to prove __init__ reaches
    them, in order, not re-verify the DWM plumbing underneath."""
    calls: list[str] = []
    orig_backdrop = style.apply_window_backdrop_to
    orig_opacity = style.get_window_opacity

    def recording_backdrop(window, kind=None):
        calls.append("backdrop")
        return orig_backdrop(window, kind)

    def recording_opacity():
        calls.append("opacity")
        return orig_opacity()

    monkeypatch.setattr(style, "apply_window_backdrop_to", recording_backdrop)
    monkeypatch.setattr(style, "get_window_opacity", recording_opacity)

    _dialog(tmp_path)

    # get_window_opacity() is ALSO read again later (unrelated) to seed the
    # opacity-slider draft, so assert order + presence rather than an exact
    # count — the construction-time application call is the first one.
    assert "backdrop" in calls and "opacity" in calls
    assert calls.index("backdrop") < calls.index("opacity")


# =========================================================================== #
# Glass-gap fix (2026-07-13): the window's own canvas (QMainWindow/QDialog/   #
# #mainShell — gui.style.build_qss/_canvas_fill) lets a real DWM backdrop     #
# material show through via an rgba() alpha fill, instead of unconditionally  #
# painting an opaque hex directly over the transparent Window-role palette    #
# gui.backdrop._prepare_window_canvas sets up. See                           #
# docs/design/glass_gap_findings.md for the full barrier list/mechanism.      #
# =========================================================================== #

def test_canvas_fill_is_byte_identical_when_backdrop_is_none():
    """Byte-identical-when-off guard: the shipped default (backdrop == "none")
    must render EXACTLY as before this fix existed."""
    assert style.get_window_backdrop() == "none"
    for mode in ("dark", "light"):
        p = style.palette(mode)
        assert style._canvas_fill(p) == p["bg"]
        qss = style.build_qss(p)
        assert f"QMainWindow, QDialog {{ background: {p['bg']}; }}" in qss
        assert f"QWidget#mainShell {{ background: {p['bg']}; }}" in qss
        assert "rgba(" not in qss.split("QMainWindow, QDialog")[1][:80]


def test_canvas_fill_becomes_rgba_alpha_when_backdrop_active():
    """The actual fix: once a real backdrop material is the user's chosen
    preference, the canvas rule stops being a flat opaque hex and starts
    letting DWM through via rgba() alpha."""
    for kind in ("mica", "acrylic"):
        style.set_window_backdrop(kind)
        p = style.palette("dark")
        fill = style._canvas_fill(p)
        assert fill.startswith("rgba(")
        assert fill != p["bg"]
        assert 0.0 < style.BACKDROP_CANVAS_ALPHA < 1.0
        qss = style.build_qss(p)
        assert f"QMainWindow, QDialog {{ background: {fill}; }}" in qss
        assert f"QWidget#mainShell {{ background: {fill}; }}" in qss
    style.reset_theme_customization()


def test_canvas_fill_never_touches_panel_or_readout_surfaces():
    """Scope guard: the passthrough is canvas-only. QFrame#cardPane (every
    panel-kit Card, including ones hosting a pyqtgraph plot or the camera
    view) must stay a fully opaque hex regardless of backdrop state -- a QSS
    selector cannot tell a plot-hosting card from a plain one, so the "content
    stays opaque" hard rule requires leaving the panel role alone entirely."""
    style.set_window_backdrop("acrylic")
    for mode in ("dark", "light"):
        p = style.palette(mode)
        qss = style.build_qss(p)
        idx = qss.index("QFrame#cardPane")
        block = qss[idx: idx + 200]
        assert f"background: {p['panel']};" in block
        assert "rgba(" not in block
    style.reset_theme_customization()


def test_reset_theme_customization_restores_canvas_passthrough_default():
    style.set_window_backdrop("mica")
    assert style._canvas_fill(style.palette("dark")).startswith("rgba(")
    style.reset_theme_customization()
    assert style.get_window_backdrop() == "none"
    assert style._canvas_fill(style.palette("dark")) == style.palette("dark")["bg"]


# =========================================================================== #
# Task 3 (Kaya UX): the Surface-tint slider tooltip must say plainly it mixes   #
# pre-blended fake-glass surface tones, NOT real transparency/blur.             #
# =========================================================================== #

def test_surface_tint_tooltip_disclaims_real_transparency(tmp_path):
    dlg = _dialog(tmp_path)
    tip = dlg._glass_slider.toolTip().lower()
    assert "blur" in tip
    assert "not" in tip
    assert "opacity" in tip and "backdrop" in tip


# =========================================================================== #
# Task 1c: a live DWM material and a layered (<100%) window are mutually        #
# exclusive — while a backdrop is active the opacity slider is pinned to 100%   #
# and disabled, with a VISIBLE note (never a silent clamp).                     #
# =========================================================================== #

def test_backdrop_pins_and_disables_opacity_with_a_visible_note(tmp_path, monkeypatch):
    _force_backdrop_supported(monkeypatch)
    _install_recording_dwm(monkeypatch)
    dlg = _dialog(tmp_path)
    # Default (no backdrop): opacity is fully editable and the note is hidden.
    assert dlg._opacity_slider.isEnabled() is True
    assert dlg._opacity_backdrop_note.isHidden() is True

    dlg._opacity_slider.setValue(88)               # a translucent preference...
    idx = dlg._backdrop_combo.findData("acrylic")
    dlg._backdrop_combo.setCurrentIndex(idx)       # ...suppressed by the material
    assert dlg._opacity_slider.isEnabled() is False
    assert dlg._opacity_slider.value() == 100
    assert dlg._opacity_backdrop_note.isHidden() is False
    assert style.get_window_opacity() == pytest.approx(1.0)

    # Back to none: the slider re-enables and the note hides again.
    dlg._backdrop_combo.setCurrentIndex(dlg._backdrop_combo.findData("none"))
    assert dlg._opacity_slider.isEnabled() is True
    assert dlg._opacity_backdrop_note.isHidden() is True
    style.reset_theme_customization()


# =========================================================================== #
# Task 1c + Adam's persistence follow-up: backdrop (and opacity) AUTO-APPLY and #
# AUTO-PERSIST on change — a chosen backdrop must survive the dialog lifecycle  #
# and a simulated restart, WITH or WITHOUT pressing Apply.                      #
# =========================================================================== #

def test_backdrop_auto_persists_on_combo_change_without_apply(tmp_path):
    """The reported bug's regression guard: pick acrylic in the combo, destroy
    the dialog WITHOUT Apply, simulate a restart (reset globals + reload from
    the store) — the store holds acrylic, get_window_backdrop() returns it, and
    a freshly built dialog shows it."""
    settings = _tmp_settings(tmp_path)
    from gui.theme_editor import ThemeEditorDialog

    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    dlg._backdrop_combo.setCurrentIndex(dlg._backdrop_combo.findData("acrylic"))
    # Persisted immediately, no Apply click:
    assert settings.value("theme/window_backdrop") == "acrylic"
    dlg.deleteLater()

    # Simulated restart: in-memory globals cleared, reloaded from the store.
    style.reset_theme_customization()
    style.load_theme_customization(settings)
    assert style.get_window_backdrop() == "acrylic"

    dlg2 = ThemeEditorDialog(mode="dark", settings=settings)
    assert dlg2._draft_backdrop == "acrylic"
    assert dlg2._backdrop_combo.currentData() == "acrylic"
    dlg2.deleteLater()
    style.reset_theme_customization()


def test_backdrop_still_persists_with_apply_across_restart(tmp_path):
    """The exact flow Kaya used (WITH Apply) must persist just the same."""
    settings = _tmp_settings(tmp_path)
    from gui.theme_editor import ThemeEditorDialog

    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    dlg._backdrop_combo.setCurrentIndex(dlg._backdrop_combo.findData("acrylic"))
    dlg._apply()
    assert style.get_window_backdrop() == "acrylic"
    assert settings.value("theme/window_backdrop") == "acrylic"
    dlg.deleteLater()

    style.reset_theme_customization()
    style.load_theme_customization(settings)
    assert style.get_window_backdrop() == "acrylic"
    style.reset_theme_customization()


def test_window_opacity_auto_persists_on_slider_change_without_apply(tmp_path):
    settings = _tmp_settings(tmp_path)
    from gui.theme_editor import ThemeEditorDialog

    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    dlg._opacity_slider.setValue(88)               # no Apply
    assert settings.value("theme/window_opacity") is not None
    dlg.deleteLater()

    style.reset_theme_customization()
    style.load_theme_customization(settings)
    assert style.get_window_opacity() == pytest.approx(0.88)
    style.reset_theme_customization()


# =========================================================================== #
# Task 2: the "Panel glass (experimental)" switch flags REGISTERED safe panes   #
# (this dialog's own cards) and auto-persists; plots/camera/danger excluded.    #
# =========================================================================== #

def test_panel_glass_switch_flags_registered_dialog_cards_and_persists(tmp_path):
    import gui.panel_kit as panel_kit

    settings = _tmp_settings(tmp_path)
    from gui.theme_editor import ThemeEditorDialog

    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    try:
        # The dialog registered its own four cards on construction.
        assert len(dlg._glass_cards) == 4
        for card in dlg._glass_cards:
            assert card in panel_kit.registered_glass_panes()
            assert not card.property("glassPane")   # opt-in default: off

        dlg._panel_glass_check.setChecked(True)
        for card in dlg._glass_cards:
            assert card.property("glassPane") == "true"
        assert app_settings.theme_panel_glass_enabled(settings) is True

        dlg._panel_glass_check.setChecked(False)
        for card in dlg._glass_cards:
            assert not card.property("glassPane")
        assert app_settings.theme_panel_glass_enabled(settings) is False
    finally:
        dlg._panel_glass_check.setChecked(False)
        panel_kit.set_panel_glass(False)
        dlg.deleteLater()


def test_panel_glass_qss_uses_rgba_panel_tint():
    p = style.palette("dark")
    qss = style.build_qss(p)
    assert 'QFrame#cardPane[glassPane="true"]' in qss
    assert 'QGroupBox[glassPane="true"]' in qss
    assert 0.0 < style.PANEL_GLASS_ALPHA < 1.0
    tint = style._rgba(p["panel"], style.PANEL_GLASS_ALPHA)
    assert tint in qss
