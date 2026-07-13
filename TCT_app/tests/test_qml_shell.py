"""Headless tests for the opt-in QML-hybrid chrome shell (slice 1).

Covers, per the task brief plus Mary's slice-1 review fixes:
  * DEFAULT boot is unaffected — TCT_QML_SHELL unset builds the classic shell
    and constructs ZERO QQuickWidgets;
  * QML boot smoke — flag set builds the window, the chrome QQuickWidget loads
    error-free, the RHI was pinned to OpenGL, and show+close does not crash;
  * detach/redock of the scope tab with the QML shell enabled goes through the
    unchanged DetachableTabWidget engine;
  * the rail cluster (Devices/Settings/Log/Debug + the app-state readout) stays
    reachable now that the classic toolbar is hidden in QML mode;
  * fail-safe: a Shell.qml load error does NOT hide the classic toolbar/native
    tab bar — the app stays fully operable classic (review RISK #2);
  * production soft-reload (``_reload_config``) releases the OLD QQuickWidget's
    QML engine before building a new one, every cycle, through the REAL
    production path — not just the test-harness mitigation (review RISK #1);
  * the Theme singleton's token values match gui/style.py for both themes and
    its NOTIFY fires on a theme switch;
  * the tab-shelf adapter syncs current-index both directions;
  * the .qml chrome has ZERO inline hex (the no-inline-hex rule, extended to QML).

Offscreen + fully simulated. Software scene graph: these assert structure/wiring
and QObject state, not pixels (valid headless — see qml_hybrid_architecture.md §2).
"""
from __future__ import annotations

import gc
import os
import re
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtWidgets import QApplication


# --------------------------------------------------------------------------- #
# Harness                                                                       #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(seconds: float = 0.1) -> None:
    app = _app()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.005)


def _flush_deferred_deletes(seconds: float = 0.1) -> None:
    """Force pending ``deleteLater()`` calls to actually run, headless.

    Verified empirically (this task's investigation): a plain ``app.
    processEvents()`` pump loop that never enters ``QApplication.exec()`` does
    NOT reliably deliver ``QEvent.DeferredDelete`` in this offscreen setup —
    confirmed with a minimal repro (a bare ``QWidget.deleteLater()`` stayed
    ``shiboken6.isValid() == True`` after a 0.3 s pump). Under the real app's
    actual ``app.exec()`` main loop (``main.py``) this is a non-issue: a soft
    reload is only ever re-triggered by another user click, i.e. another
    real event-loop turn, during which Qt's normal idle processing reclaims
    the previous cycle's deferred deletions — verified separately with a
    ``QTimer``-driven swap-and-check under real ``exec()``. So production's
    ``TCTMainWindow._teardown_panels`` fix (plain ``old_central.deleteLater()``,
    no forcing) is correct and sufficient as-is.

    CAUTION — do not call this immediately after tearing down a FULL, live
    ``TCTMainWindow`` (with its other threads/panels still active) and before
    that window does more work: forcing ``DeferredDelete`` through in that
    specific combination reproduced a real access-violation crash during this
    investigation (a raw ``shiboken6.delete()`` did too — both "make it happen
    now" approaches were unsafe there; only the natural, unforced
    ``deleteLater()`` proved stable). This helper is safe as a narrow,
    isolated utility (e.g. confirming a lightweight standalone widget's
    deferred deletion actually landed) — it is deliberately NOT used by
    ``_finish_teardown`` or the repeated-reload regression test below.
    """
    app = _app()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _pump(seconds)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _pump(0.02)


def _make_window(monkeypatch, *, qml: bool):
    """Build a TCTMainWindow in classic or QML mode against the repo's
    fully-simulated default config (never connected — construction only)."""
    if qml:
        monkeypatch.setenv("TCT_QML_SHELL", "1")
        from gui.qml_shell import pin_opengl_rhi
        pin_opengl_rhi()   # main.py does this in QML mode before the window
    else:
        monkeypatch.delenv("TCT_QML_SHELL", raising=False)

    from tct_gui import TCTMainWindow

    # Keep persisted geometry / detached-tab state out of the headless build.
    monkeypatch.setattr(TCTMainWindow, "_restore_window_state", lambda self: None)
    win = TCTMainWindow(config_path="configs/devices.yaml")
    _pump()
    return win


