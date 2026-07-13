"""Headless tests for gui.motion_kit — the "fluent motion" QWidgets kit.

Not tests/test_motion.py: that file pins the PRE-EXISTING gui/motion.py
(PulseController/ActivityRing/flash_property/set_pulse, property-flip only,
zero QGraphicsEffect — an AST-checked invariant). gui/motion_kit.py is a
deliberately separate sibling module (see its own docstring for why) with
its own, different invariants: fade_swap/pulse legitimately use
QGraphicsOpacityEffect, scoped so it never lands on a hot-path widget.

Animations are driven deterministically via QAbstractAnimation.setCurrentTime
(no real-time sleeps) per the task brief.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6
from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent
from PySide6.QtWidgets import QApplication, QLabel, QStackedWidget, QWidget

import gui.motion_kit as mk
from gui.style import TRANSITION_MS


def _flush(app: QApplication) -> None:
    """Deterministically drain queued deferred-delete / zero-delay singleShot
    events — no real-time sleep (mirrors tests/test_worker_primitive.py's
    ``sendPostedEvents`` idiom, which this module's own crash-fix pattern
    (see gui/motion_kit.py's fade_swap/pulse ``_finish``) needs the same way)."""
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stack(n: int = 3) -> QStackedWidget:
    stack = QStackedWidget()
    for i in range(n):
        stack.addWidget(QLabel(f"page {i}"))
    stack.resize(120, 80)
    return stack


# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

def test_base_ms_reuses_style_transition_ms():
    """Task-1 design decision: BASE_MS reuses gui.style.TRANSITION_MS instead
    of inventing a second base-duration constant."""
    assert mk.BASE_MS == TRANSITION_MS
    assert mk.FAST_MS < mk.BASE_MS < mk.SLOW_MS


def test_standard_easing_is_out_quint():
    assert mk.STANDARD_EASING == QEasingCurve.Type.OutQuint


# --------------------------------------------------------------------------- #
# fade_swap                                                                    #
# --------------------------------------------------------------------------- #

def test_fade_swap_kill_switch_jumps_directly(monkeypatch):
    _app()
    monkeypatch.setattr(mk, "motion_enabled", lambda: False)
    stack = _stack()
    before = len(stack.findChildren(QLabel))

    mk.fade_swap(stack, 2)

    assert stack.currentIndex() == 2
    assert getattr(stack, mk._FADE_ATTR, None) is None
    # No overlay QLabel was created — a direct jump, no animation machinery.
    assert len(stack.findChildren(QLabel)) == before


def test_fade_swap_same_or_out_of_range_index_is_noop():
    _app()
    stack = _stack()
    stack.setCurrentIndex(1)
    mk.fade_swap(stack, 1)
    assert getattr(stack, mk._FADE_ATTR, None) is None

    mk.fade_swap(stack, 99)  # out of range — Qt's own setCurrentIndex no-ops too
    assert stack.currentIndex() == 1
    assert getattr(stack, mk._FADE_ATTR, None) is None


def test_fade_swap_animates_and_lands_on_correct_index_with_effect_removed():
    app = _app()
    stack = _stack()

    mk.fade_swap(stack, 1)

    anim = getattr(stack, mk._FADE_ATTR, None)
    assert anim is not None
    overlay = anim.parent()
    assert overlay is not None and overlay.parent() is stack
    assert stack.currentIndex() == 1  # instant swap underneath, before the fade lands
    assert overlay.graphicsEffect() is not None
    assert overlay.isHidden() is False

    anim.setCurrentTime(anim.duration())  # drive to completion deterministically

    assert stack.currentIndex() == 1
    assert overlay.isHidden() is True  # hidden synchronously by _finish
    assert getattr(stack, mk._FADE_ATTR, None) is None

    _flush(app)  # the disposable overlay (+ its effect/anim children) is
    # actually gone once deleteLater() is processed — "removed after finish"
    assert not shiboken6.isValid(overlay)


def test_fade_swap_cancel_on_restart_cleans_up_prior_overlay():
    app = _app()
    stack = _stack()

    mk.fade_swap(stack, 1)
    anim1 = getattr(stack, mk._FADE_ATTR)
    overlay1 = anim1.parent()
    assert overlay1.graphicsEffect() is not None

    mk.fade_swap(stack, 2)  # interrupts anim1 before it finishes

    anim2 = getattr(stack, mk._FADE_ATTR)
    assert anim2 is not anim1
    assert overlay1.isHidden() is True  # cancelled cleanup, not leaked
    assert stack.currentIndex() == 2

    anim2.setCurrentTime(anim2.duration())
    assert stack.currentIndex() == 2
    assert getattr(stack, mk._FADE_ATTR, None) is None

    _flush(app)
    assert not shiboken6.isValid(overlay1)


def test_fade_swap_never_touches_stacked_widgets_own_effect():
    """The hot-path law: gui.motion_kit must never place a QGraphicsEffect on
    the stacked widget or its pages — only a disposable overlay label."""
    _app()
    stack = _stack()
    mk.fade_swap(stack, 1)
    assert stack.graphicsEffect() is None
    for i in range(stack.count()):
        assert stack.widget(i).graphicsEffect() is None


# --------------------------------------------------------------------------- #
# roll_number                                                                  #
# --------------------------------------------------------------------------- #

def test_roll_number_kill_switch_jumps_directly(monkeypatch):
    _app()
    monkeypatch.setattr(mk, "motion_enabled", lambda: False)
    label = QLabel()

    mk.roll_number(label, 0.0, 42.0, "{:.0f}")

    assert label.text() == "42"
    assert getattr(label, mk._ROLL_ATTR, None) is None


def test_roll_number_same_value_is_noop():
    _app()
    label = QLabel()
    mk.roll_number(label, 5.0, 5.0, "{:.1f}")
    assert label.text() == "5.0"
    assert getattr(label, mk._ROLL_ATTR, None) is None


def test_roll_number_lands_exactly_on_final_value():
    _app()
    label = QLabel()

    mk.roll_number(label, 0.0, 150.236, "{:+.2f} V")

    assert label.text() == "+0.00 V"  # starts at the OLD value, animated
    anim = getattr(label, mk._ROLL_ATTR)
    assert anim.parent() is label

    anim.setCurrentTime(anim.duration())

    assert label.text() == "+150.24 V"  # fmt applied to `new` EXACTLY, not a
    # float-interpolation near-miss (e.g. "+150.23 V" / "+150.25 V")
    assert getattr(label, mk._ROLL_ATTR, None) is None


def test_roll_number_callable_fmt():
    _app()
    label = QLabel()
    mk.roll_number(label, 0.0, 3.0, lambda v: f"n={v:.0f}")
    anim = getattr(label, mk._ROLL_ATTR)
    anim.setCurrentTime(anim.duration())
    assert label.text() == "n=3"


def test_roll_number_cancel_on_restart_uses_new_old_value():
    _app()
    label = QLabel()

    mk.roll_number(label, 0.0, 10.0, "{:.0f}")
    anim1 = getattr(label, mk._ROLL_ATTR)

    mk.roll_number(label, 5.0, 20.0, "{:.0f}")  # interrupts anim1

    assert anim1.state() == QAbstractAnimation.State.Stopped
    assert label.text() == "5"  # reset to the SECOND call's `old`
    anim2 = getattr(label, mk._ROLL_ATTR)
    assert anim2 is not anim1

    anim2.setCurrentTime(anim2.duration())
    assert label.text() == "20"
    assert getattr(label, mk._ROLL_ATTR, None) is None


# --------------------------------------------------------------------------- #
# pulse                                                                        #
# --------------------------------------------------------------------------- #

def test_pulse_kill_switch_is_noop(monkeypatch):
    _app()
    monkeypatch.setattr(mk, "motion_enabled", lambda: False)
    widget = QWidget()
    mk.pulse(widget)
    assert widget.graphicsEffect() is None
    assert getattr(widget, mk._PULSE_ATTR, None) is None


def test_pulse_sets_effect_then_restores_on_completion():
    app = _app()
    widget = QWidget()

    mk.pulse(widget)

    anim = getattr(widget, mk._PULSE_ATTR)
    assert anim.parent() is widget
    assert widget.graphicsEffect() is not None

    anim.setCurrentTime(anim.duration())  # drives `finished`, schedules the
    # deferred clear (owned_single_shot(widget, 0, ...) — see gui/motion_kit.py)
    assert getattr(widget, mk._PULSE_ATTR, None) is None

    _flush(app)  # let the zero-delay singleShot actually fire
    assert widget.graphicsEffect() is None


def test_pulse_cancel_on_restart_never_leaves_widget_dimmed():
    _app()
    widget = QWidget()

    mk.pulse(widget)
    anim1 = getattr(widget, mk._PULSE_ATTR)
    effect1 = widget.graphicsEffect()

    mk.pulse(widget)  # interrupts anim1 before it finishes

    assert anim1.state() == QAbstractAnimation.State.Stopped
    anim2 = getattr(widget, mk._PULSE_ATTR)
    assert anim2 is not anim1
    effect2 = widget.graphicsEffect()
    assert effect2 is not None and effect2 is not effect1  # cancel clears
    # the OLD effect synchronously (not from inside anim1's own finished
    # emission — see _cancel_pulse), so no deferred flush needed here.

    anim2.setCurrentTime(anim2.duration())
    assert getattr(widget, mk._PULSE_ATTR, None) is None


# --------------------------------------------------------------------------- #
# Regression: bare-widget + cyclic-GC access violation                        #
# --------------------------------------------------------------------------- #
#
# Root cause (found while writing this beat): a QVariantAnimation/
# QPropertyAnimation parented to the SAME widget its own connected closure
# (``_finish``, the ``valueChanged`` lambda) also references forms a Python
# reference cycle (widget -> anim child -> connected closure -> widget).
# Harmless while the widget has other live references (any panel still
# attached to the running app) — but when the widget's LAST external
# reference dies at the same moment (exactly this shape: a bare local
# widget going out of scope at test end, or in the real app a
# WA_DeleteOnClose detached panel closing mid-animation), Python's cyclic
# collector has to break the cycle with no knowledge of Qt's C++
# parent-owns-child contract, and combined with
# ``QAbstractAnimation.DeletionPolicy.DeleteWhenStopped`` that raced and
# access-violated reproducibly (isolated repro, not merely an artifact of
# THIS test's own shape). gui/motion_kit.py's ``_detach()`` fixes it by
# breaking the Qt parent link the moment an animation is done. These tests
# pin the exact scenario that caught it: drive to completion, drop every
# external reference, force a GC pass (no processEvents() in between — the
# whole point is to hit this BEFORE any deferred-delete flush would have
# cleaned it up some other way).

def test_roll_number_survives_bare_widget_plus_gc_after_finish():
    _app()
    label = QLabel()
    mk.roll_number(label, 0.0, 150.236, "{:+.2f} V")
    anim = getattr(label, mk._ROLL_ATTR)
    anim.setCurrentTime(anim.duration())
    del anim
    del label
    import gc
    gc.collect()  # must not access-violate


def test_pulse_survives_bare_widget_plus_gc_after_finish():
    _app()
    widget = QWidget()
    mk.pulse(widget)
    anim = getattr(widget, mk._PULSE_ATTR)
    anim.setCurrentTime(anim.duration())
    del anim
    del widget
    import gc
    gc.collect()  # must not access-violate


def test_fade_swap_survives_bare_widget_plus_gc_after_finish():
    _app()
    stack = _stack()
    mk.fade_swap(stack, 1)
    anim = getattr(stack, mk._FADE_ATTR)
    anim.setCurrentTime(anim.duration())
    del anim
    del stack
    import gc
    gc.collect()  # must not access-violate


def test_roll_number_survives_bare_widget_plus_gc_after_cancel():
    _app()
    label = QLabel()
    mk.roll_number(label, 0.0, 10.0, "{:.0f}")
    mk.roll_number(label, 3.0, 20.0, "{:.0f}")  # cancels the first mid-flight
    del label
    import gc
    gc.collect()  # must not access-violate


def test_pulse_survives_bare_widget_plus_gc_after_cancel():
    _app()
    widget = QWidget()
    mk.pulse(widget)
    mk.pulse(widget)  # cancels the first mid-flight
    del widget
    import gc
    gc.collect()  # must not access-violate


def test_fade_swap_survives_bare_widget_plus_gc_after_cancel():
    _app()
    stack = _stack()
    mk.fade_swap(stack, 1)
    mk.fade_swap(stack, 2)  # cancels the first mid-flight
    del stack
    import gc
    gc.collect()  # must not access-violate
