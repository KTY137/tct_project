"""Order-independent proof that the panel-glass registry never yields a dead
widget.

BUG (glass wave, BEAT 0). ``gui/panel_kit._GLASS_PANE_REGISTRY`` is a
``WeakSet[QWidget]``. A WeakSet forgets an entry only when the *Python* wrapper
is garbage-collected -- NOT when the underlying C++ ``QObject`` is destroyed. A
QQuickWidget-heavy teardown deletes the C++ side while a Python wrapper is still
referenced elsewhere; the registry then still holds that wrapper, and
``registered_glass_panes()`` used to hand it straight back. The wrapper is a
live Python object, so ``list(reg)`` does not raise -- but the first attribute
access on it raises ``RuntimeError: Internal C++ object already deleted``.

The existing guard test (``test_panel_kit_cockpit
.test_set_panel_glass_survives_a_destroyed_registered_pane``) ``del``\\s its
reference, so the wrapper is GC'd and the WeakSet drops it on its own -- it never
reaches the dead-wrapper-survives state this bug is about. These tests hold a
strong Python reference across the C++ deletion, so the wrapper genuinely
outlives its C++ object, and they assert order-independently (relative
membership, never an absolute registry size) so collection order cannot hide the
failure.

Idiom follows the gui test convention: QT_QPA_PLATFORM=offscreen, a shared
QApplication.instance() helper, no pytest-qt. PySide6 / shiboken6 only.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6
from shiboken6 import isValid
from PySide6.QtWidgets import QApplication, QWidget

import gui.panel_kit as panel_kit
from gui.panel_kit import Card, GlassPane, register_glass_pane, registered_glass_panes


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _in_raw_registry(widget: QWidget) -> bool:
    """Identity membership in the raw WeakSet (``is``, never ``==`` -- a dead
    wrapper's ``__eq__`` would touch the deleted C++ object). Proves the dead
    entry was actually present before a read pruned it, so the prune does real
    work rather than the WeakSet having already dropped it."""
    return any(w is widget for w in panel_kit._GLASS_PANE_REGISTRY)


def test_registry_prunes_a_pane_whose_cpp_object_was_deleted():
    """Deterministic reproduction: register a pane, keep a strong Python ref,
    delete ONLY the C++ side. The registry must never yield the dead wrapper and
    must never raise."""
    _app()
    dead = Card("Explicitly deleted")
    register_glass_pane(dead)

    shiboken6.delete(dead)                     # kill C++ now; wrapper survives
    assert not isValid(dead)                   # precondition: genuinely dead
    assert _in_raw_registry(dead)              # and still sitting in the WeakSet

    # The read must prune it, not hand it back, and not raise.
    panes = registered_glass_panes()
    assert dead not in panes
    assert all(isValid(w) for w in panes)
    # Stronger than isValid: the returned panes are actually USABLE (attribute
    # access on a dead wrapper is exactly what raised the reported RuntimeError).
    for w in panes:
        w.objectName()

    # Eager drop: a second read no longer even holds the dead entry.
    assert not _in_raw_registry(dead)


def test_registry_prunes_a_pane_whose_parent_window_was_torn_down():
    """The QQuickWidget-shaped case: a registered pane is a child of a window
    that is torn down. Deleting the parent's C++ object cascades to the child's
    C++ object, but the child's Python wrapper survives in a local ref -- a dead
    registry entry, without ever touching the child directly.

    ``shiboken6.delete`` runs the parent's C++ destructor NOW (deterministic);
    ``QWidget.deleteLater`` would only post a ``DeferredDelete`` that a bare
    ``processEvents()`` does not dispatch, so the teardown would not actually
    happen in a headless run."""
    _app()
    parent = QWidget()
    child = GlassPane("Child on a doomed window", parent=parent)   # auto-registers
    assert isValid(child)
    assert _in_raw_registry(child)

    shiboken6.delete(parent)                   # tear the window down; child C++ dies

    assert not isValid(child)                  # parent teardown killed the child C++
    assert _in_raw_registry(child)             # wrapper (our ref) kept the dead entry

    panes = registered_glass_panes()
    assert child not in panes
    assert all(isValid(w) for w in panes)
    for w in panes:
        w.objectName()


def test_registry_yields_live_panes_alongside_a_dead_one():
    """Mixed state, order-independent: a live registered pane must still be
    returned while a dead sibling is pruned -- proving the prune is a filter,
    not a blanket clear."""
    _app()
    live = Card("Survivor")
    doomed = Card("Doomed")
    register_glass_pane(live)
    register_glass_pane(doomed)

    shiboken6.delete(doomed)
    assert not isValid(doomed)

    panes = registered_glass_panes()
    assert live in panes                       # live entry preserved
    assert doomed not in panes                 # dead entry dropped
    assert all(isValid(w) for w in panes)


def test_set_panel_glass_tolerates_a_surviving_dead_wrapper():
    """set_panel_glass funnels through registered_glass_panes(), so a dead
    wrapper that OUTLIVES its C++ object (strong ref held) must not make the
    switch raise. This is the harder variant the cockpit guard test does not
    reach (it ``del``\\s its ref, letting the WeakSet drop the entry first)."""
    _app()
    dead = Card("Toggled after death")
    register_glass_pane(dead)
    shiboken6.delete(dead)
    assert not isValid(dead)
    assert _in_raw_registry(dead)              # dead entry present at toggle time

    try:
        panel_kit.set_panel_glass(True)        # must not raise
        panel_kit.set_panel_glass(False)
    finally:
        panel_kit.set_panel_glass(False)       # never leak the module-wide state
