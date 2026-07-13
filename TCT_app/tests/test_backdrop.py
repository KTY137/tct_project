"""Headless tests for ``gui/backdrop.py`` (Windows acrylic/mica backdrop core).

The suite runs under ``QT_QPA_PLATFORM=offscreen`` (no DWM, no real compositor),
so every test either drives the injectable support probes to exercise the
matrix, or monkeypatches the ``_dwm_*`` native-call functions with recording
stubs so no test ever touches ctypes/dwmapi.

Beat C2 additionally covers the ``gui/style.py`` wiring on top of this core
(settings persistence, the app-wide fan-out, the apply-order contract with
window opacity, and the C1 risk-note fix for a backdrop reset) — style.py
owns the theme and reaches into this module's monkeypatch seams the same way
the core tests above do, so those tests live here rather than duplicating the
``_force_supported``/``_recording_dwm`` helpers into ``test_theme_editor.py``.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

import gui.backdrop as backdrop
from gui import style


@pytest.fixture(autouse=True)
def _reset_style_backdrop_state():
    """gui/style.py's window_backdrop (and everything else
    ``reset_theme_customization`` covers) is module-global state — restore
    the shipped defaults after every test in this file, same idiom as
    ``tests/test_theme_editor.py``'s ``_reset_style_state``. Unconditional
    (cheap) so a test author never has to remember it."""
    yield
    style.reset_theme_customization()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_window() -> QWidget:
    _app()
    return QWidget()


def _force_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive is_backdrop_supported() to True regardless of the real host."""
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22621)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")


def _recording_dwm(monkeypatch: pytest.MonkeyPatch, extend_hr: int = 0,
                    attr_hr: int = 0):
    """Patch both DWM calls with recorders; returns the shared call log."""
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


# --------------------------------------------------------------------------- #
# Support matrix                                                             #
# --------------------------------------------------------------------------- #

def test_unsupported_old_build(monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22000)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")
    assert backdrop.is_backdrop_supported() is False


def test_supported_on_win11_22h2_with_native_platform(monkeypatch):
    _force_supported(monkeypatch)
    assert backdrop.is_backdrop_supported() is True


def test_unsupported_offscreen_platform(monkeypatch):
    # Even with a fully qualifying build/OS, the offscreen Qt plugin (what
    # this whole suite runs under) must stay unsupported -- no DWM exists.
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22621)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "offscreen")
    assert backdrop.is_backdrop_supported() is False


def test_unsupported_non_windows(monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "linux")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 99999)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")
    assert backdrop.is_backdrop_supported() is False


# --------------------------------------------------------------------------- #
# apply_backdrop -- supported host, recorded DWM calls                       #
# --------------------------------------------------------------------------- #

