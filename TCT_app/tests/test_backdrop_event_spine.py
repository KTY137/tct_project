"""Headless tests for the material EVENT SPINE (beat G-B1).

The glass council's SYNTHESIS (§2.3/§2.4, Fenrir riders 1 + 4) says a DWM
attribute is not a setting: it is state on ONE HWND, and it dies with that HWND
— silently, with a full history of S_OK. Two symptoms Kaya confirmed live on
2026-07-13 fall straight out of that:

* **A** — close and reopen the theme window and the material area goes BLACK.
* **B** — a detached panel window shows no glass at all, even though its
  constructor calls the backdrop path.

These tests pin the fix set:

1. the ONE ordered re-assert chain (ExtendFrame → attr 20 → attr 38 → canvas),
2. the event spine that re-runs it (WinIdChange, Show, WindowStateChange, the
   OS theme/palette events),
3. the **underlay law** — no window is ever translucent while its material is
   not verifiably attached, so a lost attribute degrades to token glass and
   NEVER to a black hole,
4. the detached-window path going through the same single function.

Everything runs under ``QT_QPA_PLATFORM=offscreen`` with the DWM calls replaced
by recorders — no test ever touches ctypes/dwmapi or a real compositor.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QLabel, QMainWindow, QWidget,
)

import gui.backdrop as backdrop
from gui import style


@pytest.fixture(autouse=True)
def _reset_style_backdrop_state():
    yield
    style.reset_theme_customization()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _force_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22621)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")


def _recording_dwm(monkeypatch: pytest.MonkeyPatch, extend_hr: int = 0,
                   attr_hr: int = 0) -> list[tuple]:
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


def _assert_full_chain(calls: list[tuple], kind_value: int) -> None:
    """The ordered chain, exactly as SYNTHESIS §2.3 specifies it:
    ExtendFrame → attr 20 (dark tint) → attr 38 (the material)."""
    kinds = [c[0] for c in calls]
    assert "extend" in kinds, f"no DwmExtendFrameIntoClientArea in {calls}"
    set_attrs = [c for c in calls if c[0] == "set_attr"]
    attrs = [c[1] for c in set_attrs]
    assert backdrop.DWMWA_USE_IMMERSIVE_DARK_MODE in attrs, "attr 20 never asserted"
    assert backdrop.DWMWA_SYSTEMBACKDROP_TYPE in attrs, "attr 38 never asserted"
    i_extend = kinds.index("extend")
    i_20 = next(i for i, c in enumerate(kinds)
                if c == "set_attr" and calls[i][1] == 20)
    i_38 = next(i for i, c in enumerate(kinds)
                if c == "set_attr" and calls[i][1] == 38)
    assert i_extend < i_20 < i_38, f"chain out of order: {calls}"
    assert ("set_attr", 38, kind_value) in calls


# =========================================================================== #
# 1. The ordered chain                                                        #
# =========================================================================== #

def test_reassert_applies_the_full_chain_in_order(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    try:
        assert backdrop.reassert_backdrop(win, "mica", dark=True) is True
        _assert_full_chain(calls, backdrop.DWMSBT_MAINWINDOW)
        assert backdrop.window_has_material(win) is True
    finally:
        win.deleteLater()


def test_reassert_never_raises_on_an_unsupported_host():
    """It runs from an event filter — a throw here would abort an unrelated Qt
    event delivery."""
    _app()
    win = QMainWindow()
    try:
        assert backdrop.reassert_backdrop(win, "mica", dark=True) is False
        assert backdrop.window_has_material(win) is False
    finally:
        win.deleteLater()


# =========================================================================== #
# 1b. THE ORDER FIX — the alpha surface must exist before the HWND does       #
#                                                                             #
# GL-island spike (scripts/spikes/gl_island_glass_spike.py, finding 2): Qt    #
# fixes a top-level's surface alpha ONCE, in QWidgetPrivate::create(), from   #
# WA_TranslucentBackground. Set the attribute after the native window exists  #
# and the surface never gains an alpha channel (alphaBufferSize == -1): DWM   #
# reports S_OK, the material attaches, and NOTHING composites — acrylic-on is #
# pixel-identical to acrylic-off. Worse, an rgba canvas painted onto a        #
# no-alpha surface blends against a zeroed backing store — which is BLACK.    #
# The offscreen platform reproduces the alpha semantics exactly, so this is   #
# provable headlessly.                                                        #
# =========================================================================== #

def test_the_alpha_surface_is_negotiated_before_the_native_window_exists(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        assert win.windowHandle() is None       # not realized yet
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)

        assert win.windowHandle().format().alphaBufferSize() >= 8, (
            "the window was realized without an alpha surface — the material "
            "cannot composite through it, no matter what DWM returns")
        assert backdrop.window_has_material(win) is True
        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
    finally:
        win.deleteLater()


def test_qt_really_loses_the_alpha_when_the_attribute_comes_late():
    """The mechanism itself, pinned against Qt (not against our code): this is
    the assumption the whole order fix rests on, so it gets its own test — if a
    future Qt changes it, this fails loudly instead of the glass dying quietly."""
    _app()
    early, late = QMainWindow(), QMainWindow()
    try:
        early.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        early.winId()
        assert early.windowHandle().format().alphaBufferSize() >= 8

        late.winId()                            # realize FIRST...
        late.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        assert late.windowHandle().format().alphaBufferSize() < 8, (
            "Qt now grants alpha after creation — the order fix may be "
            "relaxable, but verify on a real compositor before touching it")
    finally:
        early.deleteLater()
        late.deleteLater()


def test_material_on_a_surface_without_alpha_never_opens_the_alpha_hole(monkeypatch):
    """Kaya's BLACK, structurally impossible now. A window that was already
    realized when the material is switched on (the live 'pick acrylic in the
    theme editor' path) and whose alpha surface cannot be renegotiated must NOT
    paint the rgba canvas — that fill would blend against a zeroed backing store
    and render black. It reports no material and keeps the opaque token canvas."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        win.winId()                                     # realized WITHOUT alpha
        win.show()                                      # visible ⇒ no HWND yanking
        assert win.windowHandle().format().alphaBufferSize() < 8

        style.set_window_backdrop("acrylic")
        style.reassert_window_backdrop(win)

        assert backdrop.window_has_material(win) is False
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert not win.centralWidget().property(backdrop.CANVAS_GLASS_PROPERTY)
    finally:
        win.close()
        win.deleteLater()


def test_a_hidden_window_realized_too_early_gets_its_alpha_renegotiated(monkeypatch):
    """The heal: a window realized before the attribute, but NOT yet on screen,
    has its native handle re-created with the attribute set — no flicker, no live
    GL child to disturb — and comes up with real glass."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        win.winId()                                     # realized WITHOUT alpha
        assert win.windowHandle().format().alphaBufferSize() < 8

        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)

        assert win.windowHandle().format().alphaBufferSize() >= 8
        assert backdrop.window_has_material(win) is True
        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
    finally:
        win.deleteLater()


# =========================================================================== #
# 2. The event spine — every event that can lose the attributes               #
# =========================================================================== #

def test_winidchange_triggers_a_full_reassert(monkeypatch):
    """Fenrir K9, the headline: Qt re-created the native window, so every DWM
    attribute died with the old HWND. The ONE breadcrumb Qt gives is
    QEvent.WinIdChange — which had ZERO hits in TCT_app before this beat."""
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)
        calls.clear()

        app.sendEvent(win, QEvent(QEvent.Type.WinIdChange))

        _assert_full_chain(calls, backdrop.DWMSBT_MAINWINDOW)
    finally:
        win.deleteLater()


def test_native_handle_recreation_reasserts(monkeypatch):
    """The same thing driven by a REAL handle recreation rather than a
    synthetic event: toggling WA_NativeWindow / re-parenting makes Qt destroy
    and re-create the platform window, and Qt delivers WinIdChange for it."""
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    _app()
    holder = QMainWindow()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        style.set_window_backdrop("acrylic")
        style.reassert_window_backdrop(win)
        assert backdrop.window_has_material(win) is True
        calls.clear()

        # Re-parenting a top-level across window boundaries is Qt's classic
        # native-window-recreation trigger (Fenrir K9's mechanism).
        win.setParent(holder, Qt.WindowType.Window)
        win.winId()                      # force the new native handle now

        _assert_full_chain(calls, backdrop.DWMSBT_TRANSIENTWINDOW)
        assert backdrop.window_has_material(win) is True
    finally:
        win.setParent(None)
        win.deleteLater()
        holder.deleteLater()


def test_show_after_hide_reasserts(monkeypatch):
    """Symptom A's gesture: the theme editor is built lazily ONCE and re-shown,
    and nothing on the re-show path used to touch DWM again."""
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    _app()
    dlg = QDialog()
    try:
        style.set_window_backdrop("acrylic")
        style.reassert_window_backdrop(dlg)
        dlg.show()
        dlg.hide()
        calls.clear()

        dlg.show()

        _assert_full_chain(calls, backdrop.DWMSBT_TRANSIENTWINDOW)
    finally:
        dlg.deleteLater()


def test_window_state_change_reasserts(monkeypatch):
    """Minimize → restore: the other surface-recreation path (and the documented
    trigger of the stale white/black box)."""
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)
        calls.clear()

        app.sendEvent(win, QEvent(QEvent.Type.WindowStateChange))

        _assert_full_chain(calls, backdrop.DWMSBT_MAINWINDOW)
    finally:
        win.deleteLater()


@pytest.mark.parametrize("event_type", [
    QEvent.Type.ThemeChange,                # Windows WM_THEMECHANGED
    QEvent.Type.ApplicationPaletteChange,   # OS colour-scheme / app-mode flip
])
def test_os_theme_events_reassert_the_tint(monkeypatch, event_type):
    """Fenrir K5's OS half. Qt delivers Windows' WM_THEMECHANGED /
    WM_SETTINGCHANGE as these widget events, so attr 20 is re-asserted from the
    live theme WITHOUT this app putting a Python callback in the raw
    window-message hot path (which would tax the acquisition loop).

    The re-assert lands ONE event-loop turn later, never inline: these events are
    delivered while Qt walks every widget in the app, and doing DWM/palette work
    from inside that walk corrupts the list Qt is iterating (an access violation,
    reproduced in this suite). One turn later is also Fenrir rider 2 — it puts us
    after Qt's own palette heuristic in the race for attr 20."""
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)
        calls.clear()

        app.sendEvent(win, QEvent(event_type))
        assert calls == [], "the theme-event re-assert must NOT run inline"
        app.processEvents()             # ...one event-loop turn later

        _assert_full_chain(calls, backdrop.DWMSBT_MAINWINDOW)
    finally:
        win.deleteLater()


