"""
App-wide status / notification bus — decoupled from any single panel.

Two channels, deliberately different in kind:

* ``notify(text, level)`` — a transient **event**: something just happened.
  The main window shows it briefly in the status bar, and it is always logged
  (so it also appears in the Log dock).  Levels: ``"info"`` | ``"warn"`` |
  ``"error"``.
* ``set_alarm(headline, level)`` — a sticky **state**: a hazard is ongoing.
  The last value stays true until it is superseded; ``""`` means all clear.
  Meant to be rendered as a persistent, always-visible indicator (a status-bar
  chip), so a hazard raised while the operator is on another tab or in a
  detached window does not scroll away after a few seconds.

This lets device panels surface failures instead of swallowing them, without
depending on the main window.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("tct.status")


class _StatusBus(QObject):
    message = Signal(str, str)   # (text, level)          — transient event
    alarm   = Signal(str, str)   # (headline, level)      — sticky state, "" = clear


STATUS = _StatusBus()


def notify(text: str, level: str = "info") -> None:
    """Log *text* and broadcast it to the status bar."""
    lvl = (level or "info").lower()
    if lvl.startswith("err"):
        logger.error(text)
    elif lvl.startswith("warn"):
        logger.warning(text)
    else:
        logger.info(text)
    STATUS.message.emit(text, lvl)


def set_alarm(headline: str, level: str = "") -> None:
    """Publish the app-wide **sticky hazard state** (currently: slow control).

    Unlike :func:`notify` — a one-shot event that fades — this is a state
    channel: render it as a persistent indicator that stays until the state
    changes.  ``headline=""``/``level=""`` means "all clear".

    Callers emit only on a CHANGE (the state is levelled, not edge-triggered,
    so re-emitting the same headline every poll would be harmless but wasteful
    — and dangerous if a consumer ever routes it to a log or a toast).  The
    headline therefore carries no live measurement value: a steady alarm whose
    number drifts must not re-emit.  The value belongs in the :func:`notify`
    message and on the Monitor tab.

    Not logged here: the caller has already logged the transition through
    :func:`notify`, and double-logging a levelled state on every change is how
    a log becomes unreadable.
    """
    STATUS.alarm.emit(str(headline or ""), (level or "").lower())
