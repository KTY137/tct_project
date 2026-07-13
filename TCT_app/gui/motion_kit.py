"""gui/motion_kit.py — the "fluent motion" layer for QWidgets panels.

Small, OWNED, interruptible animation helpers (the QWidgets-side counterpart
to the QML shell's spring/``Behavior`` bindings, which stay the shell's own
job — see ``gui/qml/Shell.qml`` / ``gui/qml_theme.py``'s ``transitionMs``).

Not ``gui/motion.py``
----------------------
``gui/motion.py`` already exists (commit ``0800b39``) and does a different,
orthogonal job: CONTINUOUS semantic status pulsing (``PulseController``/
``set_pulse``/``ActivityRing``) and a QSS-property flash (``flash_property``/
``flash_readout``), all implemented as dynamic-property flips +
``repolish()`` — deliberately NEVER a ``QGraphicsEffect`` (pinned by
``tests/test_motion.py::test_motion_never_calls_set_graphics_effect``, an
AST scan of that entire module's source). This kit's :func:`fade_swap` and
:func:`pulse` need a real, one-shot ``QGraphicsOpacityEffect`` (the brief
that produced this module names it explicitly), which would break that
pinned invariant if dropped into the same file — so this is a sibling
module, not an addition to it. ``gui/motion.py``'s ``set_pulse`` (a
continuous laser/HV/scan activity indicator) and this module's ``pulse()``
(a one-shot attention pulse on a state CHANGE) are two intentionally
different mechanisms; do not conflate them.

Every helper here:

  * is parented to the widget it animates (or to a disposable overlay it
    creates and owns) WHILE RUNNING, so it dies with its target if that
    target is destroyed mid-animation — never a bare, unparented
    ``QPropertyAnimation``/``QVariantAnimation`` left ticking against a
    destroyed widget (the exact leak class ``gui/worker.py`` exists to rule
    out for threads; this module applies the same discipline to animations)
    — and is explicitly detached (:func:`_detach`) the moment it is done
    (finished or cancelled), because staying parented forever turned out to
    be its own hazard — see :func:`_detach`'s docstring for the
    access-violation this avoids,
  * cancels/replaces (never stacks) a prior in-flight call on the same
    target, restoring a clean end state before starting the new one, and
  * becomes a no-op **jump straight to the end state** when
    :func:`motion_enabled` is ``False`` — this app's prefers-reduced-motion
    equivalent (``gui.app_settings.motion_enabled``/``set_motion_enabled``;
    no settings-UI toggle yet, a follow-up).

Duration scale
--------------
``BASE_MS`` reuses ``gui.style.TRANSITION_MS`` (200 ms, the law-8 "state
transitions ease ~200 ms" constant already mirrored into QML as
``Theme.transitionMs`` — see that module's own comment: "any future
QVariantAnimation-driven repolish agrees on one number instead of each call
site picking its own"). This IS that future call site, so it reuses the
number instead of introducing a second, competing "base duration" constant.
``FAST_MS``/``SLOW_MS`` keep the same proportional spacing (0.6x / 1.8x) as
the design artifact's own suggested 150/250/450 ms scale, just rebased onto
the canonical 200 ms instead of a new 250 ms.

Easing
------
The design artifact's ``cubic-bezier(.22, 1, .36, 1)`` is the widely-known
"easeOutQuint" curve — a quintic ``1 - (1-t)**5`` decelerating ease-out (fast
start, long soft settle), not the gentler cubic ``1 - (1-t)**3``
"easeOutCubic". ``QEasingCurve.Type.OutQuint`` is Qt's closer built-in match
(same polynomial order/shape); that is ``STANDARD_EASING`` here.
``QEasingCurve.Type.OutCubic`` stays in use elsewhere unchanged (e.g.
``CollapsibleCard``'s bottom-sheet snap, docs/design/council_v5_noah.md §5)
— this pick does not touch that call site, and any caller here can still
override per-call via the ``easing`` kwarg.

Hard perf laws (non-negotiable, see CLAUDE.md / cockpit_style_overhaul.md §1)
-------------------------------------------------------------------------
Nothing in this module may be applied to a **hot-path widget** — the camera
view, any pyqtgraph plot, or a container that hosts one — with a
``QGraphicsEffect``. :func:`fade_swap` is built specifically to respect this
even when the ``QStackedWidget`` it swaps hosts a plot page (see its
docstring for the mechanism); :func:`pulse` sets a real
``QGraphicsOpacityEffect`` on its target and CANNOT check this for you — it
is only for non-plot chrome (status chips, badges), never a FigureCard/
camera/plot or their containers. No helper here calls ``repolish()``/mutates
a Qt stylesheet ``property`` per frame — that per-frame-repolish class is
exactly what ``tests/test_style_hover_hotpath_guard.py`` exists to catch;
this module only ever touches ``.setText()``/opacity, never a stylesheet
property.
"""
from __future__ import annotations

