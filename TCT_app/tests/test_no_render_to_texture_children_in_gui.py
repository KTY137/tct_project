"""No render-to-texture (RTT) WIDGET child inside a material-capable top-level.

THE RULE THIS PINS (and it is a design rule, not a ban on OpenGL):

    OpenGL/Quick content is welcome in this cockpit — it just has to live in
    its **own native window**.  What is forbidden is an RTT *widget* child
    (``QOpenGLWidget``, ``QQuickWidget``, ``QVideoWidget``, pyqtgraph's
    ``GLViewWidget``) parented into a QWidget top-level that we want to carry
    DWM window material (glass).

WHY (docs/design/glass_council/SYNTHESIS.md §2 — Thor's **path D**):
an RTT widget is composed into its parent's backing store by
``QWidgetRepaintManager::composeAndFlush``.  The whole top-level then flips
from the raster/DWM-composited path to the GPU-composed one, its per-pixel
alpha is poisoned, and DWM cannot show a backdrop material for that HWND — for
the ENTIRE window, for as long as that child lives, no matter how small or how
hidden it is (the old Motor 3D page was a hidden stack page and still armed the
flip on first show).  SYNTHESIS §0: "What money cannot buy … per-pixel DWM alpha
through a QWidget top-level that hosts any render-to-texture child."

THE SANCTIONED PATTERN (Kaya, 2026-07-13: "wäre trotzdem toll wenn das parallel
zu OpenGL Prozessen funken würde, dann wäre es robust"):
host GL in its **own native window** — a ``QWindow``-based surface
(``QOpenGLWindow`` / ``QQuickView`` / ``QQuickWindow``) embedded via
``QWidget.createWindowContainer``, or simply a separate top-level.  It gets its
own HWND, DWM composites it independently, and it **cannot poison the parent's
alpha**.  That is exactly how the GlassShell's fast-DAQ / GL islands are
designed: opaque and topmost *by mechanism*.  So: glass and OpenGL coexist —
via native windows, never via RTT widget children.

    forbidden:  QOpenGLWidget/GLViewWidget/QQuickWidget as a child widget
    allowed:    QOpenGLWindow/QQuickView + createWindowContainer, or a
                separate top-level window

THE ONE KNOWN EXCEPTION: ``gui/qml_shell.py``'s chrome ``QQuickWidget``
(opt-in ``TCT_QML_SHELL=1``; classic boot constructs zero of them — pinned in
tests/test_qml_shell.py).  It is the remaining RTT child in the tree and is
tracked by the GlassShell program (SYNTHESIS §2.2.2: the real ``QQuickWindow``
shell replaces it).  It is allow-listed BY FILE AND BY NAME below — any *new*
RTT child, anywhere in ``gui/``, fails this test.

History: ``gui/stage_view.py::StageView3D`` (a ``pyqtgraph.opengl.GLViewWidget``)
was deleted 2026-07-13 on Kaya's call ("die 3D view brauchen wir auch nicht"),
which is what makes the CLASSIC main window RTT-free end to end and the Motor
panel material-capable when detached.  This test is the ratchet that keeps it
that way.

Static half = AST scan (catches the import/instantiation even if the widget is
never shown).  Dynamic half = build the real panels/window offscreen and walk
the child tree.  Both are needed: the AST cannot see a widget class imported
from a third-party module under an alias chain, the tree walk cannot see code
that is not exercised.
"""
from __future__ import annotations

import ast
import gc
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

_APP_ROOT = Path(__file__).resolve().parent.parent
_GUI_DIR = _APP_ROOT / "gui"


# --------------------------------------------------------------------------- #
# What counts as a render-to-texture WIDGET child                              #
# --------------------------------------------------------------------------- #

# QWidget subclasses that render through an FBO/texture and therefore flip the
# hosting top-level onto the composeAndFlush path (path D).
_RTT_WIDGET_CLASSES = {
    "QOpenGLWidget",     # the base case (Qt)
    "QQuickWidget",      # Quick scene rendered to an FBO, then blitted
    "QVideoWidget",      # may be backed by a GL/native surface
    "GLViewWidget",      # pyqtgraph.opengl — IS a QOpenGLWidget
}

