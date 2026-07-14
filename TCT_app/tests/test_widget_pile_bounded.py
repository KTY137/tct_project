"""The widget pile must stay bounded — the invariant whose absence turned the
bench gate RED on 2026-07-14 with a 0xC0000005 access violation.

WHAT HAPPENED. ``QApplication.setStyleSheet`` (the last line of
``gui.style.apply_theme``, i.e. what a theme toggle *is*) repolishes every live
widget in the process: measured O(N) at ~0.3-0.5 ms per widget. The suite runs
every test inside ONE offscreen ``QApplication``, so a widget a test abandons is
still there for every later test. Panels were being abandoned at **835 widgets a
piece** (see ``tests/conftest.py`` for the C++-cycle mechanism that makes them
immortal), and by test 97 of 2600 the pile stood at 62,625 widgets — where a
single ``apply_theme`` costs ~17 s. A theme-switch test that toggles a few times
then blows through the 60 s ``pytest-timeout``; ``timeout_method = thread``
aborts with ``os._exit`` mid-repolish, and *that* race is the access violation.
The AV was the symptom. The pile was the disease.

These tests pin the two facts the fix rests on, so neither can rot back:

1. ``deleteLater()`` really does reclaim an abandoned panel IN FULL. This is the
   primitive ``conftest._reap_leaked_toplevel_widgets`` is built on. If it ever
   stops being true, the reaper silently stops reaping and the pile creeps back.
2. The reaper aims ONLY at widgets this app defines. It must never delete
   pyqtgraph's parentless helper widgets (``ViewBoxMenu``, ``ColorMapMenu`` and
   its ``QWidgetAction``'s bare ``QWidget``/``QFrame``, ``QColorDialog``): a
   panel holds strong Python references to those, and deleting one directly rips
   it out from under the pyqtgraph item that still owns it and hard-aborts Qt in
   the DeferredDelete drain. That is not a theory — the first cut of the reaper
   did exactly that, and Qt died with ``Fatal Python error: Aborted``.
"""
from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _drain(app: QApplication) -> None:
    """Exactly what conftest does: collect, then flush Qt's deferred deletes."""
    gc.collect()
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_deletelater_fully_reclaims_an_abandoned_panel():
    """The reaper's primitive.

    An ``AnalysisPanel`` drags ~835 widgets in with it (its pyqtgraph plots and
    their parentless menus/colour dialogs). Dropping the last Python reference
    is NOT enough to free any of it — the panel is trapped in a reference cycle
    that runs through PySide6's C++ connection storage, which Python's gc cannot
    traverse. ``deleteLater()`` destroys the C++ object, which tears the
    connection down, which releases the closure, which breaks the cycle.

    Two things are pinned, and neither fossilises a magic number:

    * the panel's ~835-widget TREE is gone after destruction, and
    * whatever residue remains is CONSTANT — the same after the 4th cycle as
      after the 2nd. pyqtgraph allocates a few process-global menus on the
      first plot ever built and reuses them for ever (measured: 3 QMenus,
      unchanged over 12 cycles). That is a one-off, not a per-panel leak, and
      the difference between those two is the whole bug: 3 forever is fine,
      3-per-panel across 2600 tests is not.
    """
    from gui.analysis_panel import AnalysisPanel

    app = _app()

    def build_and_destroy() -> tuple[int, int]:
        """One full cycle. Returns (widgets the panel brought in, the size of
        the whole pile once it has been destroyed and drained)."""
        before = len(app.allWidgets())
        panel = AnalysisPanel()
        added = len(app.allWidgets()) - before
        panel.close()
        panel.deleteLater()
        del panel
        _drain(app)
        return added, len(app.allWidgets())

    _drain(app)
    ambient = len(app.allWidgets())      # whatever the rest of the suite is holding
    cycles = [build_and_destroy() for _ in range(5)]
    added = [a for a, _ in cycles]
    pile = [p for _, p in cycles]

    assert min(added) > 100, f"the panel built almost nothing ({added})?"

    # THE invariant, stated as the disease states it: pushing panel after panel
    # through the same slot must not make the pile GROW. It is measured as the
    # absolute pile after each cycle, not as a per-cycle net, because a handful
    # of pyqtgraph's menus are freed one drain late — they cycle in and out and
    # sit at a constant (measured: 3, flat over 12 cycles), which is harmless.
    # 3 forever is fine. 835 per panel across 2600 tests is what turned the
    # bench RED.
    assert pile[-1] == pile[1], (
        f"the widget pile GROWS as panels are built and abandoned "
        f"(pile after each cycle: {pile}; each panel brings in ~{added[-1]} "
        f"widgets). close() + deleteLater() no longer reclaims a panel in full, "
        f"and tests/conftest.py's reaper is built on exactly that primitive — "
        f"if it is broken, the pile grows across the suite again and apply_theme "
        f"(which repolishes EVERY live widget) drags it back over the 60 s "
        f"pytest-timeout, where the abort races Qt into an access violation.")

    # ...and the panels themselves must leave essentially nothing behind. Measured
    # against the AMBIENT pile the rest of the suite is holding, never against the
    # absolute count: run inside the full suite this test sits on top of tens of
    # thousands of widgets it does not own.
    left_behind = pile[-1] - ambient
    assert left_behind < added[-1] * 0.05, (
        f"5 panels built and abandoned left {left_behind} widgets behind (each "
        f"builds ~{added[-1]}) — a panel's tree is not being reclaimed")