from typing import Callable, Union

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QPropertyAnimation, QVariantAnimation, Qt,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QStackedWidget, QWidget

from gui.app_settings import motion_enabled  # re-exported: gui.motion_kit.motion_enabled
from gui.style import TRANSITION_MS
from gui.worker import owned_single_shot

__all__ = [
    "STANDARD_EASING", "FAST_MS", "BASE_MS", "SLOW_MS",
    "motion_enabled", "fade_swap", "roll_number", "pulse",
    "cancel_roll", "cancel_pulse", "cancel_all",
]

# -- easing / duration scale (see module docstring) ------------------------ #
STANDARD_EASING = QEasingCurve.Type.OutQuint

BASE_MS = TRANSITION_MS         # 200 ms — gui.style's canonical law-8 constant
FAST_MS = 120                   # 0.6x BASE — same ratio as the artifact's 150/250
SLOW_MS = 360                   # 1.8x BASE — same ratio as the artifact's 450/250

NumberFormat = Union[str, Callable[[float], str]]

# Attribute names used to stash the "currently active" animation on its
# target widget (roll_number/pulse) — see _cancel_attr().
_ROLL_ATTR = "_tct_motion_roll_anim"
_PULSE_ATTR = "_tct_motion_pulse_anim"
_FADE_ATTR = "_tct_motion_fade_anim"
# Stashes the (target, handler) for an animation's mid-flight destroy-guard
# (see _arm_destroy_guard) so _detach can disarm it on every retire path.
_DESTROY_GUARD_ATTR = "_tct_motion_destroy_guard"


def _detach(obj) -> None:
    """Retire *obj*: disarm its :func:`_arm_destroy_guard` ``destroyed`` guard
    (if any) and break its Qt parent-child link. Called on every animation this
    module creates, on every path that is done with it (natural finish AND
    cancel). Why the parent break: a ``QVariantAnimation``/``QPropertyAnimation``
    parented to the same widget
    its own connected closure also references forms a Python reference cycle
    that is harmless while that widget has other live references (the normal
    case), but crashed reproducibly when the widget's last external
    reference died at the same time (a bare local widget going out of scope;
    a ``WA_DeleteOnClose`` detached panel closing) and Python's cyclic
    collector had to referee a cycle Qt's C++ parent-owns-child contract
    doesn't know about. Detaching is synchronous, ordinary, and confirmed (by
    the same repro that found this) to still let ``DeleteWhenStopped`` reap
    the animation correctly on the next event-loop pass. Disarming the guard
    in the SAME step keeps the two halves of "this animation is done" together,
    and stops a long-lived readout (which rolls every poll tick) from
    accumulating stale ``destroyed`` connections on its label."""
    guard = getattr(obj, _DESTROY_GUARD_ATTR, None)
    if guard is not None:
        setattr(obj, _DESTROY_GUARD_ATTR, None)
        target, handler = guard
        try:
            target.destroyed.disconnect(handler)
        except (RuntimeError, TypeError):
            pass  # target already gone, or the connection already dropped
    try:
        obj.setParent(None)
    except RuntimeError:
        pass  # underlying C++ QObject already gone


def _arm_destroy_guard(anim, target) -> None:
    """Defend against *target* being destroyed WHILE *anim* is still running —
    the one path :func:`_detach` does not otherwise cover. Finish, cancel and
    motion-off all detach *anim* explicitly; a bare last-reference drop or a
    ``WA_DeleteOnClose`` detached panel closing mid-animation never runs any of
    those, so the animation stays parented (and cyclically referenced) into the
    exact access-violation :func:`_detach` exists to prevent.

    Fix: connect *target*'s ``destroyed`` to a handler that STOPS and unparents
    *anim*. ``destroyed`` fires at the very top of ``~QObject`` — before Qt
    deletes children — so *anim*'s C++ object is still valid in the slot, but
    *target*'s is mid-teardown: the handler therefore touches ONLY the
    animation, never the widget. Stopping halts ``valueChanged`` before the
    widget is gone; unparenting breaks the Qt-parent<->Python-cycle cyclic GC
    would otherwise have to referee. The connection is disarmed by
    :func:`_detach` on every normal finish/cancel, so it never lingers or
    accumulates."""
    def _on_target_destroyed(*_a, _anim=anim) -> None:
        try:
            _anim.stop()
        except RuntimeError:
            pass
        try:
            _anim.setParent(None)
        except RuntimeError:
            pass
        setattr(_anim, _DESTROY_GUARD_ATTR, None)  # guard consumed
    setattr(anim, _DESTROY_GUARD_ATTR, (target, _on_target_destroyed))
    target.destroyed.connect(_on_target_destroyed)