# Importing any of these into gui/ means an RTT widget is (about to be) built.
_RTT_MODULES = {
    "pyqtgraph.opengl",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimediaWidgets",
    "OpenGL",            # PyOpenGL — only pyqtgraph.opengl ever wanted it here
}

# QWindow-based GL surfaces: NOT RTT children.  Legal — but only when hosted in
# their own native window (createWindowContainer), which the design-rule test
# below enforces.
_NATIVE_GL_WINDOW_CLASSES = {
    "QOpenGLWindow",
    "QQuickView",
    "QQuickWindow",
}

# file name -> the RTT names it may use.  EXACTLY one entry, and it is tracked:
# the GlassShell program replaces this QQuickWidget with a real QQuickWindow
# shell (SYNTHESIS §2.2.2).  Do not add rows here without that conversation.
_ALLOWED: dict[str, set[str]] = {
    "qml_shell.py": {"QQuickWidget", "PySide6.QtQuickWidgets"},
}


def _scanned_files() -> list[Path]:
    """Every GUI-layer source file plus the composition root and entry point —
    i.e. everything that could parent a widget into the main top-level."""
    files = sorted(
        p for p in _GUI_DIR.rglob("*.py") if "__pycache__" not in p.parts
    )
    files.append(_APP_ROOT / "tct_gui.py")
    files.append(_APP_ROOT / "main.py")
    return files