def test_apply_mica_records_dwmsbt_mainwindow(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is True
    assert ("set_attr", 38, backdrop.DWMSBT_MAINWINDOW) in calls
    assert backdrop.DWMSBT_MAINWINDOW == 2


def test_apply_acrylic_records_dwmsbt_transientwindow(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "acrylic") is True
    assert ("set_attr", 38, backdrop.DWMSBT_TRANSIENTWINDOW) in calls
    assert backdrop.DWMSBT_TRANSIENTWINDOW == 3


def test_extend_frame_called_before_set_attribute(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    backdrop.apply_backdrop(w, "mica")

    kinds = [c[0] for c in calls]
    assert kinds.index("extend") < kinds.index("set_attr")


def test_translucent_attribute_set_only_after_both_dwm_calls_succeed(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    w = _make_window()

    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
    assert backdrop.apply_backdrop(w, "mica") is True
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True


# --------------------------------------------------------------------------- #
# DWM fix (Prometheus item a): the QMainWindow CENTRAL widget (#mainShell) must #
# also go translucent, or the top-level's translucency never reaches DWM.       #
# --------------------------------------------------------------------------- #

def test_central_widget_translucency_set_and_cleared_symmetrically(monkeypatch):
    """A QMainWindow's client is painted by its central #mainShell child, not
    the window — so the child must carry WA_TranslucentBackground too, set on
    apply and cleared on reset, symmetric with the top-level."""
    from PySide6.QtWidgets import QMainWindow, QWidget

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    central = QWidget()
    win.setCentralWidget(central)
    try:
        assert central.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
        assert backdrop.apply_backdrop(win, "acrylic") is True
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert central.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True

        assert backdrop.apply_backdrop(win, "none") is True
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
        assert central.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
    finally:
        win.deleteLater()


def test_plain_dialog_has_no_central_widget_step(monkeypatch):
    """A flat QDialog IS the widget covering its own client, so the central-
    widget step must be a clean no-op there (it has no centralWidget)."""
    from PySide6.QtWidgets import QDialog

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    dlg = QDialog()
    try:
        assert backdrop.apply_backdrop(dlg, "mica") is True
        assert dlg.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert backdrop._canvas_widgets(dlg) == [dlg]
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- #
# Unsupported host                                                           #
# --------------------------------------------------------------------------- #

def test_unsupported_host_returns_false_and_never_touches_dwm(monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22000)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is False
    assert calls == []
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


# --------------------------------------------------------------------------- #
# kind == "none" reset                                                       #
# --------------------------------------------------------------------------- #

def test_none_after_applied_backdrop_resets_and_clears_translucent(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "acrylic") is True
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True

    calls.clear()
    assert backdrop.apply_backdrop(w, "none") is True
    assert ("set_attr", 38, backdrop.DWMSBT_NONE) in calls
    assert backdrop.DWMSBT_NONE == 1
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


def test_none_without_a_prior_apply_is_a_true_noop(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "none") is True
    assert calls == []


# --------------------------------------------------------------------------- #
# Invalid kind                                                               #
# --------------------------------------------------------------------------- #

def test_invalid_kind_raises_value_error(monkeypatch):
    _force_supported(monkeypatch)
    w = _make_window()
    with pytest.raises(ValueError):
        backdrop.apply_backdrop(w, "glass")


# --------------------------------------------------------------------------- #
# DWM failure simulation                                                     #
# --------------------------------------------------------------------------- #

def test_dwm_nonzero_hresult_on_set_attribute_fails_safe(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch, extend_hr=0, attr_hr=1)  # nonzero HRESULT == failure
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is False
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


def test_dwm_nonzero_hresult_on_extend_frame_fails_safe(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch, extend_hr=1, attr_hr=0)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is False
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


def test_dwm_extend_frame_raises_fails_safe(monkeypatch):
    _force_supported(monkeypatch)
    w = _make_window()

    def raising_extend(hwnd):
        raise OSError("simulated DWM failure")

    monkeypatch.setattr(backdrop, "_dwm_extend_frame", raising_extend)
    monkeypatch.setattr(backdrop, "_dwm_set_window_attribute",
                         lambda hwnd, attribute, value: 0)

    assert backdrop.apply_backdrop(w, "acrylic") is False
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


def test_dwm_set_attribute_raises_fails_safe(monkeypatch):
    _force_supported(monkeypatch)
    w = _make_window()

    def raising_set_attr(hwnd, attribute, value):
        raise OSError("simulated DWM failure")

    monkeypatch.setattr(backdrop, "_dwm_extend_frame", lambda hwnd: 0)
    monkeypatch.setattr(backdrop, "_dwm_set_window_attribute", raising_set_attr)

    assert backdrop.apply_backdrop(w, "acrylic") is False
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


# --------------------------------------------------------------------------- #
# BACKDROP_KINDS sanity                                                      #
# --------------------------------------------------------------------------- #

def test_backdrop_kinds_tuple():
    assert backdrop.BACKDROP_KINDS == ("none", "mica", "acrylic")


# --------------------------------------------------------------------------- #
# gui.style wiring (Beat C2) -- settings persistence                         #
# --------------------------------------------------------------------------- #

def test_window_backdrop_defaults_to_none():
    assert style.get_window_backdrop() == "none"


def test_set_window_backdrop_round_trips_the_valid_kinds():
    for kind in backdrop.BACKDROP_KINDS:
        assert style.set_window_backdrop(kind) == kind
        assert style.get_window_backdrop() == kind


@pytest.mark.parametrize("garbage", [None, "", "   ", "glass", "MICA_TYPO", 42, object()])
def test_set_window_backdrop_falls_back_to_none_on_garbage(garbage):
    """Mirrors set_window_opacity's fail-opaque philosophy: garbage is never
    trusted as-is, it drops to the safe/opaque end ("none"), never raises."""
    style.set_window_backdrop("mica")
    assert style.set_window_backdrop(garbage) == "none"
    assert style.get_window_backdrop() == "none"


def test_set_window_backdrop_is_case_and_whitespace_insensitive():
    assert style.set_window_backdrop(" Mica ".strip()) == "mica"
    assert style.set_window_backdrop("ACRYLIC") == "acrylic"


def test_window_backdrop_round_trips_through_qsettings(tmp_path):
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "backdrop_roundtrip.ini"), QSettings.Format.IniFormat)
    style.set_window_backdrop("acrylic")
    style.save_theme_customization(settings)

    style.reset_theme_customization()
    assert style.get_window_backdrop() == "none"        # reset really did reset

    style.load_theme_customization(settings)
    assert style.get_window_backdrop() == "acrylic"


def test_hostile_persisted_backdrop_is_dropped_to_none_not_obeyed(tmp_path):
    """A hand-edited registry entry naming an unknown kind (a typo, a kind
    retired in a future rename) is never obeyed -- same fail-opaque contract
    as a live call to set_window_backdrop with garbage."""
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "backdrop_hostile.ini"), QSettings.Format.IniFormat)
    settings.setValue("theme/window_backdrop", "acrylic-glow-9000")

    style.load_theme_customization(settings)
    assert style.get_window_backdrop() == "none"