def test_theme_event_reassert_is_coalesced(monkeypatch):
    """A burst of theme events (a live theme-editor preview fires them by the
    dozen) must collapse into ONE deferred pass — not one queued app-wide
    fan-out per event.

    ``== 1``, not ``<= 1`` (Mary, G-B1 review, RISK 3): the old assertion passed
    VACUOUSLY at zero passes, so the suite structurally could not see the
    coalescing latch getting stuck True and suppressing the re-assert forever.
    Exactly one pass, no more and no fewer."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    passes: list[int] = []
    real = style._reassert_all_top_levels
    monkeypatch.setattr(style, "_reassert_all_top_levels",
                        lambda: (passes.append(1), real())[1])
    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)

        for _ in range(10):
            app.sendEvent(win, QEvent(QEvent.Type.ThemeChange))
        app.processEvents()

        assert len(passes) == 1
    finally:
        win.deleteLater()


def test_the_coalescing_latch_never_stays_stuck(monkeypatch):
    """RISK 3, the mechanism itself. ``_post_toggle_pending`` is set BEFORE the
    QTimer that clears it. If that timer never fires — process shutdown, or a
    caller/test that never drains the event loop — the flag latches True and
    EVERY future post-toggle re-assert is silently suppressed for the life of the
    process (and, in the suite, leaks into every later test). The module's
    back-to-a-known-state function must clear it."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)

        # Schedule a pass and DO NOT drain the event loop — the latch is armed.
        style._schedule_post_toggle_reassert()
        assert style._post_toggle_pending is True

        style.reset_theme_customization()
        assert style._post_toggle_pending is False

        # ...and the spine still works afterwards.
        passes: list[int] = []
        real = style._reassert_all_top_levels
        monkeypatch.setattr(style, "_reassert_all_top_levels",
                            lambda: (passes.append(1), real())[1])
        style.set_window_backdrop("acrylic")
        style._schedule_post_toggle_reassert()
        app.processEvents()
        assert len(passes) >= 1, (
            "the post-toggle re-assert was suppressed by a stale latch")
    finally:
        win.deleteLater()


