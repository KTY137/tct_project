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
"""
from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


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