def test_absent_backdrop_key_means_shipped_default(tmp_path):
    """An ABSENT key means the shipped default, not "keep whatever was
    already loaded" -- same contract test_theme_editor.py already runs for
    window_opacity (load_theme_customization DEFINES the state)."""
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "backdrop_absent.ini"), QSettings.Format.IniFormat)
    style.set_window_backdrop("mica")
    style.load_theme_customization(settings)
    assert style.get_window_backdrop() == "none"


# --------------------------------------------------------------------------- #
# gui.style wiring (Beat C2) -- apply_window_backdrop fan-out                #
# --------------------------------------------------------------------------- #

def test_apply_window_backdrop_fans_out_to_top_levels_and_skips_transients(monkeypatch):
    from PySide6.QtWidgets import QDialog, QMainWindow, QMenu

    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    app = _app()
    win, dlg, menu = QMainWindow(), QDialog(), QMenu()
    try:
        style.set_window_backdrop("mica")
        kind = style.apply_window_backdrop(app)

        assert kind == "mica"
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert dlg.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        # Transient chrome (menus/tooltips/splashes) is skipped -- same
        # _is_transient_window rule apply_window_opacity already uses.
        assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
        assert ("set_attr", 38, backdrop.DWMSBT_MAINWINDOW) in calls
    finally:
        win.deleteLater()
        dlg.deleteLater()
        menu.deleteLater()