def test_palette_change_is_deliberately_not_watched():
    """QEvent.PaletteChange is emitted by every setPalette and every stylesheet
    repolish IN THE APP — including the ones the re-assert itself performs. It
    is a feedback source with no unique signal (an OS colour-scheme change
    arrives as ThemeChange + ApplicationPaletteChange), and hooking it wedged
    the suite for exactly one run. Keep it out."""
    assert QEvent.Type.PaletteChange not in backdrop._BackdropGuard._WATCHED
    assert QEvent.Type.ThemeChange in backdrop._BackdropGuard._WATCHED
    assert QEvent.Type.ApplicationPaletteChange in backdrop._BackdropGuard._WATCHED


def test_reassert_is_not_reentrant(monkeypatch):
    """The re-assert touches attributes/palette/properties, which can deliver the
    very events the guard listens for (creating the native window fires
    WinIdChange right inside the chain). One pass per window — never a loop, and
    never a nested pass that could land the opacity pin before the material."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    depth = {"max": 0, "cur": 0}
    real = backdrop.reassert_backdrop

    def counting(window, kind, **kwargs):
        depth["cur"] += 1
        depth["max"] = max(depth["max"], depth["cur"])
        try:
            if depth["cur"] == 1:       # re-enter through a WATCHED event
                app.sendEvent(window, QEvent(QEvent.Type.WinIdChange))
            return real(window, kind, **kwargs)
        finally:
            depth["cur"] -= 1

    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)
        monkeypatch.setattr(backdrop, "reassert_backdrop", counting)

        app.sendEvent(win, QEvent(QEvent.Type.Show))

        assert depth["max"] == 1, "the guard re-entered its own re-assert"
    finally:
        win.deleteLater()


def test_spine_is_a_true_noop_in_the_shipped_default(monkeypatch):
    """Backdrop "none" (the shipped default): the spine must do NOTHING on a
    Show/WinIdChange — no DWM call, no repolish churn on every window show. The
    glass machinery costs exactly zero until Kaya opts in."""
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    try:
        assert style.get_window_backdrop() == "none"
        style.reassert_window_backdrop(win)         # installs the guard
        calls.clear()
        repolished: list = []
        monkeypatch.setattr(style, "repolish", lambda w: repolished.append(w))

        app.sendEvent(win, QEvent(QEvent.Type.Show))
        app.sendEvent(win, QEvent(QEvent.Type.WinIdChange))

        assert calls == []
        assert repolished == []
    finally:
        win.deleteLater()


def test_os_colour_scheme_flip_is_a_noop_in_the_shipped_default(monkeypatch):
    """NIT 7 — the OTHER path into the app-wide fan-out, which
    test_spine_is_a_true_noop_in_the_shipped_default did not cover.

    ``TCTMainWindow._on_os_color_scheme_changed`` (wired to Qt's
    ``colorSchemeChanged``) used to run the full fan-out unconditionally, handing
    every top-level a palette reset + repolish whenever Windows flipped its app
    mode — even with the shipped "none" backdrop, where there is no material tint
    to re-assert. The app's own dark/light choice is deliberately independent of
    the OS one, so in the default configuration this signal has nothing to do.
    "Zero cost until Kaya opts in" has to hold for every entry point, not just
    the guard's."""
    import tct_gui

    calls: list[str] = []
    monkeypatch.setattr(tct_gui, "apply_window_backdrop",
                        lambda app: calls.append("backdrop"))
    monkeypatch.setattr(tct_gui, "apply_window_opacity",
                        lambda app: calls.append("opacity"))
    _app()

    # Unbound call with a throwaway self: the handler reads no instance state —
    # that is the whole point of it being a pure "is a material active?" gate.
    assert style.get_window_backdrop() == "none"
    tct_gui.TCTMainWindow._on_os_color_scheme_changed(object())
    assert calls == []

    style.set_window_backdrop("mica")
    tct_gui.TCTMainWindow._on_os_color_scheme_changed(object())
    assert calls == ["backdrop", "opacity"], (
        "with a material active the OS app-mode flip MUST still re-assert the "
        "immersive-dark tint (Fenrir K5)")