def _cancel_attr(owner: QWidget, attr: str) -> None:
    """Stop, detach and drop a previously-stored animation on *owner* (if
    any), so a helper called again on the same target never runs two
    animations at once. Does not otherwise touch *owner*'s visible state —
    callers whose animation can leave a widget in a non-default state
    (opacity dimmed, etc.) restore it themselves (see :func:`_cancel_pulse`).
    """
    prev = getattr(owner, attr, None)
    if prev is not None:
        setattr(owner, attr, None)
        try:
            prev.stop()
        except RuntimeError:
            pass  # underlying C++ QObject already gone
        _detach(prev)


def _render(fmt: NumberFormat, value: float) -> str:
    return fmt(value) if callable(fmt) else fmt.format(value)


# --------------------------------------------------------------------------- #
# fade_swap — QStackedWidget page cross-fade                                  #
# --------------------------------------------------------------------------- #

def _cancel_fade(stacked: QStackedWidget) -> None:
    """Tear down a fade already in flight on *stacked*, INCLUDING its overlay
    label/effect. ``QAbstractAnimation.stop()`` does not emit ``finished``, so
    the generic :func:`_cancel_attr` alone would leak the overlay — this
    performs the same cleanup :func:`fade_swap`'s ``finished`` handler does,
    synchronously, before a new fade grabs a fresh snapshot."""
    anim = getattr(stacked, _FADE_ATTR, None)
    if anim is None:
        return
    setattr(stacked, _FADE_ATTR, None)
    overlay = anim.parent()
    try:
        anim.stop()
    except RuntimeError:
        pass
    _detach(anim)  # see _detach's docstring — anim<->overlay closure cycle
    if overlay is not None:
        try:
            # hide() (not setGraphicsEffect(None)) so a fresh grab() right
            # after never captures the stale ghost overlay — no synchronous
            # QObject deletion here at all; deleteLater() cascades effect
            # (still parented to overlay) on the next event-loop pass.
            overlay.hide()
            _detach(overlay)  # same cycle risk one level up (overlay<->stacked)
            overlay.deleteLater()
        except RuntimeError:
            pass


def fade_swap(
    stacked: QStackedWidget,
    new_index: int,
    *,
    duration: int | None = None,
    easing: QEasingCurve.Type | None = None,
) -> None:
    """Opacity cross-fade a ``QStackedWidget`` page change.

    Never places a ``QGraphicsEffect`` on *stacked* or any of its pages — the
    hot-path law bans a ``QGraphicsEffect`` on a pyqtgraph plot OR ITS
    CONTAINER, and several of this app's stacked pages host one (e.g.
    ``gui/analysis_panel.py``'s 2D-map/CCE/Survey mode stack wraps
    ``ScanMapView``/plot content). Instead: grab a static ``QPixmap``
    snapshot of the OUTGOING page, show it in a throwaway ``QLabel`` overlay
    on top of the stack, swap ``stacked``'s current index INSTANTLY
    underneath (the incoming page is live immediately, not delayed behind
    the fade), then fade ONLY that disposable snapshot label to transparent
    and delete it. The live widget subtree the stack actually manages is
    never touched by an effect at any point.

    A no-op immediate ``setCurrentIndex(new_index)`` when
    :func:`motion_enabled` is ``False``, when *new_index* is already current,
    or when it is out of range. Cancels/replaces any fade already in flight
    on *stacked* (see :func:`_cancel_fade`).
    """
    _cancel_fade(stacked)
    if new_index == stacked.currentIndex() or not (0 <= new_index < stacked.count()):
        stacked.setCurrentIndex(new_index)
        return
    if not motion_enabled():
        stacked.setCurrentIndex(new_index)
        return

    pixmap = stacked.grab()
    overlay = QLabel(stacked)
    overlay.setPixmap(pixmap)
    overlay.setGeometry(stacked.rect())
    overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    overlay.show()
    overlay.raise_()

    # Instant swap UNDERNEATH the overlay — no QGraphicsEffect ever touches
    # this call, or anything it manages.
    stacked.setCurrentIndex(new_index)

    effect = QGraphicsOpacityEffect(overlay)
    overlay.setGraphicsEffect(effect)
    effect.setOpacity(1.0)

    anim = QPropertyAnimation(effect, b"opacity", overlay)
    anim.setDuration(BASE_MS if duration is None else int(duration))
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(STANDARD_EASING if easing is None else easing)

    def _finish() -> None:
        # NEVER synchronously delete `effect` (setGraphicsEffect(None)) here:
        # this slot runs from INSIDE anim's own finished-signal emission
        # (still on QPropertyAnimation's internal C++ call stack, about to
        # run its own DeleteWhenStopped self-deleteLater()) — `effect` IS
        # anim's literal C++ property target, and destroying it re-entrantly
        # from here access-violated in testing. hide() + a plain (fully
        # deferred, non-destructive) deleteLater() is safe; overlay's
        # eventual destruction cascades to `effect` (still its child) on a
        # later, separate event-loop pass. anim/overlay are ALSO explicitly
        # _detach()'d — see that function's docstring for the separate
        # (Python-GC-cycle) access-violation this avoids.
        overlay.hide()
        _detach(anim)
        _detach(overlay)
        overlay.deleteLater()
        if getattr(stacked, _FADE_ATTR, None) is anim:
            setattr(stacked, _FADE_ATTR, None)

    anim.finished.connect(_finish)
    setattr(stacked, _FADE_ATTR, anim)
    # Mid-flight safety net: if `stacked` is externally destroyed before the
    # fade lands (finish/cancel never run), stop + unparent the anim (parented
    # to the disposable overlay, itself a child of `stacked`) — see
    # _arm_destroy_guard.
    _arm_destroy_guard(anim, stacked)
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# --------------------------------------------------------------------------- #
# roll_number — QVariantAnimation-driven numeric readout roll                 #
# --------------------------------------------------------------------------- #