def test_apply_window_backdrop_to_targets_a_single_window(monkeypatch):
    """The single-window helper detachable_tabs/tct_gui startup use -- must
    not touch any OTHER top-level window."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win, other = QMainWindow(), QMainWindow()
    try:
        assert style.apply_window_backdrop_to(win, "acrylic") == "acrylic"
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert other.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
    finally:
        win.deleteLater()
        other.deleteLater()


def test_apply_window_backdrop_default_arg_resolves_via_qapplication_instance(monkeypatch):
    """No explicit app= -- must fall back to QApplication.instance() (the
    real call sites in tct_gui/theme_editor never pass one) and still reach
    every live top-level window, exactly like the explicit-app case above."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    try:
        style.set_window_backdrop("mica")
        kind = style.apply_window_backdrop()   # no app= argument at all

        assert kind == "mica"
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
    finally:
        win.deleteLater()


# --------------------------------------------------------------------------- #
# gui.style wiring (Beat C2) -- apply-order contract (backdrop before        #
# opacity, see gui.style.apply_window_backdrop's docstring)                  #
# --------------------------------------------------------------------------- #

def test_apply_order_backdrop_before_opacity(monkeypatch):
    """Both fan-outs called in the SAME order tct_gui startup / _toggle_theme
    and the theme editor's _apply() use them: the backdrop's native DWM call
    for a window must land before that window's setWindowOpacity call."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    orig_set_opacity = QMainWindow.setWindowOpacity

    def recording_set_opacity(self, value):
        calls.append(("opacity", value))
        return orig_set_opacity(self, value)

    monkeypatch.setattr(QMainWindow, "setWindowOpacity", recording_set_opacity)

    app = _app()
    win = QMainWindow()
    try:
        style.set_window_backdrop("acrylic")
        style.set_window_opacity(0.9)

        style.apply_window_backdrop(app)     # apply-order contract: first...
        style.apply_window_opacity(app)      # ...then opacity.

        kinds = [c[0] for c in calls]
        assert "set_attr" in kinds and "opacity" in kinds
        assert kinds.index("set_attr") < kinds.index("opacity")
    finally:
        win.deleteLater()


# --------------------------------------------------------------------------- #
# gui.style wiring (Beat C2) -- C1 risk-note fix: no default-grey flash      #
# --------------------------------------------------------------------------- #

def test_backdrop_reset_to_none_reapplies_theme_palette_no_flash(monkeypatch):
    """apply_backdrop(window, "none") (gui.backdrop._clear_window_canvas)
    resets the window's own QPalette to a bare default -- style.py's
    apply_window_backdrop_to must immediately re-sync it to the CURRENT
    theme palette and force a repolish, never leaving a stray default-Qt-
    grey frame. See gui.style._reassert_window_palette."""
    from PySide6.QtWidgets import QMainWindow
    from PySide6.QtGui import QPalette

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    style.apply_theme(app, "dark")
    win = QMainWindow()
    try:
        style.set_window_backdrop("mica")
        style.apply_window_backdrop(app)
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True

        repolish_calls = []
        monkeypatch.setattr(style, "repolish", lambda w: repolish_calls.append(w))

        style.set_window_backdrop("none")
        style.apply_window_backdrop(app)

        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
        assert win in repolish_calls, "reset must force an immediate QSS repolish"
        # Never Qt's own built-in default grey -- the CURRENT theme canvas.
        got = win.palette().color(QPalette.ColorRole.Window).name().lower()
        want = style.DARK["bg"].lower()
        assert got == want
    finally:
        win.deleteLater()


def test_backdrop_reset_without_a_prior_apply_still_reapplies_palette(monkeypatch):
    """The true-no-op path in gui.backdrop (kind "none" on a window that was
    never given a real backdrop) must still get the style.py resync -- it is
    unconditional on kind == "none", not gated on backdrop.py having actually
    changed anything (see apply_window_backdrop_to)."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    style.apply_theme(app, "light")
    win = QMainWindow()
    try:
        repolish_calls = []
        monkeypatch.setattr(style, "repolish", lambda w: repolish_calls.append(w))

        style.set_window_backdrop("none")
        style.apply_window_backdrop(app)

        assert win in repolish_calls
    finally:
        win.deleteLater()