def _release_qml_chrome(win) -> bool:
    """Explicitly clear the window's QML source and drop this file's Python
    references to chrome/bridge/adapter. Returns whether a chrome existed.

    A ``QQuickWidget`` owns its own ``QQmlEngine`` and scene-graph resources,
    and this file constructs several of them in one process (headless
    offscreen/software RHI). Relying only on ``deleteLater`` + a short
    event-loop pump left native teardown incomplete often enough to surface as
    an access violation **later**, in an unrelated test (the exact "widget
    corpse" class ``gui.style._apply_pyqtgraph`` already documents — proven by
    a full-suite run: green with this file excluded, crashing with it
    included). Explicitly clearing the QML source releases the root object
    graph and engine-owned resources synchronously — Qt's own recommended
    teardown for a QQuickWidget you are about to discard.
    """
    chrome = getattr(win, "_qml_chrome", None)
    if chrome is None:
        return False
    try:
        chrome.setSource(QUrl())
    except Exception:
        pass
    win._qml_chrome = None
    win._shell_bridge = None
    win._scope_vm = None
    return True


def _finish_teardown(win, had_chrome: bool) -> None:
    """Hide/deleteLater + a generous pump/GC pass (longer when a QQuickWidget
    was involved) so deferred native deletions land before the next window is
    constructed — see ``_release_qml_chrome`` for why this matters.

    Deliberately plain ``_pump()``, NOT ``_flush_deferred_deletes()``: this
    task's investigation found that forcing ``QEvent.DeferredDelete`` through
    immediately (via ``QCoreApplication.sendPostedEvents``) while the FULL
    app's other live threads/panels are still around is itself a crash
    vector — reproduced with the real ``TCTMainWindow``, not just the QML
    chrome in isolation. Plain ``deleteLater()`` + a generous plain pump is
    the configuration proven stable across the full test suite; save the
    forcing helper for narrow, isolated contexts only.
    """
    win.hide()
    win.deleteLater()
    _pump(0.2 if had_chrome else 0.1)
    gc.collect()
    _pump(0.05)


def _destroy(win) -> None:
    """Tear a (classic- or QML-mode) window down deterministically."""
    try:
        win._teardown_panels()
    finally:
        had_chrome = _release_qml_chrome(win)
        _finish_teardown(win, had_chrome)


# --------------------------------------------------------------------------- #
# 1. Default boot unaffected                                                    #
# --------------------------------------------------------------------------- #
def test_default_boot_builds_no_qquickwidget(monkeypatch):
    from PySide6.QtQuickWidgets import QQuickWidget

    app = _app()
    win = _make_window(monkeypatch, qml=False)
    try:
        assert win._qml_chrome is None
        assert win._shell_bridge is None
        assert win.findChildren(QQuickWidget) == []
        # Classic ribbon + toolbar are present; native tab bar and toolbar not
        # hidden (isVisible() is False until the top-level is shown, so assert
        # on isHidden() — the explicit-hide flag — instead).
        assert not win._tabs.tabBar().isHidden()
        assert not win._toolbar.isHidden()
        assert win._chip_bias_v.text().startswith("HV")
    finally:
        _destroy(win)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 2. QML boot smoke                                                             #
