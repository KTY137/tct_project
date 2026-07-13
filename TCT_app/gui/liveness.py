"""Background device-liveness monitor.

Periodically sweeps ``DeviceManager.poll_liveness()`` from its own QThread so
a yanked USB cable or powered-off instrument flips the device's connected
flag within seconds — the Device Manager table and the main-window status
lights then repaint from the corrected flags on their own refresh timers.

Emits ``device_lost(name)`` on every connected→lost transition so the main
window can raise a status-bus warning even when no device window is open.

Usage (owner is responsible for the thread):

    monitor = LivenessMonitor(device_manager)
    thread = QThread(parent)
    monitor.moveToThread(thread)
    thread.started.connect(monitor.start)
    monitor.device_lost.connect(on_lost)          # queued → GUI thread
    thread.start()
    ...
    thread.quit(); thread.wait(2000)              # teardown
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal, Slot

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_MS = 3000


class LivenessMonitor(QObject):
    """Polls device liveness on a timer that lives in the monitor's thread."""

    device_lost = Signal(str)      # device display name

    def __init__(self, devices, interval_ms: int = _DEFAULT_INTERVAL_MS) -> None:
        super().__init__()
        self._devices = devices
        self._prev: dict[str, bool] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_ms))
        self._timer.timeout.connect(self._sweep)

    @Slot()
    def start(self) -> None:
        """Start sweeping — must run in the monitor's own thread (connect to
        QThread.started, or invoke via a queued signal)."""
        self._timer.start()

    @Slot()
    def stop(self) -> None:
        self._timer.stop()

    @Slot()
    def _sweep(self) -> None:
        try:
            alive = self._devices.poll_liveness()
        except Exception as exc:                  # never kill the timer loop
            logger.warning("Liveness sweep failed: %s", exc)
            return
        for name, ok in alive.items():
            if self._prev.get(name) and not ok:
                logger.error("Device connection lost: %s", name)
                self.device_lost.emit(name)
        self._prev = alive
