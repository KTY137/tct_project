"""Regression tests for ``gui.style.apply_theme`` Qt object-lifetime safety.

Background
----------
``apply_theme`` used to call ``_apply_pyqtgraph``, which walked
``QApplication.allWidgets()`` and re-styled every live ``pg.PlotWidget``.
After many widgets are created and destroyed in one process (windows closed,
panels detached, deferred deletions not yet flushed), that walk could
enumerate Python wrappers whose C++ ``QWidget`` was mid/post-destruction.
Touching — or even materialising — such a corpse access-violates *natively*,
an AV the surrounding ``try/except`` cannot catch. Under the full suite this
segfaulted the process (exit 139, faulthandler pointing at the
``for w in app.allWidgets()`` line).

The walk was removed: pyqtgraph plots self-style at construction
(``background=PLOT_BG`` + ``showGrid(...)``) and ``apply_theme`` now only sets
pyqtgraph's global config defaults. It is therefore safe to call at any time
(e.g. the settings-window theme toggle) even with closed / half-destroyed
windows still around. These tests lock that in.

Follows the existing gui test idiom: ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()`` helper, no pytest-qt.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QMainWindow

from gui.style import PLOT_BG, PLOT_FG, apply_theme

try:
    import pyqtgraph as pg
    _HAS_PG = True
except Exception:  # pragma: no cover - pyqtgraph is a hard dep in this repo
    _HAS_PG = False


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.skipif(not _HAS_PG, reason="pyqtgraph not installed")
def test_apply_theme_survives_half_destroyed_plot_windows():
    """Create windows hosting PlotWidgets, ``close()`` + ``deleteLater()`` them
    WITHOUT flushing the DeferredDelete queue, then toggle the theme both ways.

    This recreates the "corpse pile" that made the old ``allWidgets()`` walk
    access-violate. It must now be crash-safe."""
    app = _app()
    windows = []
    for _ in range(8):
        win = QMainWindow()
        win.setCentralWidget(pg.PlotWidget(background=PLOT_BG))
        windows.append(win)

    # Schedule destruction but do NOT process DeferredDelete events, so the
    # C++ objects sit in a half-alive / pending-delete state — exactly the
    # condition under which allWidgets() used to AV.
    for win in windows:
        win.close()
        win.deleteLater()

    # Historically segfaulted here (native AV -> exit 139). Must be safe now.
    assert apply_theme(app, "dark") == "dark"
    assert apply_theme(app, "light") == "light"

    # Flush the pending deletions and toggle once more — still safe post-death.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert apply_theme(app, "dark") == "dark"
    assert apply_theme(app, "light") == "light"


@pytest.mark.skipif(not _HAS_PG, reason="pyqtgraph not installed")
def test_apply_theme_does_not_touch_live_plots():
    """``apply_theme`` must not reach into existing plots. A plot that opts out
    of the dark canvas — ScanMapWindow's transparent axis overlay uses
    ``setBackground(None)`` — must keep that transparent background across a
    theme toggle (the old walk silently clobbered it to PLOT_BG)."""
    app = _app()
    apply_theme(app, "light")

    overlay = pg.PlotWidget()
    overlay.setBackground(None)  # transparent, like ScanMapWindow's overlay
    assert overlay.backgroundBrush().style() == Qt.BrushStyle.NoBrush

    apply_theme(app, "dark")
    apply_theme(app, "light")

    # apply_theme() did not call setBackground on the live overlay, so it is
    # still transparent (NoBrush), not the opaque PLOT_BG solid fill.
    assert overlay.backgroundBrush().style() == Qt.BrushStyle.NoBrush


@pytest.mark.skipif(not _HAS_PG, reason="pyqtgraph not installed")
def test_apply_theme_sets_pyqtgraph_defaults_for_future_plots():
    """The mechanism that replaced the walk: ``apply_theme`` sets pyqtgraph's
    global background/foreground config, so plots built afterwards inherit the
    dark canvas with no global widget walk required."""
    app = _app()
    apply_theme(app, "dark")
    assert pg.getConfigOption("background") == PLOT_BG
    assert pg.getConfigOption("foreground") == PLOT_FG