def roll_number(
    label: QLabel,
    old: float,
    new: float,
    fmt: NumberFormat,
    *,
    duration: int | None = None,
    easing: QEasingCurve.Type | None = None,
    force: bool = False,
) -> None:
    """Animate *label*'s text from *old* to *new*, re-rendering via *fmt* at
    every intermediate frame.

    *fmt* is either a ``str.format``-style template (``"{:+.2f} V"``) or a
    ``callable(value) -> str``. Tabular-numeral rendering is the LABEL's own
    responsibility (the mono/tabular value font role ``MetricTile``/
    ``ReadoutCell`` value labels already carry) — this helper only ever
    calls ``.setText()``, never touches fonts or stylesheet properties.

    Always lands EXACTLY on ``fmt`` applied to *new* when finished (or
    immediately, if the DISPLAYED text does not change or motion is off) —
    never a float-interpolation rounding near-miss. Cancels/replaces any roll
    already in flight on *label*.

    Change-gate on the *rendered string*, not the raw float: a live readback
    (HV voltage, current, ...) almost never repeats a bit-identical float
    between poll ticks, so a raw ``old == new`` gate let the tile re-roll on
    ~every ~500 ms tick even when the shown number never moved — a static
    reading that visibly animates reads as RAMPING to an operator. When the
    formatted text is unchanged we land it directly and skip the animation
    entirely. ``force=True`` overrides the gate (animate even if the string is
    unchanged) for callers/tests that want the motion regardless.
    """
    _cancel_attr(label, _ROLL_ATTR)
    final_text = _render(fmt, new)
    start_text = _render(fmt, old)
    if not motion_enabled() or (not force and start_text == final_text):
        label.setText(final_text)
        return

    label.setText(start_text)

    anim = QVariantAnimation(label)
    anim.setDuration(BASE_MS if duration is None else int(duration))
    anim.setStartValue(float(old))
    anim.setEndValue(float(new))
    anim.setEasingCurve(STANDARD_EASING if easing is None else easing)
    anim.valueChanged.connect(lambda v: label.setText(_render(fmt, v)))

    def _finish() -> None:
        label.setText(final_text)
        if getattr(label, _ROLL_ATTR, None) is anim:
            setattr(label, _ROLL_ATTR, None)
        _detach(anim)  # see _detach's docstring (anim<->label closure cycle)

    anim.finished.connect(_finish)
    setattr(label, _ROLL_ATTR, anim)
    _arm_destroy_guard(anim, label)   # survive a mid-flight destruction of label
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# --------------------------------------------------------------------------- #
# pulse — one soft attention pulse (NOT gui.motion.set_pulse — see module     #
# docstring)                                                                   #
# --------------------------------------------------------------------------- #