# --------------------------------------------------------------------------- #
def test_qml_boot_smoke(monkeypatch):
    from PySide6.QtQuickWidgets import QQuickWidget

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        from gui.qml_shell import rhi_pinned
        assert rhi_pinned() is True

        # Best-effort confirmation the pin actually took at the Qt level.
        from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
        assert QQuickWindow.graphicsApi() == QSGRendererInterface.GraphicsApi.OpenGL

        chrome = win._qml_chrome
        assert chrome is not None
        assert isinstance(chrome, QQuickWidget)
        assert chrome.status() != QQuickWidget.Status.Error, \
            [e.toString() for e in chrome.errors()]
        assert chrome.rootObject() is not None
        # Exactly one chrome island; native tab bar AND the classic toolbar
        # (Connect All / Disconnect All / Device Manager / Settings / Show Log
        # / Show Device Debug / state readout) are hidden in QML mode — the
        # rail is the only visible surface for those actions (no duplicate
        # Connect/Disconnect controls).
        assert len(win.findChildren(QQuickWidget)) == 1
        assert win._tabs.tabBar().isHidden()
        assert win._toolbar.isHidden()

        # show + close must not crash (closeEvent tears the window down once).
        win.show()
        _pump()
        win.close()
        _pump()
    finally:
        # closeEvent already ran _teardown_panels(); avoid a second teardown.
        had_chrome = _release_qml_chrome(win)
        _finish_teardown(win, had_chrome)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 3. Detach / redock of the scope tab with the QML shell enabled                #
# --------------------------------------------------------------------------- #
def test_qml_shell_scope_tab_detach_redock(monkeypatch):
    from gui.detachable_tabs import _DetachedWindow

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        tabs = win._tabs
        adapter = win._qml_chrome._tab_adapter
        idx = next(i for i in range(tabs.count())
                   if tabs.tabText(i) == "Oscilloscope")

        before = tabs.count()
        # Detach through the QML pill's affordance (adapter -> engine.detach).
        adapter.detach(idx)
        _pump()
        assert tabs.count() == before - 1
        assert "Oscilloscope" in tabs.detached_titles()
        assert "Oscilloscope" not in adapter.titles
        floating = [w for w in app.topLevelWidgets() if isinstance(w, _DetachedWindow)]
        assert len(floating) == 1

        # Redock by closing the floating window (the engine's contract).
        floating[0].close()
        _pump()
        assert tabs.count() == before
        assert "Oscilloscope" not in tabs.detached_titles()
        # The adapter's synced view reflects the redock.
        assert "Oscilloscope" in adapter.titles
    finally:
        _destroy(win)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 3b. Rail cluster — the toolbar's non-duplicated affordances stay reachable    #
#     (Device Manager / Settings / Show Log / Show Device Debug / app-state)    #
# --------------------------------------------------------------------------- #
def test_qml_rail_exposes_toolbar_affordances_and_state_readout(monkeypatch):
    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        bridge = win._shell_bridge
        # Dock isVisible() only reflects reality once the top-level is shown
        # (matches what _collect_shell_state's "log_visible"/"debug_visible"
        # reads) — show once up front so the assertions below are meaningful.
        win.show()
        _pump()

        # State readout mirrors the toolbar's app-state chip (self._lbl_state),
        # distinct from the "Scan" chip.
        assert bridge.appText == win._lbl_state.text()
        from controller.state_machine import AppState
        win._on_state_change(win._sm.state, AppState.CONNECTED)
        bridge.pull()
        assert bridge.appText == win._lbl_state.text()
        assert "CONNECTED" in bridge.appText

        # Device Manager: rail action opens the SAME window as the toolbar.
        assert win._device_manager_window is None
        bridge.openDeviceManager()
        _pump()
        assert win._device_manager_window is not None
        win._device_manager_window.close()
        _pump()

        # Settings: rail action opens the SAME settings window.
        assert win._settings_window is None
        bridge.openSettings()
        _pump()
        assert win._settings_window is not None
        win._settings_window.close()
        _pump()

        # Log dock: rail toggle flips the SAME checkable action/dock the
        # (hidden) toolbar and View menu drive — no parallel visibility state.
        assert not win._log_dock.isVisible()
        bridge.toggleLog()
        _pump()
        assert win._log_dock.isVisible()
        assert win._act_log.isChecked()
        bridge.pull()
        assert bridge.logVisible is True
        bridge.toggleLog()
        _pump()
        assert not win._log_dock.isVisible()

        # Device Debug dock: same contract.
        assert not win._device_debug_dock.isVisible()
        bridge.toggleDeviceDebug()
        _pump()
        assert win._device_debug_dock.isVisible()
        assert win._act_device_debug.isChecked()
        bridge.pull()
        assert bridge.debugVisible is True
        bridge.toggleDeviceDebug()
        _pump()
        assert not win._device_debug_dock.isVisible()
    finally:
        _destroy(win)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 3c. Fail-safe: a Shell.qml load error must NOT hide the classic surfaces      #