def test_guard_is_installed_on_every_top_level_by_the_fan_out(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win, dlg = QMainWindow(), QDialog()
    try:
        style.set_window_backdrop("mica")
        style.apply_window_backdrop(app)

        assert win in backdrop._guarded_windows
        assert dlg in backdrop._guarded_windows
        # Idempotent: a second fan-out does not stack a second filter.
        assert backdrop.install_backdrop_guard(
            win, lambda w, r: None, lambda: None) is False
    finally:
        win.deleteLater()
        dlg.deleteLater()


# =========================================================================== #
# 3. THE UNDERLAY LAW — black must be structurally impossible                 #
# =========================================================================== #

def test_underlay_law_qss_canvas_is_opaque_unless_the_property_is_set():
    """The unqualified canvas rule NEVER carries alpha. The rgba fill exists
    only behind [glassCanvas="true"], which only a verified-material window
    carries — so a window whose DWM attributes died paints the opaque token
    pre-blend, not a hole."""
    for kind in ("mica", "acrylic"):
        style.set_window_backdrop(kind)
        p = style.palette("dark")
        qss = style.build_qss(p)

        assert f"QMainWindow, QDialog {{ background: {p['bg']}; }}" in qss
        assert f"QWidget#mainShell {{ background: {p['bg']}; }}" in qss
        glass = style._canvas_fill(p)
        assert glass.startswith("rgba(")
        assert 'QMainWindow[glassCanvas="true"]' in qss
        assert f'QWidget#mainShell[glassCanvas="true"] {{ background: {glass}; }}' in qss


def test_underlay_law_no_material_means_no_translucent_canvas(monkeypatch):
    """A window on a host that cannot attach the material never goes
    translucent and never claims the glass canvas."""
    _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)      # unsupported host: no-op

        assert backdrop.window_has_material(win) is False
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert not win.centralWidget().property(backdrop.CANVAS_GLASS_PROPERTY)
    finally:
        win.deleteLater()