def test_backdrop_reassert_never_runs_while_a_real_material_is_applied(monkeypatch):
    """The palette resync must NEVER fire for kind != "none" -- a live mica/
    acrylic window needs its transparent Window-role palette
    (gui.backdrop._prepare_window_canvas) for the DWM material to show
    through; resyncing would silently paint over it."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    try:
        repolish_calls = []
        monkeypatch.setattr(style, "repolish", lambda w: repolish_calls.append(w))

        style.set_window_backdrop("mica")
        style.apply_window_backdrop(app)

        assert repolish_calls == []
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
    finally:
        win.deleteLater()


# --------------------------------------------------------------------------- #
# Theme-editor button-corruption fix (2026-07-13): a reissued active-material #
# apply (every _toggle_theme call does this for every top-level window, incl.#
# ThemeEditorDialog/SettingsWindow) must force a repaint -- see              #
# apply_window_backdrop_to's docstring for the full mechanism.               #
# --------------------------------------------------------------------------- #

def test_active_material_apply_forces_a_repaint(monkeypatch):
    """First apply of a real material must schedule a repaint (window.update())
    so an already-shown window's re-touched WA_TranslucentBackground/palette
    does not leave stale pixels behind until the next unrelated paint event."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    try:
        update_calls = []
        monkeypatch.setattr(QMainWindow, "update", lambda self: update_calls.append(self))

        assert style.apply_window_backdrop_to(win, "mica") == "mica"
        assert win in update_calls
    finally:
        win.deleteLater()


def test_active_material_reapply_forces_a_repaint_every_time_not_a_repolish(monkeypatch):
    """The actual bug shape: EVERY theme toggle re-applies the SAME already-
    active kind (see apply_window_backdrop's app-wide fan-out) -- the repaint
    must fire on every one of those reissues, not just the first, and it must
    go through window.update(), never style.repolish() (the sibling test
    above pins repolish() to the palette-reset "none" path only -- reusing it
    here would silently paint over the transparent Window-role palette the
    DWM material needs, exactly what that test guards against)."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    try:
        update_calls = []
        monkeypatch.setattr(QMainWindow, "update", lambda self: update_calls.append(self))
        repolish_calls = []
        monkeypatch.setattr(style, "repolish", lambda w: repolish_calls.append(w))

        style.set_window_backdrop("mica")
        style.apply_window_backdrop_to(win)             # first apply
        assert win in update_calls

        update_calls.clear()
        style.apply_window_backdrop_to(win)             # reissue, same kind
        assert win in update_calls, "a same-kind reissue must still repaint"
        assert repolish_calls == []
    finally:
        win.deleteLater()


def test_unsupported_host_active_kind_never_forces_a_repaint(monkeypatch):
    """Byte-identical-when-off guard: on a host that cannot apply the material
    at all (nothing changed), apply_window_backdrop_to must not touch
    window.update() either -- no observable side effect beyond today's
    behaviour when the backdrop mechanism is a true no-op."""
    from PySide6.QtWidgets import QMainWindow

    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22000)   # too old
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    try:
        update_calls = []
        monkeypatch.setattr(QMainWindow, "update", lambda self: update_calls.append(self))

        assert style.apply_window_backdrop_to(win, "mica") == "mica"
        assert update_calls == []
    finally:
        win.deleteLater()


def test_backdrop_none_repaint_behaviour_is_unchanged(monkeypatch):
    """Byte-identical-when-off guard for the "none" branch itself: this fix
    only touches the kind != "none" path -- the shipped default (backdrop
    off) must keep going through _reassert_window_palette/repolish exactly as
    before, never window.update()."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    try:
        update_calls = []
        monkeypatch.setattr(QMainWindow, "update", lambda self: update_calls.append(self))
        repolish_calls = []
        monkeypatch.setattr(style, "repolish", lambda w: repolish_calls.append(w))

        assert style.apply_window_backdrop_to(win, "none") == "none"
        assert update_calls == []
        assert win in repolish_calls
    finally:
        win.deleteLater()