#     (Mary's review RISK #2 — never leave the user with a running-but-        #
#     unusable frame).                                                          #
# --------------------------------------------------------------------------- #
def test_qml_shell_fallback_on_bad_qml_source(monkeypatch, tmp_path):
    import gui.qml_shell as qml_shell_mod

    # Point the module at a directory with no Shell.qml -- the same load-error
    # path a corrupted/missing QML resource would hit in production.
    monkeypatch.setattr(qml_shell_mod, "_QML_DIR", tmp_path)

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        # build_qml_chrome returned (None, None): nothing was adopted.
        assert win._qml_chrome is None
        assert win._shell_bridge is None
        assert win._scope_vm is None

        # The classic toolbar and native tab bar were NEVER hidden -- the app
        # stays fully operable in its classic shell despite TCT_QML_SHELL=1.
        assert not win._toolbar.isHidden()
        assert not win._tabs.tabBar().isHidden()
        assert win._tabs.count() > 0
        assert win._chip_bias_v.text().startswith("HV")

        from PySide6.QtQuickWidgets import QQuickWidget
        assert win.findChildren(QQuickWidget) == []

        win.show()
        _pump()
        win.close()
        _pump()
    finally:
        had_chrome = _release_qml_chrome(win)
        _finish_teardown(win, had_chrome)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 3d. Regression pin for Mary's review RISK #1 — production soft-reload         #
