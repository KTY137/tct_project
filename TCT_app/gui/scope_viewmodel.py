"""``ScopeViewModel`` — the minimal UI->backend seam for the QML shell slice.

Per ``docs/research/qml_hybrid_architecture.md`` §7/§9, the QML chrome must bind
to the backend through a **view-model QObject** (Q_PROPERTY + signals) rather
than reaching into a panel or driver directly. This is the first, deliberately
small instance of that seam: a **read-only mirror** of already-cached scope
state (connected / simulated / acquiring + a compact status string), exposed as
NOTIFY-able Qt properties the QML rail binds a scope-status readout to.

Hard scope for slice 1 (honest cut): this does **no hardware I/O**, owns no
thread, and does **not** rewrite ``ScopePanel``. It is fed by the composition
root from state the app already polls (the ribbon's cached device flags and the
scope panel's Live-button state). A live acquisition rate is out of scope here
and left as a TODO — the property exists and defaults to empty so the QML
binding is stable, and a later task can drive it from the scope reader's
frame cadence without touching the QML.
"""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal


class ScopeViewModel(QObject):
    """Read-only Qt-property mirror of cached scope status for the QML rail."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._simulated = False
        self._acquiring = False
        self._status_text = "Scope offline"
        self._rate_text = ""   # TODO(slice 2): drive from the scope reader cadence

    # -- Python-side update (called by the composition root's cached-state
    #    poll — NEVER performs I/O; arguments are already-read flags) ------ #
    def update(
        self,
        *,
        connected: bool = False,
        simulated: bool = False,
        acquiring: bool = False,
        status: str | None = None,
        rate: str | None = None,
    ) -> None:
        self._connected = bool(connected)
        self._simulated = bool(simulated)
        self._acquiring = bool(acquiring)
        if status is not None:
            self._status_text = str(status)
        if rate is not None:
            self._rate_text = str(rate)
        self.changed.emit()

    # -- QML-facing read-only properties --------------------------------- #
    @Property(bool, notify=changed)
    def connected(self) -> bool:
        return self._connected

    @Property(bool, notify=changed)
    def simulated(self) -> bool:
        return self._simulated

    @Property(bool, notify=changed)
    def acquiring(self) -> bool:
        return self._acquiring

    @Property(str, notify=changed)
    def statusText(self) -> str:
        return self._status_text

    @Property(str, notify=changed)
    def rateText(self) -> str:
        return self._rate_text
