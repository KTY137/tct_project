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


# --------------------------------------------------------------------------- #
# Immersive-dark-mode tint (the "komplett weiss" fix): Mica/Acrylic composes  #
# LIGHT by default unless DWMWA_USE_IMMERSIVE_DARK_MODE(20) is asserted. The   #
# backdrop path must set it explicitly from the caller's theme, BEFORE the     #
# material attach, and must NOT touch it when the caller passes no tint.       #
# --------------------------------------------------------------------------- #

def test_dark_true_asserts_immersive_dark_before_backdrop(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica", dark=True) is True
    # value 1 = dark tint, on attribute 20
    assert ("set_attr", backdrop.DWMWA_USE_IMMERSIVE_DARK_MODE, 1) in calls
    assert backdrop.DWMWA_USE_IMMERSIVE_DARK_MODE == 20
    # ORDER: immersive-dark (20) is set before the material (38) per the
    # documented recipe — some builds ignore a post-attach flip.
    set_attrs = [c for c in calls if c[0] == "set_attr"]
    idx20 = next(i for i, c in enumerate(set_attrs) if c[1] == 20)
    idx38 = next(i for i, c in enumerate(set_attrs) if c[1] == 38)
    assert idx20 < idx38


def test_dark_false_asserts_immersive_light(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "acrylic", dark=False) is True
    assert ("set_attr", backdrop.DWMWA_USE_IMMERSIVE_DARK_MODE, 0) in calls


def test_dark_none_default_never_touches_immersive_flag(monkeypatch):
    """The default (and every non-theme caller/test) must be byte-identical to
    the pre-fix behaviour: attribute 20 is never written."""
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is True
    assert not any(c[0] == "set_attr" and c[1] == 20 for c in calls)


def test_extend_frame_called_before_set_attribute(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    backdrop.apply_backdrop(w, "mica")

    kinds = [c[0] for c in calls]
    assert kinds.index("extend") < kinds.index("set_attr")


def test_translucent_attribute_set_only_after_both_dwm_calls_succeed(monkeypatch):
    """The fail-safe pairing, restated after the GL-island spike (2026-07-13):

    The old contract was "WA_TranslucentBackground is set only after both DWM
    calls succeed". That is now known to be self-defeating — Qt fixes a
    top-level's surface alpha in QWidgetPrivate::create(), so an attribute set
    after the HWND exists yields alphaBufferSize == -1 and the material composites
    NOTHING (measured; see tests/test_backdrop_event_spine.py's order tests).

    The invariant that actually guards the hole therefore moved to the glass
    PIXELS (the glassCanvas property, which is what makes the QSS paint an rgba
    canvas): surface early, pixels only on S_OK. This test pins both halves for
    the success path; the failure path is pinned by the fail-safe tests below."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    w = _make_window()

    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
    assert not w.property(backdrop.CANVAS_GLASS_PROPERTY)
    assert backdrop.apply_backdrop(w, "mica") is True
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
    assert w.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
    # ...and the surface really did get an alpha channel (the whole point).
    assert w.windowHandle().format().alphaBufferSize() >= 8


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
    pick the backdrop kind up at construction, backdrop before opacity.

    The opacity assertion changed in beat G-B1 and the change IS the fix: the
    constructor used to push the RAW stored opacity (0.85 here) onto a window it
    had just attached a material to, which layers it (WS_EX_LAYERED) and
    suppresses that material outright -- so a torn-off panel could never show
    glass. It now goes through style.reassert_window_backdrop, which applies the
    same pin apply_window_opacity has always applied app-wide (see
    test_apply_window_opacity_pinned_to_full_while_backdrop_active). The stored
    preference is untouched and returns when the backdrop goes back to "none"
    (asserted below)."""
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
        # Layered-window pin: fully opaque while the material is live...
        assert win.windowOpacity() == pytest.approx(1.0, abs=1.0 / 255.0)
        # ...and the stored preference survives untouched.
        assert style.get_window_opacity() == pytest.approx(0.85)
    finally:
        win.deleteLater()


def test_detached_window_without_material_keeps_the_stored_opacity(monkeypatch):
    """The pin is ONLY for a live material: with the shipped "none" backdrop a
    torn-off panel still inherits the cockpit's translucency exactly as before
    (byte-identical-when-off guard for the G-B1 opacity change above)."""
    from PySide6.QtWidgets import QLabel
    from gui.detachable_tabs import _DetachedWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()

    style.set_window_opacity(0.85)
    win = _DetachedWindow(QLabel("panel"), "Motor Stage")
    try:
        assert style.get_window_backdrop() == "none"
        assert win.windowOpacity() == pytest.approx(0.85, abs=1.0 / 255.0)
    finally:
        win.deleteLater()


def test_detached_window_construction_skips_backdrop_when_none(monkeypatch):
    """Ship default: a detached window built with the shipped "none" kind
    never touches DWM at all — and never claims the glass canvas.

    CHANGED in G-B1b (Mary's BUG 2 fix), and the change IS the fix: on a
    material-capable host the window now DOES get WA_TranslucentBackground at
    construction (``style.prepare_window_surface`` no longer gates the SURFACE on
    the backdrop preference), because Qt grants a top-level per-pixel alpha
    exactly once — when its native window is created. Gating that on "none" meant
    every window in the shipped default was born without alpha and could never
    gain it while visible, so the live "switch glass on" toggle was unreachable
    by construction. The PIXELS stay gated on DWM success, which is what keeps
    this window visually identical to before: no DWM call, no glassCanvas
    property, and the QSS canvas rule paints the opaque token pre-blend. See
    test_default_backdrop_stays_visually_inert_even_though_the_surface_has_alpha
    for the full inertness pin."""
    from PySide6.QtWidgets import QLabel
    from gui.detachable_tabs import _DetachedWindow

    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    _app()

    win = _DetachedWindow(QLabel("panel"), "Motor Stage")
    try:
        assert calls == []                       # DWM never touched
        assert backdrop.window_has_material(win) is False
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert not win.centralWidget().property(backdrop.CANVAS_GLASS_PROPERTY)
    finally:
        win.deleteLater()


# --------------------------------------------------------------------------- #
# G-B1b / BUG 2 — the surface is negotiated for every material-capable window, #
# the PIXELS stay gated on DWM. The shipped default must remain visually inert #
# even though its windows can now carry alpha. If this ever fails, the fix has  #
# started leaking glass into a build that never asked for it.                  #
# --------------------------------------------------------------------------- #

def test_default_backdrop_stays_visually_inert_even_though_the_surface_has_alpha(monkeypatch):
    """THE regression pin for BUG 2. With backdrop == "none" (shipped default),
    on a fully material-capable host:

    * no DWM call is ever made,
    * no window carries the ``glassCanvas`` property (the underlay law's carrier),
    * the QSS contains NO ``[glassCanvas="true"]`` rule at all, and
    * the canvas rules paint the OPAQUE ``p['bg']`` token pre-blend.

    Only the invisible half changed: the native surface can now carry alpha, and
    "a translucent-capable surface painted with an opaque fill is simply an
    opaque window" (gui/backdrop.py's own underlay law)."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    central = QWidget()
    central.setObjectName("mainShell")
    win.setCentralWidget(central)
    try:
        assert style.get_window_backdrop() == "none"

        assert style.prepare_window_surface(win) is True   # surface: prepared...
        style.apply_theme(app, "dark")
        style.reassert_window_backdrop(win)

        # ...pixels: nothing. Not one DWM call, not one glass property.
        assert calls == []
        assert backdrop.window_has_material(win) is False
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert not central.property(backdrop.CANVAS_GLASS_PROPERTY)

        # The stylesheet has no glass rule to apply even if something DID set the
        # property, and the canvas is the opaque token pre-blend.
        qss = app.styleSheet()
        assert 'glassCanvas' not in qss
        p = style.palette("dark")
        assert f"QMainWindow, QDialog {{ background: {p['bg']}; }}" in qss
        assert f"QWidget#mainShell {{ background: {p['bg']}; }}" in qss
        assert style._canvas_fill(p) == p["bg"]            # opaque, not rgba()
        assert "rgba(" not in style._glass_canvas_qss(p)
        assert style._glass_canvas_qss(p) == ""
    finally:
        win.deleteLater()


def test_prepare_window_surface_is_still_a_noop_on_an_unsupported_host(monkeypatch):
    """The host gate is the one that survived: Linux/macOS/pre-22H2 Windows and
    the offscreen suite never get an alpha surface, glass or no glass."""
    from PySide6.QtWidgets import QMainWindow

    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22000)   # too old
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")
    _app()
    win = QMainWindow()
    try:
        assert style.prepare_window_surface(win) is False
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
    finally:
        win.deleteLater()


def test_a_window_born_under_none_can_still_gain_glass_live(monkeypatch):
    """BUG 2's user-visible point: the cockpit is built under the shipped "none"
    default, is SHOWN, and only then does Kaya pick acrylic. Before the fix that
    window had no alpha surface (born without the attribute) and, being visible,
    refused to have its HWND re-created — so it could never composite the
    material. Now it can."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        assert style.get_window_backdrop() == "none"
        style.prepare_window_surface(win)        # ...as TCTMainWindow.__init__ does
        win.show()                               # realized + visible: no HWND yanking
        assert win.windowHandle().format().alphaBufferSize() >= 8

        style.set_window_backdrop("acrylic")     # the live toggle
        style.reassert_window_backdrop(win)

        assert backdrop.window_has_material(win) is True
        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
        assert win.centralWidget().property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
    finally:
        win.close()
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


# --------------------------------------------------------------------------- #
# G-B1b / BUG 1 — the QSS must be rebuilt on a LIVE backdrop change.           #
#                                                                             #
# The glass-canvas rules only exist in the stylesheet while a material is      #
# preferred (_glass_canvas_qss). The theme editor's backdrop combo went        #
# set_window_backdrop -> persist -> apply_window_backdrop -> apply_window_     #
# opacity and rebuilt NOTHING — so gui.backdrop set glassCanvas="true" on      #
# windows whose material had attached while the installed QSS had no rule      #
# behind that selector. The alpha hole never opened: Kaya saw no glass, while  #
# scripts/glass_probe.py (which hand-adds an apply_theme call) measured it.    #
# --------------------------------------------------------------------------- #

def test_live_backdrop_toggle_rebuilds_the_qss_glass_rule(monkeypatch):
    """The exact _on_backdrop_changed sequence, replayed: after a live
    none -> acrylic flip the glass rule MUST be in the installed stylesheet."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    style.apply_theme(app, "dark")                     # boot: "none" QSS
    assert '[glassCanvas="true"]' not in app.styleSheet()

    # ── theme_editor._on_backdrop_changed, verbatim (minus the persistence) ──
    style.set_window_backdrop("acrylic")
    style.apply_window_backdrop()
    style.apply_window_opacity()

    assert '[glassCanvas="true"]' in app.styleSheet(), (
        "the glass rule is missing from the live stylesheet — a window that "
        "gets glassCanvas=true has nothing to paint and stays opaque")
    p = style.palette("dark")
    assert style._canvas_fill(p).startswith("rgba(")
    assert style._canvas_fill(p) in app.styleSheet()


def test_live_backdrop_toggle_back_to_none_removes_the_glass_rule(monkeypatch):
    """...and the other direction: switching the material off takes the rule
    with it, so the QSS returns to the pre-glass build byte-for-byte."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    style.apply_theme(app, "dark")
    baseline = app.styleSheet()

    style.set_window_backdrop("mica")
    style.apply_window_backdrop()
    assert '[glassCanvas="true"]' in app.styleSheet()

    style.set_window_backdrop("none")
    style.apply_window_backdrop()

    assert '[glassCanvas="true"]' not in app.styleSheet()
    assert app.styleSheet() == baseline


def test_backdrop_fan_out_does_not_rebuild_the_qss_when_the_kind_is_unchanged(monkeypatch):
    """The rebuild is a fix, not a new hot path: a same-kind re-apply (every
    theme toggle re-runs the fan-out) must not re-install the stylesheet — an
    app-wide setStyleSheet re-polishes the ENTIRE widget tree (~9 s at 13k
    widgets, Phase-0)."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    style.set_window_backdrop("mica")
    style.apply_theme(app, "dark")                     # QSS now built WITH mica

    sets: list[str] = []
    real_set = type(app).setStyleSheet
    monkeypatch.setattr(type(app), "setStyleSheet",
                        lambda self, qss: (sets.append(qss), real_set(self, qss))[1])

    style.apply_window_backdrop(app)                   # same kind — no rebuild
    assert sets == []


def test_theme_editor_backdrop_combo_lights_up_the_glass_rule(tmp_path, monkeypatch):
    """The product path itself, through the real dialog widget: picking a
    material in the Backdrop combo must leave the app stylesheet carrying the
    glass rule. This is the test that would have caught the bug Kaya reported as
    "I see no glass"."""
    from PySide6.QtCore import QSettings
    from gui.theme_editor import ThemeEditorDialog

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    style.apply_theme(app, "dark")
    settings = QSettings(str(tmp_path / "theme_test.ini"),
                         QSettings.Format.IniFormat)
    dlg = ThemeEditorDialog(mode="dark", settings=settings)
    try:
        assert '[glassCanvas="true"]' not in app.styleSheet()

        idx = dlg._backdrop_combo.findData("acrylic")
        dlg._backdrop_combo.setCurrentIndex(idx)       # -> _on_backdrop_changed

        assert style.get_window_backdrop() == "acrylic"
        assert '[glassCanvas="true"]' in app.styleSheet()
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- #
# G-B1b / NIT 6 — the reset path is a loss path too.                           #
# --------------------------------------------------------------------------- #

def test_a_failed_reset_falls_back_to_the_opaque_canvas(monkeypatch):
    """_reset_backdrop was the ONE path that could return False without failing
    safe: on a non-zero HRESULT the window kept glassCanvas="true", kept
    WA_TranslucentBackground and stayed in _backdrop_applied_windows — so
    window_has_material() went on reporting True for a material whose state we no
    longer know, and the WS_EX_LAYERED opacity pin keys off exactly that. An
    unknown material is a lost material (underlay law: every loss path clears
    it)."""
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)                  # the attach succeeds...
    _app()
    win = QMainWindow()
    central = QWidget()
    win.setCentralWidget(central)
    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)
        assert backdrop.window_has_material(win) is True

        # ...and now DWM refuses the RESET.
        _recording_dwm(monkeypatch, attr_hr=-1)
        assert backdrop.apply_backdrop(win, "none") is False

        assert backdrop.window_has_material(win) is False
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert not central.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
    finally:
        win.deleteLater()


# --------------------------------------------------------------------------- #
# G-B1b / RISK 5 — a cosmetic repaint must never preempt a run.                #
#                                                                             #
# backdrop.nudge_repaint resizes the top-level by 1 px and back on EVERY       #
# successful re-assert of a live-material window (Show, WinIdChange,           #
# WindowStateChange, post-toggle, the deferred theme pass). That relayouts the #
# dock tree, every pyqtgraph plot and the camera view on the GUI thread of an   #
# app that is already CPU-bound during acquisition.                            #
# --------------------------------------------------------------------------- #

def test_repaint_nudge_is_skipped_while_a_scan_is_running(monkeypatch):
    from PySide6.QtWidgets import QMainWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    nudges: list = []
    monkeypatch.setattr(backdrop, "nudge_repaint", lambda w: nudges.append(w))
    try:
        style.set_window_backdrop("mica")

        style.set_scan_active_provider(lambda: True)        # a run is in flight
        style.reassert_window_backdrop(win, reason="windowstate")
        assert nudges == [], "a 1-px relayout of the cockpit during a scan"

        style.set_scan_active_provider(lambda: False)       # run over
        style.reassert_window_backdrop(win, reason="windowstate")
        assert nudges == [win], "the heal must resume once the run is done"
    finally:
        style.set_scan_active_provider(None)
        win.deleteLater()


def test_scan_gate_defaults_to_not_scanning_and_fails_safe(monkeypatch):
    """Unwired (every test, every script, any embedding without a scan) means
    "not scanning" — and a provider that RAISES must not suppress the repaint
    heal forever either: the gate fails towards the cosmetic repair, never
    towards a permanently stale surface."""
    assert style.scan_is_active() is False           # unwired

    def boom() -> bool:
        raise RuntimeError("run-state source is gone")

    style.set_scan_active_provider(boom)
    try:
        assert style.scan_is_active() is False
    finally:
        style.set_scan_active_provider(None)


# --------------------------------------------------------------------------- #
# G-B2b — the five ENVIRONMENT PROBES the glass contract cannot make itself.   #
#                                                                             #
# gui/glass_env.py is pure (no Qt, no ctypes, AST-pinned), so the five Win32   #
# observations live here, in the quarantine, and it calls them. Every one of   #
# them must fail SOFT: a missing API, a denied registry key, a non-Windows     #
# host, an exploding call ⇒ None ("cannot be asked"), never an exception, and  #
# never a guess — because in the contract False VETOES a tier and True would   #
# promise a material the host cannot render (the one unacceptable failure).    #
#                                                                             #
# The ctypes/winreg PRIMITIVES are monkeypatched in every test below; no test  #
# in this suite ever calls user32/dwmapi/kernel32 or reads the registry.       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("probe", [
    "dwm_composition_probe", "transparency_probe", "high_contrast_probe",
    "remote_session_probe", "battery_saver_probe",
])
def test_every_probe_is_unknown_on_a_non_windows_host(probe, monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "linux")
    assert getattr(backdrop, probe)() is None


@pytest.mark.parametrize("probe", [
    "dwm_composition_probe", "transparency_probe", "high_contrast_probe",
    "remote_session_probe", "battery_saver_probe",
])
def test_every_probe_answers_the_tri_state_on_the_real_host(probe):
    """Whatever machine this is: True, False or None — never a string, never an
    int, never a raise. The contract coerces bool|None and DEGRADES on anything
    else, so a probe that returns 1 instead of True would silently drop the whole
    app to the safe floor."""
    value = getattr(backdrop, probe)()
    assert value is None or isinstance(value, bool), f"{probe}() -> {value!r}"


def test_remote_session_probe_reads_sm_remotesession(monkeypatch):
    seen: list[int] = []

    def fake_metric(index):
        seen.append(index)
        return 1

    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_system_metric", fake_metric)

    assert backdrop.remote_session_probe() is True
    assert seen == [backdrop.SM_REMOTESESSION]      # 4096, winuser.h

    monkeypatch.setattr(backdrop, "_system_metric", lambda index: 0)
    assert backdrop.remote_session_probe() is False


def test_high_contrast_probe_reads_the_hcf_bit(monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "win32")

    # dwFlags carries more than one bit; only HCF_HIGHCONTRASTON means "on".
    monkeypatch.setattr(backdrop, "_high_contrast_flags",
                        lambda: backdrop.HCF_HIGHCONTRASTON | 0x02)
    assert backdrop.high_contrast_probe() is True

    monkeypatch.setattr(backdrop, "_high_contrast_flags", lambda: 0x02)
    assert backdrop.high_contrast_probe() is False


def test_battery_saver_probe_reads_the_power_saving_bit(monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "win32")

    monkeypatch.setattr(backdrop, "_power_status_flag",
                        lambda: backdrop.SYSTEM_STATUS_FLAG_POWER_SAVING_ON)
    assert backdrop.battery_saver_probe() is True

    monkeypatch.setattr(backdrop, "_power_status_flag", lambda: 0)
    assert backdrop.battery_saver_probe() is False


@pytest.mark.parametrize("raw,expected", [(1, True), (0, False), (None, None)])
def test_transparency_probe_maps_the_registry_value(raw, expected, monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_transparency_setting", lambda: raw)
    assert backdrop.transparency_probe() is expected


def _fake_winreg(monkeypatch, *, value=None, error: Exception | None = None):
    """A stand-in ``winreg`` module, so the REAL registry code path
    (``backdrop._transparency_setting``) can be exercised on any host — including
    a Linux runner, where the stdlib module does not exist at all."""
    import sys as _sys
    import types

    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = 0

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def open_key(root, path):
        assert path == backdrop._TRANSPARENCY_KEY
        if error is not None:
            raise error
        return _Key()

    def query(key, name):
        assert name == backdrop._TRANSPARENCY_VALUE
        return value, 4                                  # REG_DWORD

    fake.OpenKey = open_key
    fake.QueryValueEx = query
    monkeypatch.setitem(_sys.modules, "winreg", fake)
    monkeypatch.setattr(backdrop.sys, "platform", "win32")


@pytest.mark.parametrize("value,expected", [(1, True), (0, False)])
def test_transparency_probe_reads_the_personalize_key(value, expected, monkeypatch):
    _fake_winreg(monkeypatch, value=value)
    assert backdrop._transparency_setting() == value
    assert backdrop.transparency_probe() is expected


def test_a_missing_registry_value_is_unknown_not_off(monkeypatch):
    """A fresh profile that never touched Settings ▸ Colors has no
    EnableTransparency value at all. Reading THAT as OFF would veto the material
    on a machine whose transparency is, in fact, on — the fail-soft direction is
    "cannot be asked" (None), never "absent" (False)."""
    _fake_winreg(monkeypatch, error=FileNotFoundError(2, "no such key"))
    assert backdrop._transparency_setting() is None
    assert backdrop.transparency_probe() is None


def test_a_denied_registry_key_is_unknown_too(monkeypatch):
    _fake_winreg(monkeypatch, error=PermissionError(5, "access is denied"))
    assert backdrop._transparency_setting() is None
    assert backdrop.transparency_probe() is None


@pytest.mark.parametrize("primitive,probe", [
    ("_system_metric", "remote_session_probe"),
    ("_high_contrast_flags", "high_contrast_probe"),
    ("_transparency_setting", "transparency_probe"),
    ("_dwm_composition_enabled", "dwm_composition_probe"),
    ("_power_status_flag", "battery_saver_probe"),
])
def test_an_unreadable_primitive_is_unknown_never_a_guess(primitive, probe,
                                                          monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, primitive, lambda *args: None)
    assert getattr(backdrop, probe)() is None


def test_the_primitives_never_raise_whatever_ctypes_does(monkeypatch):
    """The ctypes seam itself. Every primitive swallows the failure and answers
    None — a probe that throws must not be able to take the GUI down (it runs on
    the GUI thread, from probe_environment)."""
    class _Exploding:
        def __getattr__(self, name):
            raise OSError(f"{name}.dll is on fire")

    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop.ctypes, "windll", _Exploding())

    assert backdrop._system_metric(backdrop.SM_REMOTESESSION) is None
    assert backdrop._high_contrast_flags() is None
    assert backdrop._dwm_composition_enabled() is None
    assert backdrop._power_status_flag() is None

    # ...and so do the tri-states built on top of them.
    assert backdrop.remote_session_probe() is None
    assert backdrop.high_contrast_probe() is None
    assert backdrop.dwm_composition_probe() is None
    assert backdrop.battery_saver_probe() is None


def test_the_probes_do_not_gate_on_backdrop_SUPPORT(monkeypatch):
    """Deliberate: these describe the HOST, not our material support. High
    contrast matters on Windows 10 (where WINDOW is refused forever) and under
    the offscreen plugin (where this suite runs) just as much — the FLAT mandate
    is an accessibility rule, not a glass feature. So the probes must answer even
    where is_backdrop_supported() is False."""
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "offscreen")
    monkeypatch.setattr(backdrop, "_high_contrast_flags",
                        lambda: backdrop.HCF_HIGHCONTRASTON)

    assert backdrop.is_backdrop_supported() is False
    assert backdrop.high_contrast_probe() is True


def test_style_never_imports_the_controller():
    """The decoupling that makes the scan gate legal: presentation may ask "is a
    scan running" only through an INJECTED predicate — gui/style.py must not
    import controller/ (composition-root rule,
    docs/design/gui_architecture_plan.md).

    Parsed, not grepped: every import STATEMENT in the module (including the
    function-local ones — style.py imports QApplication that way), so a comment
    that merely mentions the word cannot pass or fail this."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(style))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    offenders = [m for m in imported
                 if m == "controller" or m.startswith("controller.")]
    assert offenders == [], (
        f"gui/style.py imports the controller: {offenders} — the run-state "
        "source must be INJECTED (set_scan_active_provider), not imported")