def test_underlay_law_a_failed_attach_never_opens_an_alpha_hole(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch, attr_hr=-1)      # DWM rejects the material
    _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        style.set_window_backdrop("acrylic")
        style.reassert_window_backdrop(win)

        assert backdrop.window_has_material(win) is False
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
    finally:
        win.deleteLater()


def test_underlay_law_a_lost_material_falls_back_to_the_token_canvas(monkeypatch):
    """THE anti-black guarantee, and the exact shape of Kaya's symptom A: the
    material was live (translucent canvas + glassCanvas), then a re-assert on a
    recreated HWND fails. The window must drop its translucency and its glass
    property in the same breath, so the QSS paints the opaque token pre-blend —
    "looks like token glass", never a black hole."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)                  # first attach succeeds
    _app()
    win = QMainWindow()
    central = QWidget()
    win.setCentralWidget(central)
    try:
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
        assert central.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"

        # ...and now DWM starts refusing (the recreated-HWND / material-lost case)
        _recording_dwm(monkeypatch, extend_hr=-1)
        style.reassert_window_backdrop(win, reason="winidchange")

        assert backdrop.window_has_material(win) is False
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert not central.property(backdrop.CANVAS_GLASS_PROPERTY)
    finally:
        win.deleteLater()


def test_glass_canvas_property_is_set_on_window_and_central_widget(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()
    win = QMainWindow()
    central = QWidget()
    central.setObjectName("mainShell")
    win.setCentralWidget(central)
    try:
        style.set_window_backdrop("acrylic")
        style.reassert_window_backdrop(win)

        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
        assert central.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"

        style.set_window_backdrop("none")
        style.reassert_window_backdrop(win)

        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert not central.property(backdrop.CANVAS_GLASS_PROPERTY)
    finally:
        win.deleteLater()


# =========================================================================== #
# 4. Symptom B — the detached window path                                     #
# =========================================================================== #

def test_detached_window_makes_its_central_widget_translucent(monkeypatch):
    """Symptom B's root cause: _DetachedWindow used to apply the backdrop while
    centralWidget() was still None, so gui.backdrop._canvas_widgets() skipped
    the one child that actually paints a QMainWindow's client — an opaque child
    over a translucent top-level carries NO alpha to DWM, and the panel showed
    no glass. The content must now be in place before the chain runs."""
    from gui.detachable_tabs import _DetachedWindow

    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    _app()

    style.set_window_backdrop("mica")
    content = QLabel("panel")
    win = _DetachedWindow(content, "Monitor")
    try:
        assert win.centralWidget() is content
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert content.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert content.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
        _assert_full_chain(calls, backdrop.DWMSBT_MAINWINDOW)
    finally:
        win.deleteLater()


def test_detached_window_goes_through_the_same_single_chain(monkeypatch):
    """Every satellite window — theme editor, settings, device manager, torn-off
    panel — reaches DWM through style.reassert_window_backdrop and nothing
    else."""
    from gui.detachable_tabs import _DetachedWindow

    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    _app()

    seen: list[str] = []
    real = style.reassert_window_backdrop
    monkeypatch.setattr(style, "reassert_window_backdrop",
                        lambda w, **kw: (seen.append(type(w).__name__), real(w, **kw))[1])

    style.set_window_backdrop("mica")
    win = _DetachedWindow(QLabel("panel"), "Scope")
    try:
        assert "_DetachedWindow" in seen
        assert win in backdrop._guarded_windows
    finally:
        win.deleteLater()


def test_detached_window_reasserts_on_show(monkeypatch):
    from gui.detachable_tabs import _DetachedWindow

    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    _app()

    style.set_window_backdrop("acrylic")
    win = _DetachedWindow(QLabel("panel"), "Scope")
    try:
        calls.clear()
        win.show()
        _assert_full_chain(calls, backdrop.DWMSBT_TRANSIENTWINDOW)
    finally:
        win.close()
        win.deleteLater()


# =========================================================================== #
# 5. THE ACTIVATION CLAUSE (beat G-B2b) — an inactive window has no material   #
#                                                                             #
# Measured (82ddd2f): DWM does not composite a system backdrop on a window     #
# that is not active. It paints a fallback SOLID — mid-grey [84,84,84] —       #
# behind it instead. Reproduced on a live, never-minimized window simply by    #
# stealing focus (d_behind 63.99 -> 0.0) and reversed exactly by re-activating; #
# on the shipped QWidget cockpit AND on a QQuickWindow root.                    #
#                                                                             #
# So "inactive" is a LOSS PATH, and the underlay law never knew about it: an   #
# unfocused cockpit kept its rgba canvas and painted alpha over a flat         #
# #545454. The canvas now follows the focus.                                    #
#                                                                             #
# What these tests CANNOT prove: that DWM really re-composites after           #
# re-activation (offscreen has no compositor). That is the spike's             #
# measurement, and the pixels stay Kaya's eyeball.                             #
# =========================================================================== #

def _material_window(monkeypatch, kind: str = "mica") -> QMainWindow:
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    style.set_window_backdrop(kind)
    style.reassert_window_backdrop(win)
    assert backdrop.window_has_material(win) is True
    assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
    return win


def test_deactivation_closes_the_alpha_hole(monkeypatch):
    """THE fix. Focus goes elsewhere ⇒ no live material ⇒ no alpha hole; the QSS
    falls back to the opaque token pre-blend on the window AND on #mainShell (the
    child that actually paints a QMainWindow's client)."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = _material_window(monkeypatch)
    central = win.centralWidget()
    try:
        app.sendEvent(win, QEvent(QEvent.Type.WindowDeactivate))

        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
        assert not central.property(backdrop.CANVAS_GLASS_PROPERTY)
    finally:
        win.deleteLater()


