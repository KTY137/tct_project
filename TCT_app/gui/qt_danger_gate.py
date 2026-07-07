"""Qt-native :class:`~controller.danger_gate.DangerGate`: a confirmation dialog
that a *worker thread* can safely block on.

``ScanController``'s plan executor runs on a plain ``threading.Thread`` (see
``controller/scan_controller.py`` / ``controller/danger_gate.py``) and calls
``gate.confirm(action)`` immediately before every dangerous step (HV ramp,
stage move).  It must never touch a widget directly — only the GUI thread may
do that — so :class:`QtDangerGate` bridges the call across threads with a
queued Qt signal and blocks the caller on a ``threading.Event`` until the
GUI thread has shown the dialog and recorded an answer.

Fail-closed by design (see CLAUDE.md hardware-safety rules): a timeout, an
:meth:`abort`, or a :meth:`shutdown` all resolve any pending confirmation as
**deny**, never as an accidental "yes".  ``confirm`` never raises for a normal
refusal — only fatal misuse (calling it after ``shutdown()`` is a plain
deny too, not an exception) so the executor can always treat "not True" as a
clean stop.

Tests stub :meth:`_show_dialog` (the only method that would otherwise pop a
real ``QMessageBox``) instead of driving a real dialog headlessly.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from controller.danger_gate import DangerAction


class _PendingConfirm:
    """One in-flight confirmation: the action, its answer, and the event that
    releases the blocked worker thread once the answer is set."""

    __slots__ = ("action", "event", "result")

    def __init__(self, action: DangerAction) -> None:
        self.action = action
        self.event = threading.Event()
        self.result = False


class QtDangerGate(QObject):
    """Implements ``controller.danger_gate.DangerGate`` (``confirm(action) ->
    bool``) with a real Qt confirmation dialog.

    Safe to call ``confirm()`` from either thread:

    * From a **worker thread** (the normal case — the scan executor thread):
      the action is queued to the GUI thread via a Qt signal
      (``Qt.QueuedConnection``) and the caller blocks on a
      ``threading.Event`` until the GUI thread answers, times out
      (``timeout_s``, default 120 s -> deny), or the gate is
      :meth:`abort`-ed / :meth:`shutdown` -ed (-> deny).
    * From the **GUI thread itself** (e.g. a synchronous caller or a test):
      queuing a signal to the same thread and then blocking on it would
      deadlock (nothing pumps the event loop while blocked), so this path
      shows the dialog directly and returns its result synchronously.
    """

    DEFAULT_TIMEOUT_S = 120.0

    # Internal bridge: (DangerAction, _PendingConfirm) — never connected to
    # anything outside this class.
    _confirm_requested = Signal(object, object)

    def __init__(
        self,
        parent: QWidget | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        super().__init__(parent)
        self._parent_widget = parent
        self._timeout_s = float(timeout_s)
        self._closed = False
        self._lock = threading.Lock()
        self._pending: list[_PendingConfirm] = []
        self._confirm_requested.connect(
            self._on_confirm_requested, Qt.ConnectionType.QueuedConnection
        )

    # ------------------------------------------------------------------ #
    # DangerGate protocol                                                 #
    # ------------------------------------------------------------------ #

    def confirm(self, action: DangerAction) -> bool:
        """Ask the operator to confirm *action*; ``True`` only on an explicit
        Yes. Fail-closed on timeout/shutdown/abort/any ambiguity."""
        if self._closed:
            return False

        if self._on_gui_thread():
            return self._show_dialog(action)

        pending = _PendingConfirm(action)
        with self._lock:
            if self._closed:
                return False
            self._pending.append(pending)
        self._confirm_requested.emit(action, pending)

        answered = pending.event.wait(self._timeout_s)
        with self._lock:
            if pending in self._pending:
                self._pending.remove(pending)
        if not answered or self._closed:
            return False
        return pending.result

    # ------------------------------------------------------------------ #
    # GUI-thread side                                                     #
    # ------------------------------------------------------------------ #

    @Slot(object, object)
    def _on_confirm_requested(self, action: DangerAction, pending: _PendingConfirm) -> None:
        # Decide UNDER THE LOCK whether this request is still live before
        # showing anything: shutdown()/abort()/the confirm timeout may have
        # already released the worker while this queued call sat undelivered
        # in the event queue — showing the dialog then would pop a stray
        # modal (e.g. during window teardown) whose answer nobody reads.
        with self._lock:
            active = (not self._closed) and pending in self._pending
        if not active:
            pending.event.set()   # idempotent — every path releases
            return
        # try/finally: if the dialog itself raises, the blocked worker must
        # still be released immediately (result stays False = deny) instead
        # of stalling until the timeout.
        try:
            pending.result = self._show_dialog(action)
        finally:
            pending.event.set()

    def _show_dialog(self, action: DangerAction) -> bool:
        """Show the actual confirmation dialog. Runs on the GUI thread only.

        Factored out (rather than inlined in ``confirm``) so tests can stub
        it and exercise the threading/timeout/shutdown logic without ever
        opening a real ``QMessageBox``.
        """
        title = f"Confirm: {action.kind}"
        detail_lines = [f"{k}: {v}" for k, v in (action.detail or {}).items()]
        text = action.summary
        if detail_lines:
            text = text + "\n\n" + "\n".join(detail_lines)
        button = QMessageBox.warning(
            self._parent_widget,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return button == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------ #
    # Fail-closed release paths                                           #
    # ------------------------------------------------------------------ #

    def abort(self) -> None:
        """Deny every currently pending ``confirm()`` right away (e.g. the
        user pressed Abort mid-run). The gate stays usable for later runs."""
        self._release_pending(close=False)

    def shutdown(self) -> None:
        """Deny every pending ``confirm()`` and permanently refuse any future
        one. Call this from panel/window teardown so a dialog can never pop
        up after the owning window has started closing."""
        self._release_pending(close=True)

    def _release_pending(self, *, close: bool) -> None:
        with self._lock:
            if close:
                self._closed = True
            pending = list(self._pending)
            self._pending.clear()
        for p in pending:
            p.result = False
            p.event.set()

    # ------------------------------------------------------------------ #
    # helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _on_gui_thread() -> bool:
        app = QApplication.instance()
        if app is None:
            # No Qt event loop at all (e.g. a bare unit test): there is
            # nothing to deadlock against, so treat as "GUI thread" and go
            # synchronous rather than block forever on a signal nobody pumps.
            return True
        return QThread.currentThread() is app.thread()
