"""gui/worker.py — one owned worker-lifecycle primitive for the GUI.

Motivation
----------
~22-25 ``gui/`` sites hand-roll ``moveToThread`` + ``QThread`` + ``quit()`` /
``wait()`` with divergent magic timeouts and ad-hoc done-signal wiring
(``docs/TECH_DEBT.md``: "no shared worker-lifecycle primitive").  The recurring
bug class — proved at commit ``41a8ab2`` with a ``QThread.currentThread()``
probe — is a worker's *terminal* signal wired to a **context-less closure**.
Qt cannot infer a receiver thread for a bare ``lambda``/closure, so it uses a
*direct* connection and runs the slot **on the worker thread**:

  * ``thread.wait()`` inside it becomes a wait-on-**itself** (never returns), and
  * any widget touch (``setEnabled``) races the GUI thread's own state.

:class:`WorkerThread` makes that entire class impossible **by construction**:

  * The terminal signal is delivered to a **bound method** of this GUI-thread
    handle, so ``AutoConnection`` queues teardown to the owner (GUI) thread.
  * Teardown **never waits on its own thread** (``QThread.currentThread``
    guard) — even if a caller mis-wires something, it degrades to "don't wait",
    never to a deadlock.
  * The finished ``QThread`` + worker are **reaped by dropping their Python
    refs on the owner thread** (GUI-side destruction, the fix pattern from
    ``docs/TECH_DEBT.md`` row on ``finished→deleteLater``).  Nothing is left
    parented to a long-lived panel, so stopped threads never accumulate over a
    session, and no ``~QObject`` runs on the worker thread.
  * :meth:`shutdown` distinguishes :attr:`ShutdownKind.ABANDON` (best-effort —
    request stop, drop it if it will not join) from
    :attr:`ShutdownKind.MUST_COMPLETE` (an HV ramp-class op — a worker that
    will not join in time emits :attr:`orphaned` *and* logs at ERROR, so it is
    **never silently orphaned**).

This module is intentionally hardware-agnostic: it owns *threads*, not devices.
It performs no device I/O and imports nothing from ``devices/``.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal, SignalInstance

logger = logging.getLogger(__name__)

# Single house default for the teardown join, replacing the 2000/3000 ms magic
# numbers scattered across the hand-rolled sites (motor_panel alone had both).
DEFAULT_JOIN_MS = 2000


class ShutdownKind(Enum):
    """How :meth:`WorkerThread.shutdown` treats a worker that will not join.

    ``ABANDON``
        Best-effort teardown.  A cooperative stop is requested (``stop_hook``)
        and the thread is dropped if it does not finish in time.  Correct for
        pollers and for sweeps whose ``abort()`` merely stops *stepping* — the
        device is left in a state the next readout re-derives.

    ``MUST_COMPLETE``
        HV ramp-class work that must not be silently orphaned.  No cooperative
        stop is requested (we *want* it to finish); on timeout the handle emits
        :attr:`WorkerThread.orphaned` and logs at ERROR so the incomplete HV
        operation is loud, never swallowed (Mary rider: a shutdown ``wait``
        must never abandon a still-RAMPING worker in silence).
    """

    ABANDON = "abandon"
    MUST_COMPLETE = "must_complete"


class WorkerThread(QObject):
    """GUI-thread-owned lifecycle handle around one off-thread ``QObject`` worker.

    The ``worker`` is a plain ``QObject`` exposing a ``run()`` slot (invoked once
    when the thread starts) and a *terminal* signal emitted exactly once when it
    is done.  This handle owns the ``QThread``, moves the worker onto it, wires
    the terminal signal to a GUI-thread teardown slot, joins + reaps on
    completion, and re-emits completion as :attr:`finished` — **on the owner
    (GUI) thread**.

    Intermediate signals (progress, per-point data, early-stop reasons) stay the
    caller's business: connect them to the worker directly, using **bound
    methods** of your GUI widget (not lambdas) so they too are queued to the GUI
    thread.

    Ownership: pass ``parent`` (your panel) so the handle dies with it.  Keep a
    reference to the handle for its whole run; drop it after :attr:`finished` /
    :meth:`shutdown`.
    """

    #: Emitted on the OWNER thread once the worker's terminal signal fired and
    #: the thread was joined + reaped.  Carries the terminal signal's first
    #: argument (e.g. an error string), or ``None`` if the terminal took none.
    finished = Signal(object)

    #: Emitted (owner thread) when a ``MUST_COMPLETE`` worker could not be joined
    #: within the shutdown timeout — a loud, non-silent failure surface.
    orphaned = Signal(str)

    def __init__(
        self,
        worker: QObject,
        terminal: SignalInstance,
        *,
        kind: ShutdownKind = ShutdownKind.ABANDON,
        stop_hook: Optional[Callable[[], None]] = None,
        join_ms: int = DEFAULT_JOIN_MS,
        name: str = "worker",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._worker: Optional[QObject] = worker
        self._thread: Optional[QThread] = QThread()  # unparented → Python-owned,
        #   so reaping = dropping the ref on THIS (owner) thread destroys it here,
        #   not on the worker thread and not as a leaked child of a long-lived
        #   panel.  We never let it run while unreferenced (this handle holds it).
        self._kind = kind
        self._stop_hook = stop_hook
        self._join_ms = int(join_ms)
        self._name = name
        self._started = False
        self._reaped = False

        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        # Terminal → BOUND METHOD of this GUI-thread handle: AutoConnection posts
        # it to the owner event loop (a QueuedConnection).  This is the whole
        # point of the primitive — never a context-less closure, so teardown can
        # never run in the worker's own context (the 41a8ab2 bug class).
        terminal.connect(self._on_terminal)

    # -- lifecycle ---------------------------------------------------------- #

    def start(self) -> None:
        """Start the worker thread.  Call once, from the GUI thread."""
        if self._started:
            raise RuntimeError(f"WorkerThread({self._name!r}) already started")
        if self._thread is None:
            raise RuntimeError(f"WorkerThread({self._name!r}) already reaped")
        self._started = True
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _on_terminal(self, *args: object) -> None:
        """GUI-thread teardown, queued from the worker's terminal signal.

        Runs on the owner thread (guaranteed by the bound-method connection), so
        the join is never a wait-on-itself and the follow-on :attr:`finished`
        handler runs on the GUI thread.
        """
        payload = args[0] if args else None
        self._join_and_reap()
        self.finished.emit(payload)

    def _join_and_reap(self) -> None:
        if self._reaped:
            return
        thread = self._thread
        if thread is not None:
            thread.quit()
            # NEVER wait on our own thread.  In correct operation this slot runs
            # on the GUI thread, so currentThread() != the worker thread and we
            # join; the guard only bites if something mis-queued us onto the
            # worker thread, and then we skip the wait rather than deadlock.
            if QThread.currentThread() is not thread:
                thread.wait(self._join_ms)
        self._reap()

    def _reap(self) -> None:
        """Drop the strong refs so the worker + thread are destroyed on the
        owner thread (their Python wrappers are owned here).  The worker thread
        has already stopped, so this is GUI-side destruction — no ``~QObject`` on
        the worker thread, no stopped ``QThread`` left parented and accumulating.

        The handle then schedules its OWN deletion (``deleteLater`` on the owner
        thread): a caller that keeps one attribute and reassigns it per run (the
        bias-panel pattern) would otherwise leave every finished handle alive as
        a child of the long-lived panel — trading a leaked QThread for a leaked
        handle.  A still-running handle that is never reaped falls back to dying
        with its parent, so nothing is orphaned either way.
        """
        if self._reaped:
            return
        self._reaped = True
        self._worker = None
        self._thread = None
        self.deleteLater()

    def shutdown(self, timeout_ms: Optional[int] = None) -> bool:
        """Tear the worker down for app/panel teardown.

        Returns ``True`` if the worker finished (or was never running), ``False``
        if it could not be joined in time.  For a ``MUST_COMPLETE`` worker a
        ``False`` return also emits :attr:`orphaned` and logs at ERROR — the
        HV-class work is surfaced, never silently abandoned.

        Idempotent and safe to call after normal completion.
        """
        if self._reaped or self._thread is None or not self._thread.isRunning():
            # Never started, already finished, or already reaped: nothing to do.
            if not self._reaped and self._thread is not None:
                self._reap()
            return True

        thread = self._thread
        if QThread.currentThread() is thread:
            # Refuse to wait on ourselves (should never happen for a GUI-thread
            # caller, but the contract is: teardown is never a wait-on-itself).
            return False

        join = self._join_ms if timeout_ms is None else int(timeout_ms)
        if self._kind is ShutdownKind.ABANDON and self._stop_hook is not None:
            # Best-effort cooperative stop (e.g. IVWorker.abort()).  MUST_COMPLETE
            # work is deliberately NOT interrupted — we want it to finish.
            try:
                self._stop_hook()
            except Exception:  # a stop hook must never mask the teardown
                logger.exception("stop_hook raised for %s", self._name)

        thread.quit()
        if thread.wait(join):
            self._reap()
            return True

        # Timed out, still running.
        if self._kind is ShutdownKind.MUST_COMPLETE:
            msg = (
                f"{self._name}: did not finish within {join} ms at shutdown — "
                f"an HV-class operation may be INCOMPLETE and the output state "
                f"is UNVERIFIED."
            )
            logger.error(msg)          # durable surface (survives a dead loop)
            self.orphaned.emit(msg)    # in-GUI surface while the loop is alive
        return False


# --------------------------------------------------------------------------- #
# Owned timer facility                                                         #
#                                                                             #
# A bare QTimer / QTimer.singleShot with no owner outlives the widget it acts #
# on: rebuild the panel / close the window inside the timer window and it      #
# fires on a deleted C++ object (RuntimeError).  These helpers make the owned  #
# form the default so callers stop hand-rolling it.                            #
# --------------------------------------------------------------------------- #

def owned_timer(
    parent: QObject,
    interval_ms: int,
    on_timeout: Callable[[], None],
    *,
    single_shot: bool = False,
) -> QTimer:
    """A ``QTimer`` parented to *parent* (dies with it — never leaks, never
    fires on a destroyed object).  Prefer over a bare ``QTimer`` for any GUI
    timer.  Not started; call ``.start()`` on the returned timer.
    """
    timer = QTimer(parent)
    timer.setInterval(int(interval_ms))
    timer.setSingleShot(single_shot)
    timer.timeout.connect(on_timeout)
    return timer


def owned_single_shot(
    context: QObject,
    timeout_ms: int,
    slot: Callable[[], None],
) -> None:
    """``QTimer.singleShot`` with a **context object**: Qt drops the pending
    invocation when *context* is destroyed, so a fire-and-forget timer can never
    touch a deleted widget.  The owned form of a one-shot timer.
    """
    QTimer.singleShot(int(timeout_ms), context, slot)
