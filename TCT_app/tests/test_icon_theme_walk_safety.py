"""The icon system must never run Python inside Qt's stylesheet repolish walk.

THE CRASH (cf18550, caught by the bench full-suite gate 2026-07-14). The icon
fix installed a shared QObject event filter on every token-bound button and
rebuilt the button's qtawesome pixmap on ``QEvent.StyleChange``. That event is
delivered from inside ``QStyleSheetStyle``'s repolish walk, which Qt drives over
a **raw pointer snapshot** of every widget in its style-rule cache. Three facts,
all measured on PySide6 6.11.1 while fixing this (not argued from docs):

1. Deleting a cached widget from inside a StyleChange handler segfaults the
   process on a later iteration of that walk (isolated repro: 40 buttons, delete
   20 from the filter -> SIGSEGV). The snapshot is not QPointer-guarded.
2. The filter ran Python — and a *qtawesome pixmap build*, an allocation storm —
   for every registered button, so CPython's automatic gc fired INSIDE the walk
   (observed on every toggle). A gc pass frees unreachable Python-OWNED QWidgets,
   and shiboken then deletes their C++ objects: that is (1), mid-walk.
   On the bench full suite this was an ACCESS VIOLATION (0xC0000005).
3. It was also quadratic misery: every registered button still alive ANYWHERE in
   the process was re-tinted on every toggle — 3690 rebuilds, 15.6 s per theme
   switch in a full-suite process, which blew the 60 s per-test timeout in
   ``test_apply_theme_lifetime.py`` (the file whose whole job is to prove
   ``apply_theme`` survives a half-destroyed widget pile).

Neither side of the filter was ever a corpse: ``self`` and ``obj`` were
shiboken-valid on all 19 000 dispatches. Qt guards those (the eventFilters list
is a QPointer list; a dead receiver is never dispatched to). The corpse was a
THIRD widget — one Qt itself held a raw pointer to.

THE FIX: token-bound icons are QIcons over ``_TokenIconEngine``, which resolves
the palette token AT PAINT. Nothing is baked, so nothing needs re-tinting, so no
icon code runs during a theme switch at all. These tests lock that in: the icon
system's exposure to the repolish walk must stay exactly zero.
"""
from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton

from gui import status_widgets
from gui.status_widgets import set_button_icon
from gui.style import apply_theme, palette


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _ink(button) -> str:
    """Hex of the first fully-opaque pixel the button's icon renders."""
    image = button.icon().pixmap(QSize(32, 32)).toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() >= 250:
                return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())
    raise AssertionError("icon rendered no opaque pixel")


# --------------------------------------------------------------------------- #
# 1. The structural guarantee: no event filter, no module-level watcher        #
# --------------------------------------------------------------------------- #
def test_a_token_icon_installs_no_event_filter_on_the_button():
    """The direct regression guard. An event filter on a widget is how Python
    got INTO the repolish walk; there must not be one."""
    pytest.importorskip("qtawesome")
    _app()

    installed: list[object] = []

    class RecordingButton(QPushButton):
        def installEventFilter(self, obj):  # noqa: N802 - Qt override
            installed.append(obj)
            super().installEventFilter(obj)

    btn = RecordingButton("Live")
    set_button_icon(btn, "mdi.play")

    assert installed == [], (
        "set_button_icon installed an event filter on the button — that is the "
        f"cf18550 crash vector (Python inside Qt's repolish walk): {installed}")


def test_the_module_keeps_no_global_watcher_object():
    """cf18550's ``_icon_watcher`` was a module-level, PARENTLESS QObject shared
    by every button in the process. Nothing of that shape may come back."""
    assert not hasattr(status_widgets, "_icon_watcher")
    assert not hasattr(status_widgets, "_IconThemeWatcher")


# --------------------------------------------------------------------------- #
# 2. The behavioural guarantee: a theme switch runs NO icon code               #
# --------------------------------------------------------------------------- #
def test_a_theme_switch_executes_no_icon_code_inside_the_repolish_walk(monkeypatch):
    """THE invariant. ``apply_theme`` -> ``QApplication.setStyleSheet`` -> Qt
    repolishes every cached widget from a raw-pointer snapshot. Our icon system
    must contribute exactly ZERO Python to that window: no pixmap rebuild, no
    qtawesome call, hence no allocation storm and no gc pass we caused.

    On cf18550 this counter came out at one rebuild per registered button."""
    pytest.importorskip("qtawesome")
    app = _app()
    apply_theme(app, "dark")

    buttons = []
    for i in range(40):
        b = QPushButton(f"b{i}")
        set_button_icon(b, "mdi.play")
        b.show()
        buttons.append(b)

    calls: list[tuple] = []
    real_build = status_widgets._build_qta_icon

    def counting_build(name, color):
        calls.append((name, color))
        return real_build(name, color)

    monkeypatch.setattr(status_widgets, "_build_qta_icon", counting_build)

    try:
        calls.clear()
        apply_theme(app, "light")
        assert calls == [], (
            f"{len(calls)} icon rebuild(s) ran INSIDE Qt's stylesheet repolish "
            "walk — that is the access-violation vector cf18550 shipped")

        calls.clear()
        apply_theme(app, "dark")
        assert calls == []
    finally:
        apply_theme(app, "dark")
        for b in buttons:
            b.deleteLater()


