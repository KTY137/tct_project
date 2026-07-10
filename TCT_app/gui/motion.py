"""Tiny visual-motion helpers for cockpit chrome.

These helpers only flip dynamic properties that the app-wide QSS already
knows how to paint. They do not use QGraphicsEffect, do not touch plots or
camera frames, and every timer is parented to the widget it decorates.
"""
from __future__ import annotations

import itertools

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QWidget

from gui.style import repolish

__all__ = [
    "ActivityRing",
    "PulseController",
    "flash_property",
    "flash_readout",
    "set_pulse",
]


class PulseController:
    """Toggle a small phase property on *widget* at a fixed interval.

    ``kind`` names the semantic pulse (``laser``/``hv``/``scan`` today);
    ``motionPulsePhase`` alternates between ``0`` and ``1``. The QSS decides
    how that looks. The controller stores no hardware state and is safe to stop
    at any time.
    """

    def __init__(
        self,
        widget: QWidget,
        *,
        kind: str = "scan",
        interval_ms: int = 1300,
    ) -> None:
        self.widget = widget
        self._kind = str(kind)
        self._phase = itertools.cycle(("0", "1"))
        self._timer = QTimer(widget)
        self._timer.setInterval(max(1, int(interval_ms)))
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.widget.setProperty("motionPulse", self._kind)
        self._tick()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self, *, clear: bool = True) -> None:
        self._timer.stop()
        if clear:
            self.widget.setProperty("motionPulse", "")
            self.widget.setProperty("motionPulsePhase", "")
            repolish(self.widget)

    def set_kind(self, kind: str) -> None:
        self._kind = str(kind)
        if self.is_running():
            self.widget.setProperty("motionPulse", self._kind)
            repolish(self.widget)

    def is_running(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        self.widget.setProperty("motionPulse", self._kind)
        self.widget.setProperty("motionPulsePhase", next(self._phase))
        repolish(self.widget)


def set_pulse(
    widget: QWidget,
    active: bool,
    *,
    kind: str = "scan",
    interval_ms: int = 1300,
) -> PulseController | None:
    """Start or stop a semantic pulse on *widget*.

    The controller is cached on the widget as a private Python attribute so the
    caller can simply re-call this helper whenever cached state changes.
    """
    ctrl: PulseController | None = getattr(widget, "_motion_pulse_controller", None)
    if active:
        if ctrl is None:
            ctrl = PulseController(widget, kind=kind, interval_ms=interval_ms)
            setattr(widget, "_motion_pulse_controller", ctrl)
        else:
            ctrl.set_kind(kind)
        ctrl.start()
        return ctrl
    if ctrl is not None:
        ctrl.stop()
    return None


def flash_property(
    widget: QWidget,
    property_name: str,
    value: str,
    *,
    timeout_ms: int = 900,
) -> QTimer:
    """Temporarily set a dynamic property and restore it with a child timer."""
    old_value = widget.property(property_name) or ""
    widget.setProperty(property_name, str(value))
    repolish(widget)

    timer = QTimer(widget)
    timer.setSingleShot(True)

    def _restore() -> None:
        widget.setProperty(property_name, old_value)
        repolish(widget)
        timer.deleteLater()

    timer.timeout.connect(_restore)
    timer.start(max(1, int(timeout_ms)))
    return timer


def flash_readout(widget: QWidget, kind: str = "accent", *, timeout_ms: int = 900) -> QTimer:
    """Flash a readout cell border via the shared ``flash`` QSS hook."""
    return flash_property(widget, "flash", kind, timeout_ms=timeout_ms)


class ActivityRing(QFrame):
    """A tiny QSS-painted activity ring for low-frequency shell status."""

    def __init__(
        self,
        *,
        active: bool = False,
        interval_ms: int = 180,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("activityRing")
        self.setFixedSize(10, 10)
        self._phase = itertools.cycle(("0", "1", "2", "3"))
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(interval_ms)))
        self._timer.timeout.connect(self._tick)
        self.set_active(active)

    def set_active(self, active: bool) -> None:
        self.setVisible(bool(active))
        if active:
            self._tick()
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self.setProperty("phase", "")
            repolish(self)

    def is_active(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        self.setProperty("phase", next(self._phase))
        repolish(self)