def test_the_reaper_aims_only_at_widgets_this_app_defines():
    """The guard that keeps the reaper from aborting Qt.

    pyqtgraph hands a panel parentless helper widgets that the panel then owns
    by Python reference. They are top-level, they are abandoned-looking, and
    deleting them directly is fatal. Only ``gui.*``/``tct_gui`` classes may be
    reaped; destroying the panel is what reclaims everything it owns.
    """
    import pyqtgraph as pg
    from conftest import _is_app_owned

    from gui.analysis_panel import AnalysisPanel

    app = _app()
    panel = AnalysisPanel()
    try:
        assert _is_app_owned(panel), (
            "the app's own panel is no longer recognised as reapable — the "
            "reaper has gone blind and the pile will grow again")

        # Nothing Qt or pyqtgraph owns may ever be a target.
        assert not _is_app_owned(QWidget())
        assert not _is_app_owned(pg.PlotWidget())

        foreign = [w for w in app.topLevelWidgets()
                   if not (type(w).__module__ or "").startswith(("gui.", "tct_gui"))]
        assert foreign, "expected pyqtgraph's parentless helper widgets to exist"
        for widget in foreign:
            assert not _is_app_owned(widget), (
                f"{type(widget).__module__}.{type(widget).__name__} would be "
                f"reaped, but a live pyqtgraph item still holds it: deleting it "
                f"hard-aborts Qt in the DeferredDelete drain")
    finally:
        panel.close()
        panel.deleteLater()
        del panel
        _drain(app)


@pytest.mark.parametrize("panel_path", [
    "gui.analysis_panel.AnalysisPanel",
    "gui.scan_map_view.ScanMapView",
])
def test_abandoning_a_panel_does_not_grow_the_pile_across_tests(panel_path):
    """End to end, at the level the suite actually cares about: build a panel,
    walk away from it exactly as a test does, and let conftest's reaper run.
    The NEXT test must not inherit its widgets. (This test's own teardown is the
    thing under test — a regression shows up as a growing pile in the tests
    after it, which is precisely how the original bug hid for 42 commits.)"""
    import importlib

    module_name, _, class_name = panel_path.rpartition(".")
    cls = getattr(importlib.import_module(module_name), class_name)

    app = _app()
    panel = cls()
    assert isinstance(panel, QWidget)
    del panel                      # abandoned, exactly like the leaking tests
    # No close(), no deleteLater() — conftest's reaper is what must catch this.