def _cancel_pulse(widget: QWidget) -> None:
    """As :func:`_cancel_attr`, plus always drop any lingering
    ``QGraphicsEffect`` — :func:`pulse` sets one directly on *widget* (unlike
    :func:`fade_swap`'s disposable overlay), so an interrupted pulse must
    never leave the widget dimmed."""
    _cancel_attr(widget, _PULSE_ATTR)
    try:
        widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


def pulse(
    widget: QWidget,
    *,
    duration: int | None = None,
    easing: QEasingCurve.Type | None = None,
) -> None:
    """One soft attention pulse: a brief opacity dip-and-recover.

    NEVER a stylesheet ``property``/``repolish()`` flip — that different,
    QSS-driven idiom is ``gui.status_widgets.flash_button`` /
    ``gui.motion.set_pulse`` (a CONTINUOUS activity indicator — see this
    module's docstring); this one is a single ATTENTION pulse for a state
    CHANGE, without the per-frame stylesheet churn the hot-path guard test
    bans.

    HARD RULE: never call this on a ``FigureCard``/camera view/pyqtgraph
    plot or a container that hosts one — this sets a real
    ``QGraphicsOpacityEffect`` on *widget* and cannot check that boundary for
    you (see the module docstring's "Hard perf laws").

    A no-op when :func:`motion_enabled` is ``False``. Cancels/replaces any
    pulse already in flight on *widget*, and always restores full opacity +
    removes the effect when done (or immediately, if interrupted or motion is
    off) — never leaves a widget dimmed.
    """
    _cancel_pulse(widget)
    if not motion_enabled():
        return

    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    effect.setOpacity(1.0)

    anim = QVariantAnimation(widget)
    anim.setDuration(BASE_MS if duration is None else int(duration))
    anim.setKeyValueAt(0.0, 1.0)
    anim.setKeyValueAt(0.5, 0.55)
    anim.setKeyValueAt(1.0, 1.0)
    anim.setEasingCurve(STANDARD_EASING if easing is None else easing)
    anim.valueChanged.connect(effect.setOpacity)

    def _clear_effect() -> None:
        # Only clears the effect THIS pulse installed — a newer pulse call
        # (or a cancel) may already have replaced/removed it by the time this
        # deferred callback runs.
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    def _finish() -> None:
        if getattr(widget, _PULSE_ATTR, None) is anim:
            setattr(widget, _PULSE_ATTR, None)
        _detach(anim)  # see _detach's docstring (anim<->widget closure cycle)
        # Deferred (owned_single_shot(..., 0, ...), not a synchronous
        # setGraphicsEffect(None) here): this slot runs from INSIDE anim's
        # own finished-signal emission, and fade_swap's identical shape
        # access-violated when it deleted a QObject at that point in the
        # call stack (see its own ``_finish``) — this mirrors that fix
        # rather than relying on QVariantAnimation (no literal C++ property
        # target, unlike fade_swap's QPropertyAnimation) being provably safe.
        owned_single_shot(widget, 0, _clear_effect)

    anim.finished.connect(_finish)
    setattr(widget, _PULSE_ATTR, anim)
    _arm_destroy_guard(anim, widget)   # survive a mid-flight destruction of widget
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# --------------------------------------------------------------------------- #
# Public cancel helpers — quiesce in-flight motion during teardown            #
# --------------------------------------------------------------------------- #

def cancel_roll(label: QLabel) -> None:
    """Stop + detach any in-flight :func:`roll_number` animation on *label*.

    For teardown paths (panel ``shutdown``) that must quiesce a rolling readout
    before the widget — or a thread that feeds it — goes away. Leaves whatever
    text is currently shown; does not force the final value (a shutting-down
    panel has nothing to display). No-op if nothing is rolling."""
    _cancel_attr(label, _ROLL_ATTR)


def cancel_pulse(widget: QWidget) -> None:
    """Stop + detach any in-flight :func:`pulse` on *widget* and restore full
    opacity (never leaves it dimmed). No-op if nothing is pulsing."""
    _cancel_pulse(widget)


def cancel_all(widget: QWidget) -> None:
    """Stop + detach every in-flight motion_kit animation owned by *widget* —
    a roll, a pulse, and (if *widget* is a ``QStackedWidget``) a page fade.
    The blanket quiesce for a widget being torn down."""
    _cancel_attr(widget, _ROLL_ATTR)
    _cancel_pulse(widget)
    if isinstance(widget, QStackedWidget):
        _cancel_fade(widget)