# --------------------------------------------------------------------------- #
# gui.style wiring (Beat C2) -- detached windows pick up the current kind    #
# --------------------------------------------------------------------------- #

def test_detached_window_construction_applies_current_backdrop(monkeypatch):
    """gui/detachable_tabs._DetachedWindow is created AFTER the setting is
    applied, so -- mirroring window opacity's existing contract -- it must
    pick the backdrop kind up at construction, backdrop before opacity."""
    from PySide6.QtWidgets import QLabel
    from gui.detachable_tabs import _DetachedWindow

    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    _app()

    style.set_window_backdrop("acrylic")
    style.set_window_opacity(0.85)
    win = _DetachedWindow(QLabel("panel"), "Motor Stage")
    try:
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert ("set_attr", 38, backdrop.DWMSBT_TRANSIENTWINDOW) in calls
        assert win.windowOpacity() == pytest.approx(0.85, abs=1.0 / 255.0)
    finally:
        win.deleteLater()


def test_detached_window_construction_skips_backdrop_when_none(monkeypatch):
    """Ship default: a detached window built with the shipped "none" kind
    never touches DWM at all."""
    from PySide6.QtWidgets import QLabel
    from gui.detachable_tabs import _DetachedWindow

    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    _app()

    win = _DetachedWindow(QLabel("panel"), "Motor Stage")
    try:
        assert calls == []
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
    finally:
        win.deleteLater()


# --------------------------------------------------------------------------- #
# DWM fix (Prometheus item c): a layered (<100%) window suppresses the DWM     #
# material, so apply_window_opacity must PIN every window to fully opaque while #
# a backdrop is active — the stored preference is kept and returns on "none".  #
# --------------------------------------------------------------------------- #

def test_apply_window_opacity_pinned_to_full_while_backdrop_active(monkeypatch):
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    try:
        style.set_window_backdrop("acrylic")
        style.set_window_opacity(0.85)          # the stored preference...
        style.apply_window_opacity(app)         # ...but the window is pinned full
        assert win.windowOpacity() == pytest.approx(1.0, abs=1.0 / 255.0)
        # Preference is NOT destroyed — only the pushed value is pinned.
        assert style.get_window_opacity() == pytest.approx(0.85)

        # Turning the backdrop off restores the stored opacity on the window.
        style.set_window_backdrop("none")
        style.apply_window_opacity(app)
        assert win.windowOpacity() == pytest.approx(0.85, abs=1.0 / 255.0)
    finally:
        win.deleteLater()


def test_apply_window_opacity_not_pinned_when_backdrop_is_none(monkeypatch):
    """Byte-identical-when-off guard: with the shipped "none" backdrop the pin
    is inert — a translucent window stays translucent exactly as before."""
    from PySide6.QtWidgets import QMainWindow

    app = _app()
    win = QMainWindow()
    try:
        assert style.get_window_backdrop() == "none"
        style.set_window_opacity(0.9)
        style.apply_window_opacity(app)
        assert win.windowOpacity() == pytest.approx(0.9, abs=1.0 / 255.0)
    finally:
        win.deleteLater()


# --------------------------------------------------------------------------- #
# DWM fix (Prometheus item b): main.py requests an alpha-carrying default       #
# window surface BEFORE the QApplication, so a QMainWindow client can carry     #
# per-pixel alpha to DWM. Scoped/merged so it never clobbers the plot/QML stack.#
# --------------------------------------------------------------------------- #

def test_default_surface_format_requests_alpha_for_translucency():
    from PySide6.QtGui import QSurfaceFormat
    import main

    before = QSurfaceFormat.defaultFormat()
    try:
        main._enable_translucent_window_surface()
        assert QSurfaceFormat.defaultFormat().alphaBufferSize() >= 8
    finally:
        QSurfaceFormat.setDefaultFormat(before)