def test_the_icon_re_resolves_its_ink_at_paint_not_at_theme_switch():
    """The other half of the same coin: doing nothing on the toggle is only
    correct because the icon is not baked. The pixmap the button paints must
    come out in the ACTIVE theme's ink — with no event delivered, no event loop
    turn, and no re-tint pass anywhere."""
    pytest.importorskip("qtawesome")
    app = _app()

    apply_theme(app, "dark")
    btn = QPushButton("Live")
    set_button_icon(btn, "mdi.play")
    assert _ink(btn) == palette("dark")["text"].lower()

    apply_theme(app, "light")
    assert _ink(btn) == palette("light")["text"].lower()

    apply_theme(app, "dark")
    assert _ink(btn) == palette("dark")["text"].lower()


# --------------------------------------------------------------------------- #
# 3. The crash shape itself                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.timeout(60)
def test_theme_switch_over_a_half_destroyed_widget_pile():
    """The reproduction, as a test.

    The state that killed the bench: a pile of widgets whose destruction is
    half-done (closed + ``deleteLater``d, DeferredDelete NOT flushed) sitting in
    Qt's style-rule cache, plus hundreds of live token-bound buttons, and then a
    theme toggle. Under cf18550 the toggle re-tinted every one of those buttons
    from inside the walk; on the bench that access-violated, and locally it took
    ~15 s per toggle and hit the per-test timeout.

    It must now be uneventful — and the icons must still be right afterwards."""
    pytest.importorskip("qtawesome")
    app = _app()
    apply_theme(app, "dark")

    live = []
    for i in range(200):
        b = QPushButton(f"live{i}")
        set_button_icon(b, "mdi.play")
        b.show()
        live.append(b)

    # The corpse pile: real windows, closed and scheduled for deletion, with the
    # DeferredDelete queue deliberately NOT drained — exactly the state
    # tests/test_apply_theme_lifetime.py builds (and the state a full-suite
    # process is permanently in).
    doomed = []
    for i in range(8):
        win = QMainWindow()
        inner = QPushButton(f"doomed{i}", win)
        set_button_icon(inner, "mdi.play")
        win.setCentralWidget(inner)
        win.show()
        doomed.append(win)
    for win in doomed:
        win.close()
        win.deleteLater()

    for mode in ("light", "dark", "light"):
        apply_theme(app, mode)
        assert _ink(live[0]) == palette(mode)["text"].lower()

    # Now let the pile actually die, and toggle once more post-mortem.
    del doomed
    gc.collect()
    app.processEvents()
    apply_theme(app, "dark")
    assert _ink(live[-1]) == palette("dark")["text"].lower()

    for b in live:
        b.deleteLater()


def test_a_theme_switch_is_O1_in_the_number_of_live_icon_buttons(monkeypatch):
    """cf18550's toggle cost grew with every registered button still alive
    ANYWHERE in the process (3690 rebuilds, 15.6 s per switch in a full-suite
    process — that is what blew the 60 s timeout). The engine does no per-button
    work on a toggle at all, so the count must stay at zero when the number of
    live icon buttons goes up by an order of magnitude.

    Asserted on the rebuild COUNT, deliberately not on wall-clock: the wall time
    of ``apply_theme`` is dominated by Qt's own C++ repolish of every widget in
    the process (``gui.style.apply_theme``'s docstring measures ~9 s at ~13k
    widgets), which a test sharing the suite's QApplication cannot control. The
    count is exact, and it is the thing that actually regressed."""
    pytest.importorskip("qtawesome")
    app = _app()
    apply_theme(app, "dark")

    buttons = []
    for i in range(600):
        b = QPushButton(f"b{i}")
        set_button_icon(b, "mdi.play")
        b.show()
        buttons.append(b)

    builds: list[tuple] = []
    real_build = status_widgets._build_qta_icon
    monkeypatch.setattr(
        status_widgets, "_build_qta_icon",
        lambda name, color: (builds.append((name, color)), real_build(name, color))[1])

    try:
        for mode in ("light", "dark"):
            builds.clear()
            apply_theme(app, mode)
            assert builds == [], (
                f"{len(builds)} icon rebuild(s) during a theme switch with 600 "
                "live icon buttons — the toggle is O(buttons) again (cf18550: "
                "600 rebuilds here, 3690 in a full-suite process)")
    finally:
        apply_theme(app, "dark")
        for b in buttons:
            b.deleteLater()


def test_a_destroyed_button_takes_its_icon_engine_with_it():
    """The engine belongs to the QIcon, which belongs to the button: there is no
    registry, no global, and nothing to leave behind. Destroying the button and
    toggling the theme must be a non-event (cf18550's watcher, by contrast, was
    a parentless module-level QObject that outlived every widget it served)."""
    pytest.importorskip("qtawesome")
    app = _app()
    apply_theme(app, "dark")

    btn = QPushButton("doomed")
    set_button_icon(btn, "mdi.play")
    btn.show()

    btn.deleteLater()
    del btn
    gc.collect()
    app.processEvents()

    apply_theme(app, "light")
    apply_theme(app, "dark")