#     (Settings save -> ``_reload_config`` -> ``_teardown_panels`` ->           #
#     ``_build_central``) must release the OLD QQuickWidget's QML engine       #
#     BEFORE the new one is built, every cycle, through the REAL production    #
#     path (not the test-only ``_release_qml_chrome`` harness).                #
#                                                                                #
# Investigation note (this task — see the full write-up in the task report):   #
# ``QMainWindow.setCentralWidget()`` does NOT delete the widget it replaces    #
# (confirmed empirically) — it only detaches it from the layout, leaving it   #
# (and any QQuickWidget under it) alive as a hidden orphan.                    #
# ``_teardown_panels`` now explicitly ``deleteLater()``s the outgoing central  #
# widget itself (not just the chrome's QML source) — see tct_gui.py. That     #
# plain, UNFORCED ``deleteLater()`` is the fix: two "make it happen now"       #
# alternatives were tried and REJECTED because they crashed the REAL, fully   #
# populated app (reproduced with ``TCTMainWindow`` via a raw script, NO        #
# pytest involved — ruling out any pytest-timeout interaction for THIS         #
# finding) — a raw ``shiboken6.delete()`` immediate native delete, and forcing #
# ``QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)`` through   #
# synchronously. Only the natural, deferred ``deleteLater()`` proved stable.   #
#                                                                                #
# Headless leak (context, NOT the cost driver anymore): ``processEvents()``    #
# pumping (no real ``app.exec()``) never actually flushes ``deleteLater()``,   #
# so each of THIS test's 4 back-to-back reload cycles leaves the previous      #
# cycle's whole panel tree alive and orphaned. That leak is a headless-only    #
# artifact — production reclaims it on the next event-loop turn (a soft reload #
# is only ever re-triggered by another user click) — and this test does NOT    #
# force deferred deletes (plain ``_pump()``, the proven-stable configuration)  #
# nor assert an exact live-``QQuickWidget`` count (it grows across cycles for  #
# that reason).                                                                #
#                                                                              #
# PHASE 0 root-cause fix (2026-07-13): the leak used to be FATAL to this test  #
# only because ``_build_central``'s trailing same-mode ``apply_theme()``       #
# re-assert called ``QApplication.setStyleSheet`` unconditionally, and Qt      #
# re-polishes the ENTIRE live widget tree on every such call even when handed  #
# the byte-identical stylesheet already installed — so per-cycle cost grew     #
# with the accumulating orphan tree (~9s/15s/17s/22s, ~64s total) and blew the #
# per-test budget on the bench. ``gui.style.apply_theme`` now skips the set    #
# when the QSS is unchanged (a genuine theme change still re-applies), making  #
# the reload path O(new-subtree) instead of O(cumulative-tree). Measured after #
# the fix: ~10s for all 4 cycles, and a 20x loop stays flat (~1.6-2.5s/cycle,  #
# apply_theme 0.00s throughout). The timeout below is a generous contention    #
# margin (CLAUDE.md test-lane note), no longer load-bearing for correctness.   #
#                                                                              #
# What IS asserted, every cycle, through the REAL production path: the reload  #
# completes without raising, a genuinely NEW chrome is built (not reused/      #
# stale), it loads error-free, and the classic toolbar/tab bar stay hidden.    #
# --------------------------------------------------------------------------- #
@pytest.mark.slow
@pytest.mark.timeout(90)
def test_qml_shell_survives_repeated_production_soft_reload(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtQuickWidgets import QQuickWidget

    # _reload_config asks for confirmation via a modal QMessageBox; answer Yes
    # every time so the headless test can drive the real production path.
    monkeypatch.setattr(QMessageBox, "question",
                         staticmethod(lambda *a, **k: QMessageBox.Yes))

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        cfg_path = win._config_path
        seen_chromes = []
        for cycle in range(4):
            prev_chrome = win._qml_chrome
            assert prev_chrome is not None, f"cycle {cycle}: no chrome before reload"
            seen_chromes.append(prev_chrome)

            win._reload_config(cfg_path)   # the REAL production path
            _pump(0.15)

            # A soft reload built a genuinely NEW chrome -- not a stale/
            # reused reference -- and it loaded without a QML error.
            new_chrome = win._qml_chrome
            assert new_chrome is not None, f"cycle {cycle}: no chrome after reload"
            assert new_chrome not in seen_chromes, f"cycle {cycle}: chrome not rebuilt"
            assert new_chrome.status() != QQuickWidget.Status.Error, \
                [e.toString() for e in new_chrome.errors()]
            assert win._toolbar.isHidden()
            assert win._tabs.tabBar().isHidden()

        # The window is still fully alive and responsive after 4 cycles.
        win.show()
        _pump()
        win.close()
        _pump()
    finally:
        had_chrome = _release_qml_chrome(win)
        _finish_teardown(win, had_chrome)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 3e. Rail compression (slice 2a) — no Flickable/horizontal scroll on the rail, #
#     content fits a >=1280px window in one view.                              #
# --------------------------------------------------------------------------- #
def test_qml_rail_has_no_flickable(monkeypatch):
    """The rail (top 48px strip: wordmark/Connect-Disconnect/device dots/stat
    chips/icon cluster/theme toggle) no longer wraps its content in a
    Flickable — every affordance must be reachable without a horizontal
    scroll. The pill tab shelf below the rail keeps its own Flickable (a
    genuinely scrollable tab list is out of this task's scope), so the
    assertion is scoped to "no Flickable is an ancestor of railRow", not
    "zero Flickable objects anywhere in the chrome"."""
    from PySide6.QtCore import QObject

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        root = win._qml_chrome.rootObject()
        assert root is not None

        rail_row = root.findChild(QObject, "railRow")
        assert rail_row is not None, "railRow object not found in Shell.qml"

        # No ancestor of railRow is a QQuickFlickable.
        node = rail_row.parent()
        while node is not None:
            assert node.metaObject().className() != "QQuickFlickable", (
                "railRow is still wrapped in a Flickable — the rail must "
                "fit without a horizontal scroll (slice 2a)"
            )
            node = node.parent()

        # Exactly one Flickable remains in the chrome: the pill tab shelf's.
        flickables = [
            o for o in root.findChildren(QObject)
            if o.metaObject().className() == "QQuickFlickable"
        ]
        assert len(flickables) == 1, (
            f"expected exactly 1 Flickable (the pill shelf), found {len(flickables)}"
        )
    finally:
        _destroy(win)
        app.processEvents()


def test_qml_rail_content_fits_1280_width(monkeypatch):
    """The rail's natural (implicit) content width must clear a 1280px window
    with room to spare — the actual compression check, independent of the
    Flickable-absence structural check above. Measured against the real
    devices.yaml (6 named devices) and the DISCONNECTED boot state, which is
    also the longest-text AppState member (the worst case for the Scan/State
    value chips: "Scan DISCONNECTED" / "State: DISCONNECTED")."""
    from PySide6.QtCore import QObject

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        root = win._qml_chrome.rootObject()
        rail_row = root.findChild(QObject, "railRow")
        assert rail_row is not None

        implicit_width = rail_row.property("implicitWidth")
        assert implicit_width is not None
        assert implicit_width <= 1280, (
            f"rail content needs {implicit_width}px — does not fit a 1280px "
            "window without scrolling"
        )
    finally:
        _destroy(win)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 3f. Single shared 1 Hz timer (coffee-retro item) — the bridge owns no timer;  #
#     the composition root's existing `_light_timer` drives its poll too.      #
# --------------------------------------------------------------------------- #
def test_shell_bridge_owns_no_timer(monkeypatch):
    from PySide6.QtCore import QTimer

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        bridge = win._shell_bridge
        assert not hasattr(bridge, "stop"), (
            "bridge.stop() should be gone with the timer it used to stop"
        )
        # No QTimer child owned by the bridge itself.
        assert bridge.findChildren(QTimer) == []
    finally:
        _destroy(win)
        app.processEvents()


def test_shell_bridge_pulled_by_shared_light_timer(monkeypatch):
    """A tick of the window's existing `_light_timer` (the SAME timer driving
    `_refresh_lights`/`_sync_app_state`) must refresh the bridge's cached
    QML-facing state too, with no separate bridge-owned timer involved."""
    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        from controller.state_machine import AppState

        bridge = win._shell_bridge
        assert bridge.appText == "State: DISCONNECTED"
        win._on_state_change(win._sm.state, AppState.CONNECTED)
        # bridge.appText is still stale (no pull yet) until the shared timer ticks.
        assert bridge.appText == "State: DISCONNECTED"

        win._light_timer.timeout.emit()   # simulate one shared-timer tick
        _pump()

        assert bridge.appText == "State: CONNECTED"
        assert bridge.appText == win._lbl_state.text()
    finally:
        _destroy(win)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 4. Theme singleton — tokens match style.py; NOTIFY fires on toggle            #
# --------------------------------------------------------------------------- #
def test_theme_singleton_tokens_match_style_for_both_modes():
    _app()
    from gui.qml_theme import TOKEN_MAP, Theme, set_theme_mode
    from gui.style import palette

    theme = Theme()
    try:
        for mode in ("light", "dark"):
            set_theme_mode(mode)
            pal = palette(mode)
            for qml_name, key in TOKEN_MAP.items():
                got = getattr(theme, qml_name).name()  # QColor -> "#rrggbb"
                expected = pal[key].lower()
                assert got.lower() == expected, (
                    f"{qml_name} ({mode}) = {got}, expected {expected}"
                )
    finally:
        set_theme_mode("light")


def test_theme_singleton_notify_fires_on_toggle():
    _app()
    from gui.qml_theme import Theme, set_theme_mode

    set_theme_mode("light")
    theme = Theme()
    fired = {"n": 0}
    theme.changed.connect(lambda: fired.__setitem__("n", fired["n"] + 1))
    try:
        set_theme_mode("dark")
        assert fired["n"] >= 1
        assert theme.dark is True
        set_theme_mode("light")
        assert fired["n"] >= 2
        assert theme.dark is False
    finally:
        set_theme_mode("light")


# --------------------------------------------------------------------------- #
# 5. Tab-shelf adapter — bidirectional current-index sync                       #
# --------------------------------------------------------------------------- #
def test_tab_shelf_adapter_syncs_both_directions():
    from gui.detachable_tabs import DetachableTabWidget
    from gui.qml_shell import _TabShelfAdapter
    from PySide6.QtWidgets import QLabel

    _app()
    tabs = DetachableTabWidget()
    for name in ("Alpha", "Beta", "Gamma"):
        tabs.addTab(QLabel(name), name)
    adapter = _TabShelfAdapter(tabs)
    try:
        assert adapter.titles == ["Alpha", "Beta", "Gamma"]
        assert adapter.count == 3

        # QML -> engine: a pill click sets the engine's current index.
        adapter.setCurrentIndex(2)
        assert tabs.currentIndex() == 2
        assert adapter.currentIndex == 2

        # engine -> QML: an external index change re-syncs the adapter view.
        tabs.setCurrentIndex(0)
        assert adapter.currentIndex == 0

        # Out-of-range clicks are ignored (no crash, no change).
        adapter.setCurrentIndex(99)
        assert tabs.currentIndex() == 0
    finally:
        tabs.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# 6. No inline hex in the QML chrome (rule extended to .qml)                     #
# --------------------------------------------------------------------------- #
_QML_DIR = Path(__file__).resolve().parent.parent / "gui" / "qml"
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _qml_files() -> list[Path]:
    return sorted(_QML_DIR.glob("*.qml"))


def test_qml_files_glob_is_non_empty():
    assert len(_qml_files()) >= 1


def test_no_inline_hex_in_qml():
    """Every colour in the QML chrome must bind the Theme singleton — no raw
    #rrggbb literals (the gui/style.py single-source rule, extended to QML per
    qml_hybrid_architecture.md §3). Comments are stripped first so a hex value
    mentioned only in a doc comment does not trip the guard."""
    failures: dict[str, list[str]] = {}
    for path in _qml_files():
        src = path.read_text(encoding="utf-8")
        src = _BLOCK_COMMENT.sub("", src)
        src = _LINE_COMMENT.sub("", src)
        hits = _HEX_RE.findall(src)
        if hits:
            failures[path.name] = hits
    assert failures == {}, (
        "inline hex literal(s) in QML — bind Theme.* instead: " f"{failures}"
    )


# --------------------------------------------------------------------------- #
# 7. D2 — readiness-ladder caption (tct_gui._readiness_caption)                 #
# --------------------------------------------------------------------------- #
def test_readiness_caption_ladder_progression():
    """Pure-function unit test for the rail "State" chip's tooltip ladder
    (cockpit_design_system.md §5/§6 — "say WHY Start is disabled")."""
    from tct_gui import _readiness_caption

    assert _readiness_caption("DISCONNECTED") == "connected · homed · configured · ready"
    assert _readiness_caption("CONNECTED") == "connected ✓ · homed · configured · ready"
    assert _readiness_caption("HOMED") == "connected ✓ · homed ✓ · configured · ready"
    assert _readiness_caption("CONFIGURED") == "connected ✓ · homed ✓ · configured ✓ · ready"
    assert _readiness_caption("READY") == "connected ✓ · homed ✓ · configured ✓ · ready ✓"
    # Not the relevant question once a run is live or just finished.
    for st in ("RUNNING", "PAUSED", "FINISHED", "ABORTED", "ERROR"):
        assert _readiness_caption(st) == "", st


def test_qml_rail_readiness_reaches_bridge_and_tracks_state(monkeypatch):
    """End-to-end: sm.state -> _collect_shell_state()["app_readiness"] ->
    _ShellBridge.appReadiness, riding the SAME shared 1 Hz light-timer tick
    the rest of the rail uses (no separate poll)."""
    from controller.state_machine import AppState
    from tct_gui import _readiness_caption

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        bridge = win._shell_bridge
        assert bridge.appReadiness == _readiness_caption("DISCONNECTED")

        # win._sm.transition (not the _on_state_change UI callback alone) —
        # _collect_shell_state reads the real machine state, not the label
        # text _on_state_change sets; transition() fires that callback too.
        win._sm.transition(AppState.CONNECTED)
        # Stale until the shared timer ticks (matches the appText contract).
        assert bridge.appReadiness == _readiness_caption("DISCONNECTED")
        win._light_timer.timeout.emit()
        _pump()
        assert bridge.appReadiness == _readiness_caption("CONNECTED")
        assert bridge.appReadiness == "connected ✓ · homed · configured · ready"

        win._sm.transition(AppState.HOMED)
        win._sm.transition(AppState.CONFIGURED)
        win._sm.transition(AppState.READY)
        win._sm.transition(AppState.RUNNING)
        win._light_timer.timeout.emit()
        _pump()
        assert bridge.appReadiness == ""  # not the relevant question mid-run
    finally:
        _destroy(win)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 8. D2 — device-dot fault state (attempted-and-failed connect)                 #
# --------------------------------------------------------------------------- #
def test_collect_shell_state_marks_failed_connect_as_fault(monkeypatch):
    """A device present in the last connect_all() failures (and still
    disconnected) reports the rail's 4th dot state, "fault" — distinct from a
    device that was simply never attempted ("off")."""
    app = _app()
    win = _make_window(monkeypatch, qml=False)
    try:
        assert win._connect_faults == {}
        state = win._collect_shell_state()
        assert all(s != "fault" for _name, s in state["devices"])

        win._connect_faults = {"motor": "COM3: timeout"}
        state = win._collect_shell_state()
        by_name = dict(state["devices"])
        assert by_name["Motor Stage"] == "fault"
        # Every other never-attempted device stays plain "off", not "fault".
        assert by_name["Oscilloscope"] == "off"

        # An explicit disconnect clears the fault cache (tct_gui._on_disconnect_done).
        win._on_disconnect_done(None, "")
        assert win._connect_faults == {}
    finally:
        _destroy(win)
        app.processEvents()


# --------------------------------------------------------------------------- #
# 9. D2 — sim ribbon visibility (Shell.qml, law 6)                              #
# --------------------------------------------------------------------------- #
def test_sim_ribbon_hidden_when_no_device_simulated(monkeypatch):
    """Fresh boot: hardware safety rule 1 (no auto-connect on construction)
    means every device is plain "disconnected" — zero devices report "sim",
    so the ribbon must be hidden (not just visually empty)."""
    from PySide6.QtCore import QObject

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        assert win._shell_bridge.hasSimulated is False
        root = win._qml_chrome.rootObject()
        ribbon = root.findChild(QObject, "simRibbon")
        assert ribbon is not None
        assert ribbon.property("visible") is False
    finally:
        _destroy(win)
        app.processEvents()


def test_sim_ribbon_visible_after_connecting_simulated_devices(monkeypatch):
    """The repo's default ``configs/devices.yaml`` is fully simulated — after
    a (synchronous, in-test) ``connect_all()`` every named device reports
    "sim", so the ribbon must show and name them, and the chrome must grow to
    make room for it (no clipping, no dead gap)."""
    from PySide6.QtCore import QObject

    app = _app()
    win = _make_window(monkeypatch, qml=True)
    try:
        base_height = win._qml_chrome.height()

        win._devices.connect_all()   # synchronous — the suite's own pattern
        win._light_timer.timeout.emit()
        _pump()

        bridge = win._shell_bridge
        assert bridge.hasSimulated is True
        assert all(state == "sim" for _name, state in bridge.devicesModel)

        root = win._qml_chrome.rootObject()
        ribbon = root.findChild(QObject, "simRibbon")
        assert ribbon.property("visible") is True
        text_label = root.findChild(QObject, "simRibbonText")
        assert "SIMULATION" in text_label.property("text")
        assert f"of {len(bridge.devicesModel)} devices simulated" in text_label.property("text")

        # The chrome grew to make room for the now-visible ribbon.
        assert win._qml_chrome.height() > base_height

        win._devices.disconnect_all()
    finally:
        _destroy(win)
        app.processEvents()
