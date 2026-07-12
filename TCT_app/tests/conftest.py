"""Shared test infrastructure for the headless GUI suite.

1. Makes the TCT_app package root importable (the app itself relies on being
   run from the TCT_app directory, so tests do the same via sys.path).

2. Drains Qt deferred deletions after every test (T6, added 2026-07-10):
   the suite runs ~690 tests inside ONE offscreen ``QApplication``. Widgets
   scheduled with ``deleteLater()`` are never actually destroyed — no test
   returns control to the Qt event loop, so posted ``DeferredDelete`` events
   pile up and every dead panel (and its pyqtgraph scene) stays alive. Past a
   threshold this wedged pyqtgraph paints inside ``QWidget.grab()`` mid-suite
   (pytest-timeout abort at a GUI test that passes in isolation — the abort
   location depends only on how many GUI tests ran before it). The autouse
   fixture below flushes destructions after EVERY test so no test depends on
   the accumulated Qt state of the tests before it. It deliberately does NOT
   close or delete widgets a test created — only completes destructions the
   test itself already requested.

3. Isolates PROCESS-GLOBAL state that leaks between tests (D3, 2026-07-13) —
   the defect that made the parallel suite (``-n auto``) untrustworthy: tests
   that pass alone and pass serially failed under xdist, because the workers
   slice the suite differently and a leaked global then lands on a *different*
   victim test each run. Two leak classes are closed here:

   * ``QSettings("TCT", "TCTSetup")`` — repointed at a per-process throwaway
     .ini, so no test can read (or WRITE) the developer's real persisted
     settings, and no two xdist workers can stomp each other through one
     shared registry key. This used to happen only as a side effect of
     importing ``tests/test_ui_monkey.py``, i.e. it silently did not apply to
     any subset run that did not collect that file.
   * ``gui.style`` theme-customization module globals (glass amount, palette
     overrides, typography, radius scale — and the LIGHT/DARK dicts they
     recompute in place). A test that customizes the theme and does not reset
     it changes what every LATER test on that worker sees.
"""
from __future__ import annotations

import gc
import os
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore
from PySide6.QtCore import QSettings

# --------------------------------------------------------------------------- #
# QSettings redirection — runs at conftest IMPORT, i.e. before collection, so  #
# before any test module's import-time code, before any gui module is imported #
# and long before any window is built.                                         #
#                                                                              #
# Why the shim and not just setDefaultFormat(): Qt applies the default format  #
# ONLY to the ``QSettings(parent)`` constructor, and on Windows ``setPath`` is #
# ignored for NativeFormat. Every consumer in this app names the store          #
# explicitly — ``QSettings("TCT", "TCTSetup")`` (gui/bias_panel.py:222,        #
# tct_gui.py, gui/style.py::_default_settings, ...) — so those calls kept      #
# resolving to the REAL registry key HKCU\Software\TCT\TCTSetup no matter what #
# the format defaults said. (This is why the redirect that used to live at the #
# top of tests/test_ui_monkey.py never actually took: the monkey has been      #
# clicking the developer's real theme/geometry settings.)                      #
#                                                                              #
# Under xdist that registry key is ALSO shared by every worker process, so a   #
# test writing "theme" in worker A changed what a panel built in worker B read #
# mid-construction — a cross-process leak that cannot happen serially and that #
# picks a different victim test every run. Below, the (org, app) form is       #
# rewritten to an INI store under a per-process temp dir; every other overload #
# (e.g. QSettings(path, IniFormat) in tests) passes through untouched.         #
# --------------------------------------------------------------------------- #
_SETTINGS_DIR = tempfile.mkdtemp(prefix="tct_tests_settings_")
_RealQSettings = QSettings


class _IsolatedQSettings(_RealQSettings):
    """QSettings that can never reach the user's real per-app store."""

    def __init__(self, *args, **kwargs):
        if (len(args) == 2 and not kwargs
                and all(isinstance(a, str) for a in args)):
            super().__init__(_RealQSettings.Format.IniFormat,
                             _RealQSettings.Scope.UserScope, args[0], args[1])
        else:
            super().__init__(*args, **kwargs)


QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  _SETTINGS_DIR)
QSettings.setDefaultFormat(QSettings.Format.IniFormat)   # QSettings(parent) form
QtCore.QSettings = _IsolatedQSettings                    # (org, app) form


@pytest.fixture(autouse=True)
def _isolate_style_globals():
    """Restore ``gui.style``'s theme-customization globals after every test.

    ``gui/style.py`` keeps the user's theme knobs in module globals and
    recomputes the LIGHT/DARK palettes *in place* (dict identity is part of
    the contract — ``apply_theme`` checks ``palette is DARK``). Anything a
    test applies therefore persists into the rest of that process. Restoring
    only when the state actually moved keeps the common case free.
    """
    from gui import style

    before = (style.get_glass_amount(), style.theme_overrides("light"),
              style.theme_overrides("dark"), style.typography(),
              style.radius_scale())
    yield
    after = (style.get_glass_amount(), style.theme_overrides("light"),
             style.theme_overrides("dark"), style.typography(),
             style.radius_scale())
    if after != before:
        style.reset_theme_customization()


@pytest.fixture(autouse=True)
def _flush_qt_deferred_deletes():
    yield
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    # Collect Python-side garbage first: dropping the last Python reference
    # to a QWidget schedules its C++ deletion, which the drain below flushes.
    gc.collect()
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
