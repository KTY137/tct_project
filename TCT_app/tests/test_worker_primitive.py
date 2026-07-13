"""Headless tests for gui.worker.WorkerThread — the owned worker-lifecycle
primitive (batch 1).

The primitive exists to make the 41a8ab2 bug class impossible: a worker's
terminal signal wired to a context-less closure runs ON the worker thread, so
``thread.wait()`` becomes a wait-on-itself and any widget touch races the GUI
thread.  These tests prove, with a ``QThread.currentThread()`` probe (the same
instrument the original root-cause used):

  * the ``finished`` handler runs on the GUI (owner) thread, never the worker;
  * repeated start/stop reaps every thread — nothing accumulates as a child of
    the owner (the "stopped parented QThreads pile up" debt);
  * ``shutdown`` honours the two kinds — ABANDON drops a stuck worker quietly,
    MUST_COMPLETE surfaces ``orphaned`` + an ERROR log instead of silently
    abandoning an HV-class ramp.

All simulated / pure-Qt — no hardware, no devices import.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.worker import (  # noqa: E402
    DEFAULT_JOIN_MS,
    ShutdownKind,
    WorkerThread,
    owned_single_shot,
    owned_timer,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, seconds: float = 0.1) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.005)


def _pump_until(app, pred, timeout: float = 5.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        app.processEvents()
        time.sleep(0.005)
    return pred()


# --------------------------------------------------------------------------- #
# Test workers                                                                #
# --------------------------------------------------------------------------- #

class _GatedWorker(QObject):
    """Emits ``done(str)`` once its release event is set.  Records the thread it
    ran on so a test can prove it was OFF the GUI thread."""

    done = Signal(str)

    def __init__(self, release: threading.Event, payload: str = "") -> None:
        super().__init__()
        self._release = release
        self._payload = payload
        self.ran_thread: QThread | None = None
        self.aborted = False

    def abort(self) -> None:
        self.aborted = True
        self._release.set()   # cooperative stop → run() unblocks and finishes

    def run(self) -> None:
        self.ran_thread = QThread.currentThread()
        # Bounded so a genuinely stuck test can never wedge the suite forever.
        self._release.wait(timeout=10.0)
        self.done.emit(self._payload)


class _StubbornWorker(QObject):
    """Ignores abort — blocks in run() until its event is released, so a
    shutdown() with a short timeout is guaranteed to time out (the orphan path)."""

    done = Signal(str)

    def __init__(self, release: threading.Event) -> None:
        super().__init__()
        self._release = release

    def abort(self) -> None:
        # deliberately does nothing — used to exercise the timeout branch
        pass

    def run(self) -> None:
        self._release.wait(timeout=10.0)
        self.done.emit("")


class _NoArgWorker(QObject):
    """Terminal signal carries no payload — proves WorkerThread.finished emits
    None for a 0-arg terminal."""

    finished = Signal()

    def run(self) -> None:
        self.finished.emit()


# --------------------------------------------------------------------------- #
# 1. GUI-thread delivery — the core invariant (QThread.currentThread probe)    #
# --------------------------------------------------------------------------- #

def test_finished_delivered_on_owner_thread_not_worker(qapp):
    """done → finished must arrive on the OWNER (GUI) thread, and the worker's
    run() must have executed on a DIFFERENT thread.  This is the exact probe the
    41a8ab2 root-cause used, now guaranteed by the primitive."""
    main_thread = QThread.currentThread()
    release = threading.Event()
    release.set()                       # emit immediately from the worker thread
    worker = _GatedWorker(release, payload="ok")

    handle = WorkerThread(worker, worker.done, name="probe")
    seen = {}

    def _on_finished(payload):
        seen["thread"] = QThread.currentThread()
        seen["payload"] = payload

    handle.finished.connect(_on_finished)
    worker_thread_obj = handle._thread     # grab before reap nulls it
    handle.start()

    assert _pump_until(qapp, lambda: "thread" in seen), "finished never delivered"
    # Delivery landed on the GUI thread...
    assert seen["thread"] == main_thread
    # ...and the worker genuinely ran off-thread (not the GUI thread).
    assert worker.ran_thread is not None
    assert worker.ran_thread != main_thread
    assert worker.ran_thread == worker_thread_obj
    # Payload passed straight through.
    assert seen["payload"] == "ok"
    # Reaped: no lingering thread handle.
    assert handle._thread is None and handle._reaped


def test_zero_arg_terminal_delivers_none(qapp):
    worker = _NoArgWorker()
    handle = WorkerThread(worker, worker.finished, name="noarg")
    seen = {}
    handle.finished.connect(lambda p: seen.setdefault("payload", p))
    handle.start()
    assert _pump_until(qapp, lambda: "payload" in seen)
    assert seen["payload"] is None
    assert handle._thread is None


# --------------------------------------------------------------------------- #
# 2. Reaping — no accumulation of stopped parented QThreads                    #
# --------------------------------------------------------------------------- #

def test_repeated_start_stop_reaps_and_never_accumulates(qapp):
    """25x serial runs: every handle must reap its thread, and NONE of the
    QThreads may end up parented to (accumulating under) the owner — the debt
    the primitive kills.  The handles themselves are children of `owner`; the
    threads must not be."""
    owner = QObject()
    for i in range(25):
        release = threading.Event()
        release.set()
        worker = _GatedWorker(release, payload=str(i))
        handle = WorkerThread(worker, worker.done, name=f"run{i}", parent=owner)
        got = {}
        handle.finished.connect(lambda p, g=got: g.setdefault("p", p))
        handle.start()
        assert _pump_until(qapp, lambda: "p" in got), f"run {i} never finished"
        assert got["p"] == str(i)
        assert handle._thread is None and handle._reaped, f"run {i} not reaped"

    # No QThread ever ended up as a child of the owner (that was the old
    # QThread(self) pattern's leak).  The WorkerThread handles self-schedule
    # deletion on reap; force the pending DeferredDelete and neither the threads
    # NOR the handles remain as children — nothing accumulates over a session.
    qthread_children = [c for c in owner.children() if isinstance(c, QThread)]
    assert qthread_children == [], f"threads accumulated: {qthread_children}"
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert owner.children() == [], (
        f"finished handles accumulated as children: {owner.children()}"
    )


def test_handle_self_deletes_after_reap(qapp):
    """The handle schedules its own deletion once reaped, so a caller that keeps
    a single per-run attribute never leaks finished handles."""
    import shiboken6

    release = threading.Event()
    release.set()
    worker = _GatedWorker(release)
    handle = WorkerThread(worker, worker.done, name="self-delete")
    done = {}
    handle.finished.connect(lambda p: done.setdefault("p", p))
    handle.start()
    assert _pump_until(qapp, lambda: "p" in done)
    assert shiboken6.isValid(handle)          # still valid (DeferredDelete pending)
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(handle), "handle was not reaped after completion"


def test_double_start_raises(qapp):
    release = threading.Event()
    release.set()
    worker = _GatedWorker(release)
    handle = WorkerThread(worker, worker.done, name="dbl")
    handle.start()
    with pytest.raises(RuntimeError):
        handle.start()
    assert _pump_until(qapp, lambda: handle._reaped)


# --------------------------------------------------------------------------- #
# 3. shutdown() — the two kinds                                                #
# --------------------------------------------------------------------------- #

def test_shutdown_abandon_times_out_quietly(qapp):
    """ABANDON: a worker that will not stop is dropped (False) with NO orphaned
    signal — best-effort teardown for non-HV work."""
    release = threading.Event()
    worker = _StubbornWorker(release)
    handle = WorkerThread(
        worker, worker.done, kind=ShutdownKind.ABANDON, name="abandon-stuck"
    )
    orphans = []
    handle.orphaned.connect(orphans.append)
    handle.start()
    _pump(qapp, 0.05)   # let run() reach its block

    assert handle.shutdown(timeout_ms=100) is False   # could not join
    assert orphans == [], "ABANDON must not emit orphaned"

    # cleanup: release + let the queued teardown reap it
    release.set()
    assert _pump_until(qapp, lambda: handle._reaped or not handle.is_running())
    _pump(qapp, 0.05)


def test_shutdown_abandon_stop_hook_lets_it_finish(qapp):
    """ABANDON with a stop_hook: shutdown requests the cooperative stop, the
    worker unblocks and joins → True, cleanly reaped."""
    release = threading.Event()
    worker = _GatedWorker(release)
    handle = WorkerThread(
        worker,
        worker.done,
        kind=ShutdownKind.ABANDON,
        stop_hook=worker.abort,
        name="abandon-cooperative",
    )
    handle.start()
    _pump(qapp, 0.05)
    assert handle.shutdown(timeout_ms=2000) is True
    assert worker.aborted is True
    assert handle._thread is None and handle._reaped


def test_shutdown_must_complete_orphans_loudly(qapp, caplog):
    """MUST_COMPLETE: a worker that will not join within the timeout must NOT be
    silently abandoned — it emits `orphaned` and logs at ERROR (Mary rider b:
    an HV ramp-down must never be orphaned in silence)."""
    release = threading.Event()
    worker = _StubbornWorker(release)
    handle = WorkerThread(
        worker,
        worker.done,
        kind=ShutdownKind.MUST_COMPLETE,
        name="hv-ramp",
    )
    orphans = []
    handle.orphaned.connect(orphans.append)
    handle.start()
    _pump(qapp, 0.05)

    with caplog.at_level(logging.ERROR, logger="gui.worker"):
        result = handle.shutdown(timeout_ms=100)

    assert result is False
    assert len(orphans) == 1, "MUST_COMPLETE must surface orphaned"
    assert "hv-ramp" in orphans[0]
    assert any("hv-ramp" in r.message and r.levelno == logging.ERROR
               for r in caplog.records), "no ERROR log for the orphaned HV work"

    # cleanup
    release.set()
    assert _pump_until(qapp, lambda: handle._reaped or not handle.is_running())
    _pump(qapp, 0.05)


def test_shutdown_after_completion_is_true_and_idempotent(qapp):
    release = threading.Event()
    release.set()
    worker = _GatedWorker(release)
    handle = WorkerThread(
        worker, worker.done, kind=ShutdownKind.MUST_COMPLETE, name="done-already"
    )
    handle.finished.connect(lambda p: None)
    handle.start()
    assert _pump_until(qapp, lambda: handle._reaped)
    assert handle.shutdown() is True
    assert handle.shutdown() is True   # idempotent


def test_default_join_matches_house_constant():
    # The primitive replaces the scattered 2000/3000 ms magic numbers.
    assert DEFAULT_JOIN_MS == 2000


# --------------------------------------------------------------------------- #
# 4. Owned timer facility                                                      #
# --------------------------------------------------------------------------- #

def test_owned_timer_is_parented_and_fires(qapp):
    parent = QObject()
    ticks = []
    timer = owned_timer(parent, 10, lambda: ticks.append(1))
    assert timer.parent() is parent
    timer.start()
    assert _pump_until(qapp, lambda: len(ticks) >= 1)


def test_owned_single_shot_cancelled_when_context_dies(qapp):
    """The context-object overload must drop the pending call when its context
    is destroyed — a fire-and-forget timer can never touch a dead widget (the
    flash_button hazard)."""
    fired = []
    ctx = QObject()
    owned_single_shot(ctx, 80, lambda: fired.append(1))
    ctx.deleteLater()
    del ctx
    # DeferredDelete is NOT processed by processEvents() alone — force it so the
    # context is genuinely destroyed (as a panel rebuild / window close would),
    # then let the 80 ms window elapse.
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _pump(qapp, 0.25)     # well past the 80 ms window
    assert fired == [], "single-shot fired after its context was destroyed"


def test_owned_single_shot_fires_for_live_context(qapp):
    fired = []
    ctx = QObject()
    owned_single_shot(ctx, 20, lambda: fired.append(1))
    assert _pump_until(qapp, lambda: fired == [1])
