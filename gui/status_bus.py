"""
App-wide status / notification bus — decoupled from any single panel.

Panels call ``notify(text, level)`` on a user-relevant event/failure; the main
window shows it transiently in the status bar, and it is always logged (so it
also appears in the Log dock).  Levels: ``"info"`` | ``"warn"`` | ``"error"``.

This lets device panels surface failures instead of swallowing them, without
depending on the main window.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("tct.status")


class _StatusBus(QObject):
    message = Signal(str, str)   # (text, level)


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