def _called_or_subclassed_names(tree: ast.AST) -> set[str]:
    """Class names this module *instantiates* or *subclasses* (bare ``Name``
    or the trailing attribute of ``pkg.Name``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name):
                    names.add(base.id)
                elif isinstance(base, ast.Attribute):
                    names.add(base.attr)
    return names


def _imported_modules(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:
                mods.add(node.module)
    return mods


def _rtt_hits() -> dict[str, set[str]]:
    """{file name: {offending RTT class/module names}} across the GUI layer."""
    hits: dict[str, set[str]] = {}
    for path in _scanned_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found = (_called_or_subclassed_names(tree) & _RTT_WIDGET_CLASSES) | (
            _imported_modules(tree) & _RTT_MODULES
        )
        found -= _ALLOWED.get(path.name, set())
        if found:
            hits[path.name] = found
    return hits


# --------------------------------------------------------------------------- #
# Static half                                                                  #
# --------------------------------------------------------------------------- #

def test_no_render_to_texture_children_in_gui():
    """THE ratchet: no new RTT widget child anywhere under gui/ (+ the
    composition root).  One RTT child kills DWM window material for the whole
    top-level that hosts it (path D) — see this file's docstring.

    If you need OpenGL: host it in its own native window
    (``QWindow`` + ``createWindowContainer``, or a separate top-level).  That is
    allowed by this test *by construction* — QWindow-based GL classes are not in
    the forbidden set — and it is how the GlassShell GL/fast-DAQ islands work."""
    hits = _rtt_hits()
    assert hits == {}, (
        "render-to-texture WIDGET child introduced in the GUI layer: "
        f"{hits}\n"
        "This poisons the hosting top-level's per-pixel alpha and kills DWM "
        "window material for the ENTIRE window (glass_council/SYNTHESIS.md §2, "
        "path D) — even if the widget is hidden on an unshown stack page.\n"
        "Fix: host the GL content in its OWN NATIVE WINDOW (QOpenGLWindow / "
        "QQuickView + QWidget.createWindowContainer, or a separate top-level). "
        "DWM then composites it separately and the parent keeps its material."
    )


def test_scan_actually_sees_the_gui_layer():
    """Guard on the guard: if the glob ever breaks, the ratchet above would
    pass vacuously."""
    files = {p.name for p in _scanned_files()}
    assert "stage_view.py" in files
    assert "motor_panel.py" in files
    assert "qml_shell.py" in files
    assert "tct_gui.py" in files
    assert len(files) > 20


def test_the_only_allowlisted_rtt_child_is_the_qml_chrome():
    """The exception is exactly one file and exactly one class — spelled out so
    that widening it is a visible, reviewed edit, not a silent one.  The QML
    chrome QQuickWidget is the KNOWN remaining RTT child; it is opt-in
    (TCT_QML_SHELL=1, classic boot builds zero — tests/test_qml_shell.py) and
    the GlassShell program retires it by moving the chrome into a real
    QQuickWindow shell (SYNTHESIS §2.2.2)."""
    assert set(_ALLOWED) == {"qml_shell.py"}
    assert _ALLOWED["qml_shell.py"] == {"QQuickWidget", "PySide6.QtQuickWidgets"}

    # ...and it is really still there (the allowance is load-bearing, not stale).
    tree = ast.parse((_GUI_DIR / "qml_shell.py").read_text(encoding="utf-8"))
    assert "QQuickWidget" in _called_or_subclassed_names(tree)


def test_native_window_gl_must_be_hosted_in_a_window_container():
    """The sanctioned-pattern half of the rule: a QWindow-based GL surface is
    allowed *because* it lives in its own native window — so any gui/ file that
    builds one must also embed it via ``createWindowContainer`` (or hand it out
    as a separate top-level).  Instantiating a QQuickView/QOpenGLWindow and then
    NOT giving it its own window would be back-door path D.

    Vacuous today (we host no GL at all after the 3D stage view was deleted) —
    deliberately: it is the forward guard for the first GL island the GlassShell
    program adds, so the pattern is enforced the day it lands, not audited
    afterwards."""
    offenders: dict[str, set[str]] = {}
    for path in _scanned_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        built = _called_or_subclassed_names(tree) & _NATIVE_GL_WINDOW_CLASSES
        # QQuickWindow.setGraphicsApi(...) is a static call on the class, not an
        # instantiation — _called_or_subclassed_names records the *method* name
        # there ("setGraphicsApi"), so the RHI pin in qml_shell.py is not a hit.
        if built and "createWindowContainer" not in source:
            offenders[path.name] = built
    assert offenders == {}, (
        "QWindow-based GL surface built without createWindowContainer: "
        f"{offenders} — a GL window that is not given its own native window "
        "host is just path D with extra steps."
    )


# --------------------------------------------------------------------------- #
# Dynamic half — walk the real child tree, offscreen, simulated backends       #
# --------------------------------------------------------------------------- #

def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(seconds: float = 0.1) -> None:
    app = _app()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.005)


def test_motor_panel_hosts_no_opengl_widget():
    """The Motor panel was the one panel that did (the 3D stage page).  It is
    now RTT-free, which is what makes it material-capable as a DETACHED
    top-level (gui/detachable_tabs.py) — not just inside the main window."""
    from devices.motor_simulated import SimulatedMotorStage
    from gui.motor_panel import MotorPanel

    _app()
    panel = MotorPanel(SimulatedMotorStage())
    try:
        assert panel.findChildren(QOpenGLWidget) == []
        assert panel.findChildren(QQuickWidget) == []
        assert not isinstance(panel, QOpenGLWidget)
    finally:
        panel.shutdown()
        panel.deleteLater()
        _pump(0.1)


@pytest.mark.timeout(60)
def test_classic_main_window_is_render_to_texture_free(monkeypatch):
    """The payoff claim, asserted on the real thing: with the 3D stage view
    gone, the CLASSIC cockpit window (default boot, TCT_QML_SHELL unset) hosts
    ZERO render-to-texture children — so its HWND can carry a real DWM backdrop
    material end to end (gui/backdrop.py), instead of losing it the moment
    someone clicked "3D" on the Motor tab.

    Same construction/teardown idiom as tests/test_qml_shell.py (fully simulated
    config, never connected; explicit _teardown_panels + deferred delete)."""
    monkeypatch.delenv("TCT_QML_SHELL", raising=False)

    from tct_gui import TCTMainWindow

    monkeypatch.setattr(TCTMainWindow, "_restore_window_state", lambda self: None)
    _app()
    win = TCTMainWindow(config_path="configs/devices.yaml")
    _pump(0.1)
    try:
        assert win.findChildren(QOpenGLWidget) == [], (
            "the classic cockpit grew a render-to-texture child again — window "
            "material (glass) is dead for the whole top-level while it lives"
        )
        assert win.findChildren(QQuickWidget) == []
    finally:
        win._teardown_panels()
        win.hide()
        win.deleteLater()
        _pump(0.2)
        gc.collect()
        _pump(0.05)