def test_reactivation_reopens_it(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = _material_window(monkeypatch)
    central = win.centralWidget()
    try:
        app.sendEvent(win, QEvent(QEvent.Type.WindowDeactivate))
        app.sendEvent(win, QEvent(QEvent.Type.WindowActivate))

        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
        assert central.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
    finally:
        win.deleteLater()


def test_deactivation_keeps_the_surface_and_the_material(monkeypatch):
    """The two things a focus change must NOT disturb.

    * ``WA_TranslucentBackground`` stays — Qt fixes a window's surface alpha once,
      at HWND creation (GL-island spike, finding 2). Dropping the attribute on an
      alt-tab would be irreversible for a VISIBLE window: the material could never
      composite again.
    * ``window_has_material`` stays True — the DWM attributes never died, and
      style.py's WS_EX_LAYERED opacity pin keys off exactly this. If a focus change
      flipped it, an alt-tab would silently layer the window and kill the material
      for real."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = _material_window(monkeypatch, "acrylic")
    try:
        app.sendEvent(win, QEvent(QEvent.Type.WindowDeactivate))

        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
        assert backdrop.window_has_material(win) is True
    finally:
        win.deleteLater()


def test_a_focus_change_never_touches_dwm(monkeypatch):
    """It is a CANVAS event, not a re-assert. The attributes were never the
    problem — a full re-assert is measured to fix nothing here (0/3 in the spike)
    — and routing alt-tab into reassert_backdrop would buy a native chain plus a
    1-px relayout nudge of the whole dock tree on every focus change."""
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    app = _app()
    win = _material_window(monkeypatch)
    nudges: list = []
    monkeypatch.setattr(backdrop, "nudge_repaint", lambda w: nudges.append(w))
    try:
        calls.clear()

        app.sendEvent(win, QEvent(QEvent.Type.WindowDeactivate))
        app.sendEvent(win, QEvent(QEvent.Type.WindowActivate))

        assert calls == [], f"a focus change went to DWM: {calls}"
        assert nudges == [], "a focus change resized the cockpit"
    finally:
        win.deleteLater()


def test_activation_is_a_true_noop_in_the_shipped_default(monkeypatch):
    """Backdrop "none": no window is ever in _backdrop_applied_windows, so the
    whole clause is unreachable — zero property writes, zero repolish churn on
    every alt-tab. The glass machinery costs exactly nothing until Kaya opts in."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    try:
        assert style.get_window_backdrop() == "none"
        style.reassert_window_backdrop(win)          # installs the guard
        repolished: list = []
        monkeypatch.setattr(backdrop, "_repolish", lambda w: repolished.append(w))

        app.sendEvent(win, QEvent(QEvent.Type.WindowDeactivate))
        app.sendEvent(win, QEvent(QEvent.Type.WindowActivate))

        assert repolished == []
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY)
    finally:
        win.deleteLater()


