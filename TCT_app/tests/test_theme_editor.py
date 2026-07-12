"""Theme editor + style override layer (gui/theme_editor.py, gui/style.py).

Covers the task contract:
- defaults are byte-identical with no user action (recompute == inline dicts);
- glass_amount parametrizes the chrome/strip/edge/edge_shade pre-blends,
  with 0.0 collapsing chrome/strip to opaque panel and both machined edges
  to the uniform hairline;
- safety tokens (danger/armed/sim/error + the crit/warn aliases) have no
  override path: the style setter raises, the dialog draft setter raises,
  no editable swatch exists for them, and a hand-edited preset JSON that
  tries is silently stripped on load;
- an accent override reaches the generated QSS and reset restores it;
- presets round-trip through QSettings JSON;
- persistence round-trips through save/load_theme_customization;
- headless construction + theme-switch smoke for the dialog.

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

    # A fresh dialog over the same settings lists + loads the preset.
    dlg2 = ThemeEditorDialog(mode="dark", settings=settings)
    names = [dlg2._preset_list.item(i).text()
             for i in range(dlg2._preset_list.count())]
    assert names == ["Cockpit Dark", "Lab Light", "My Bench"]
    dlg2._preset_list.setCurrentRow(names.index("My Bench"))
    assert dlg2._draft_overrides == {"accent": "#336699"}
    assert dlg2._draft_glass == pytest.approx(0.40)


def test_malicious_preset_json_cannot_override_danger(tmp_path):
    from gui.theme_editor import PRESETS_KEY
    settings = _tmp_settings(tmp_path)
    settings.setValue(PRESETS_KEY, json.dumps([{
        "name": "Evil", "mode": "dark",
        "overrides": {"danger": "#00ff00", "accent": "#445566"},
        "glass": 1.0, "radius": "m",
    }]))
    settings.sync()
    _app()
    from gui.theme_editor import ThemeEditorDialog
    base_danger = style.DARK["danger"]
    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    names = [dlg._preset_list.item(i).text()
             for i in range(dlg._preset_list.count())]
    dlg._preset_list.setCurrentRow(names.index("Evil"))
    # The safety key was stripped on load; only the accent survives.
    assert dlg._draft_overrides == {"accent": "#445566"}
    dlg._apply()
    assert style.DARK["danger"] == base_danger
    assert style.DARK["accent"] == "#445566"
    assert "danger" not in style.theme_overrides("dark")


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
