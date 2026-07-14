"""Headless tests for ``scripts/qml_preview.py`` — the QML live-preview harness.

Scope, deliberately narrow (this is a DEV TOOL, not shipped UI): that the harness
imports, builds its real engine offscreen, loads a trivial .qml, hot-reloads on a
simulated file change, SURVIVES a QML syntax error and recovers on the next good
save, feeds the tier through the real ``gui/glass_env.py`` contract, and leaves no
window behind.

NOT tested here (manual-run-only by design, exactly like
``tests/test_capture_onscreen_guard.py`` treats the capture tool): the DWM material
itself, the decoy, and any pixel. Offscreen has no compositor —
``gui.backdrop.is_backdrop_supported()`` is False, so the whole glass chain is a
verified no-op and only its DECISION (the tier) is meaningful here.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from gui import glass_env, qml_theme, style
from gui.glass_env import GlassTier
from scripts import qml_preview

_GOOD = """
import QtQuick
import Tct

Item {
    objectName: "previewRoot"
    // marker the test flips across a reload
    property int rev: %d
    Rectangle { anchors.fill: parent; color: Theme.canvas }
}
"""

_BROKEN = """
import QtQuick

Item {
    this is not qml (
}
"""


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(seconds: float = 0.15) -> None:
    app = _app()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture()
def qml_file(tmp_path):
    p = tmp_path / "Preview.qml"
    p.write_text(_GOOD % 1, encoding="utf-8")
    return p


@pytest.fixture()
def win(qml_file):
    """The REAL harness — same theme feed, same glass chain, same watcher."""
    _app()
    w = qml_preview.build_preview(qml_file, mode="dark", backdrop_kind="none",
                                  tier=None, decoy=False)
    _pump()
    yield w
    w.shutdown()
    w.close()
    _pump(0.05)


# --------------------------------------------------------------------------- #
# It is a dev tool: no app, no hardware                                        #
# --------------------------------------------------------------------------- #
def test_harness_never_reaches_into_the_app_or_the_hardware():
    """Source guard: the preview may import gui/ (that is the POINT — the real
    tokens, the real glass chain) but never the composition root, the controller
    or a device. A dev tool that can start a scan is not a dev tool."""
    src = (qml_preview.Path(qml_preview.__file__)).read_text(encoding="utf-8")
    for forbidden in ("import controller", "from controller",
                      "import devices", "from devices",
                      "import tct_gui", "from tct_gui",
                      "import main", "from main"):
        assert forbidden not in src, f"qml_preview imports the app: {forbidden!r}"


# --------------------------------------------------------------------------- #
# Boot + the real token path                                                   #
# --------------------------------------------------------------------------- #
def test_builds_and_loads_a_trivial_qml_error_free(win):
    from PySide6.QtQuickWidgets import QQuickWidget

    assert win._quick.status() == QQuickWidget.Status.Ready, [
        e.toString() for e in win._quick.errors()]
    root = win._quick.rootObject()
    assert root is not None
    assert root.property("rev") == 1
    assert win._errors.isHidden()


def test_theme_is_the_real_token_singleton_not_a_copy(win):
    """The .qml binds ``Theme.canvas``; that value must BE gui.style's token, and
    it must follow a live theme switch. If these could disagree, the tool lies."""
    root = win._quick.rootObject()
    rect = root.children()[0]

    assert qml_theme.current_mode() == "dark"
    assert rect.property("color").name().lower() == \
        style.palette("dark")["canvas"].lower()

    win.toggle_theme()
    _pump()
    assert qml_theme.current_mode() == "light"
    assert rect.property("color").name().lower() == \
        style.palette("light")["canvas"].lower()


# --------------------------------------------------------------------------- #
# Hot reload                                                                   #
# --------------------------------------------------------------------------- #
def test_a_file_change_hot_reloads_the_scene(win, qml_file):
    """A simulated save (write + the watcher's signal) must swap the live scene —
    through the debounce timer and the component-cache clear, i.e. the real path."""
    old_root = win._quick.rootObject()
    assert old_root.property("rev") == 1

    qml_file.write_text(_GOOD % 2, encoding="utf-8")
    win._on_fs_event(str(qml_file))          # what QFileSystemWatcher emits
    _pump(0.4)                               # let the debounce QTimer fire

    new_root = win._quick.rootObject()
    assert new_root is not None
    assert new_root.property("rev") == 2, "the component cache was not cleared"
    assert win._errors.isHidden()


def test_the_watch_is_re_armed_after_every_reload(win, qml_file):
    """Editors save atomically (write temp → rename over the target), which drops
    the watched inode. Both the file AND its directory stay watched, every cycle —
    or the SECOND save silently stops reloading."""
    win._watcher.removePath(str(qml_file))   # simulate the atomic-save inode drop
    qml_file.write_text(_GOOD % 3, encoding="utf-8")
    win._on_fs_event(str(qml_file.parent))   # only the DIRECTORY signal survives
    _pump(0.4)

    assert win._quick.rootObject().property("rev") == 3
    assert str(qml_file) in win._watcher.files()
    assert str(qml_file.parent) in win._watcher.directories()


# --------------------------------------------------------------------------- #
# Error recovery — a tool that dies on a typo will not be used                 #
# --------------------------------------------------------------------------- #
def test_a_syntax_error_shows_up_and_the_next_good_save_recovers(win, qml_file):
    from PySide6.QtQuickWidgets import QQuickWidget

    qml_file.write_text(_BROKEN, encoding="utf-8")
    win._on_fs_event(str(qml_file))
    _pump(0.4)

    assert win._quick.status() == QQuickWidget.Status.Error
    assert win._errors.isVisible() or not win._errors.isHidden()
    assert win._errors.toPlainText().strip(), "the error text must be shown, not swallowed"
    # still watching — this is the half that makes the loop usable
    assert str(qml_file) in win._watcher.files()

    qml_file.write_text(_GOOD % 4, encoding="utf-8")
    win._on_fs_event(str(qml_file))
    _pump(0.4)

    assert win._quick.status() == QQuickWidget.Status.Ready
    assert win._quick.rootObject().property("rev") == 4
    assert win._errors.isHidden()


def test_a_deleted_file_does_not_kill_the_harness(win, qml_file):
    qml_file.unlink()
    win._on_fs_event(str(qml_file.parent))
    _pump(0.4)

    assert win._errors.toPlainText()          # says so, keeps running
    assert str(qml_file.parent) in win._watcher.directories()


# --------------------------------------------------------------------------- #
# The tier goes through the REAL contract                                      #
# --------------------------------------------------------------------------- #
def test_the_tier_is_decided_by_glass_env_not_by_the_harness(win):
    """The preview is the contract's first consumer: the tier it shows must be
    exactly ``glass_env.decide_tier`` of the environment it declares. Offscreen,
    that is the SAFE_FLOOR (TOKEN) — no compositor, no OS material."""
    env = win._environment()
    assert env.qt_platform == "offscreen"
    assert env.shell == glass_env.SHELL_CLASSIC
    assert env.scan_active is False           # a dev tool never runs an acquisition
    assert win._tier == glass_env.decide_tier(env) == glass_env.SAFE_FLOOR


def test_an_override_can_only_force_the_tier_down_and_it_gates_the_material(win):
    win._tier_override = "flat"
    win._apply_glass(reason="test")
    assert win._tier == GlassTier.FLAT
    assert win._bridge.flat is True

    # An override is a CEILING: asking for "window" offscreen cannot conjure one.
    win._tier_override = "window"
    win._backdrop_kind = "acrylic"
    win._apply_glass(reason="test")
    assert win._tier == glass_env.SAFE_FLOOR
    assert style.get_window_backdrop() == "none", \
        "below WINDOW there is no material to attach, whatever was requested"
    assert win._bridge.glass is False


# --------------------------------------------------------------------------- #
# No leaked window                                                             #
# --------------------------------------------------------------------------- #
def test_shutdown_releases_the_qml_engine_and_leaves_no_window(qml_file):
    app = _app()
    w = qml_preview.build_preview(qml_file, mode="light", backdrop_kind="none",
                                  tier=None, decoy=False)
    _pump()
    assert w in app.topLevelWidgets()

    w.shutdown()                              # explicit engine release (QQuickWidget)
    assert w._quick.rootObject() is None
    assert not w._watcher.files() and not w._watcher.directories()

    w.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _pump(0.1)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _pump(0.05)

    assert not any(type(t).__name__ == "QmlPreviewWindow"
                   for t in app.topLevelWidgets()), "the preview window leaked"