def test_the_activation_clause_has_a_kill_switch(monkeypatch):
    """The cure repolishes the window + #mainShell on every focus change. If that
    flickers worse on a real display than the mid-grey it fixes, doing nothing is
    a legitimate outcome — and it must be ONE constant, not an archaeology
    expedition."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    monkeypatch.setattr(backdrop, "CANVAS_FOLLOWS_ACTIVATION", False)
    win = _material_window(monkeypatch)
    try:
        app.sendEvent(win, QEvent(QEvent.Type.WindowDeactivate))

        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"   # inert
    finally:
        win.deleteLater()


def test_the_activation_repair_can_be_scan_gated(monkeypatch):
    """The RUN-STATE GATE, on the seam gui/style.py must use (that file is another
    beat's lock — the exact patch is in this beat's handoff).

    Re-opening the canvas repolishes the window + #mainShell (a QSS pass on the
    GUI thread), and a cosmetic repaint must never preempt a run — the same law
    that gates nudge_repaint. But the gate is ASYMMETRIC, and deliberately so: it
    is the glass contract's own transition law (glass_env.plan_transition —
    "downgrades are NEVER queued, upgrades wait for scan-idle"). Closing the
    canvas is the DOWNGRADE (glass ⇒ opaque token) and applies mid-scan; reopening
    it is the UPGRADE and waits. Gating both directions would leave an alpha hole
    open over a material that is not there — precisely the defect being fixed."""
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    scanning = {"now": False}

    def gated(window, active: bool) -> None:
        if active and scanning["now"]:
            return
        backdrop.set_canvas_for_activation(window, active)

    try:
        # Install OUR guard first; style's own install is idempotent per window.
        assert backdrop.install_backdrop_guard(
            win, style._guard_reassert, style._schedule_post_toggle_reassert,
            gated) is True
        style.set_window_backdrop("mica")
        style.reassert_window_backdrop(win)
        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"

        scanning["now"] = True
        app.sendEvent(win, QEvent(QEvent.Type.WindowDeactivate))
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY), (
            "the DOWNGRADE was queued behind a scan — an alpha hole was left "
            "open over a material DWM is not painting")

        app.sendEvent(win, QEvent(QEvent.Type.WindowActivate))
        assert not win.property(backdrop.CANVAS_GLASS_PROPERTY), (
            "the cosmetic UPGRADE preempted a running scan")

        scanning["now"] = False
        app.sendEvent(win, QEvent(QEvent.Type.WindowActivate))
        assert win.property(backdrop.CANVAS_GLASS_PROPERTY) == "true"
    finally:
        win.deleteLater()


def test_a_broken_activation_callback_cannot_abort_qt_event_delivery(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    app = _app()
    win = QMainWindow()
    try:
        def boom(window, active):
            raise RuntimeError("activation handler exploded")

        backdrop.install_backdrop_guard(
            win, style._guard_reassert, style._schedule_post_toggle_reassert, boom)

        app.sendEvent(win, QEvent(QEvent.Type.WindowActivate))    # must not raise
    finally:
        win.deleteLater()


def test_the_activation_events_are_watched_and_are_not_reasserts():
    assert QEvent.Type.WindowActivate in backdrop._BackdropGuard._WATCHED
    assert QEvent.Type.WindowDeactivate in backdrop._BackdropGuard._WATCHED
    assert QEvent.Type.WindowActivate not in backdrop._BackdropGuard._IMMEDIATE
    assert QEvent.Type.WindowDeactivate not in backdrop._BackdropGuard._IMMEDIATE
    assert QEvent.Type.WindowActivate not in backdrop._BackdropGuard._DEFERRED
