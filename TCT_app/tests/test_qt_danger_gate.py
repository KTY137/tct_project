"""Headless tests for ``QtDangerGate``.

Carved out of ``test_planner_panel.py`` per S2 Ruling Q4 (staging beat U1.0):
the ``QtDangerGate`` modal is on the roadmap NEVER-migrates list, so these
assertions must survive the QML migration verbatim against the retained QWidget
gate. This is a byte-preserving move — every assertion is identical to the
former planner-panel host; only the imports and the shared ``_app`` helper were
adjusted so the file runs standalone.

Follows the existing gui test idiom: ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()`` helper, no pytest-qt. No real ``QMessageBox`` is
ever shown — ``QtDangerGate._show_dialog`` is stubbed in every test that
exercises it.
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from controller.danger_gate import DangerAction
from gui.qt_danger_gate import QtDangerGate


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# QtDangerGate                                                                 #
# --------------------------------------------------------------------------- #

class _StubGate(QtDangerGate):
    """QtDangerGate with the real QMessageBox swapped for a canned answer."""

    def __init__(self, answer: bool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._answer = answer
        self.shown_actions: list[DangerAction] = []

    def _show_dialog(self, action: DangerAction) -> bool:
        self.shown_actions.append(action)
        return self._answer


def test_qt_danger_gate_confirms_true_on_gui_thread():
    _app()
    gate = _StubGate(True)
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V")
    assert gate.confirm(action) is True
    assert gate.shown_actions == [action]


def test_qt_danger_gate_denies_false_on_gui_thread():
    _app()
    gate = _StubGate(False)
    action = DangerAction(kind="move", summary="Move stage to (1, 2, 0)")
    assert gate.confirm(action) is False


def test_qt_danger_gate_confirm_from_worker_thread():
    _app()
    gate = _StubGate(True)
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    deadline = time.time() + 5.0
    while t.is_alive() and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    t.join(timeout=1.0)

    assert not t.is_alive()
    assert result == [True]
    assert gate.shown_actions == [action]


def test_qt_danger_gate_timeout_denies():
    _app()
    # Nobody pumps the event loop while the worker blocks, so the queued
    # signal is never delivered -> the short timeout must fire and deny.
    gate = _StubGate(True, timeout_s=0.05)
    action = DangerAction(kind="move", summary="Move stage")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=5.0)

    assert not t.is_alive()
    assert result == [False]
    # The dialog was never actually shown — the timeout won the race.
    assert gate.shown_actions == []


def test_qt_danger_gate_no_stray_dialog_after_shutdown():
    """A queued confirm released by shutdown() must NOT pop a dialog when the
    event loop later delivers the stale request (reviewer-reproduced BUG:
    stray modal during window teardown)."""
    _app()
    gate = _StubGate(True)
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    # Let the worker post its queued request, then shut down BEFORE the GUI
    # thread pumps events (mimics teardown racing an in-flight confirm).
    time.sleep(0.1)
    gate.shutdown()
    t.join(timeout=5.0)
    assert not t.is_alive()
    assert result == [False]          # released as deny
    # NOW deliver the stale queued request — no dialog may appear.
    deadline = time.time() + 0.5
    while time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert gate.shown_actions == []


def test_qt_danger_gate_timeout_then_pump_shows_no_stray_dialog():
    """Same stray-request guard for the timeout path: after a confirm times
    out (deny), pumping the loop must not show the now-orphaned dialog."""
    _app()
    gate = _StubGate(True, timeout_s=0.05)
    action = DangerAction(kind="move", summary="Move stage")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive() and result == [False]
    deadline = time.time() + 0.5
    while time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert gate.shown_actions == []


def test_qt_danger_gate_dialog_exception_releases_worker_as_deny():
    """If the dialog slot raises, the blocked worker must be released
    immediately as deny — not stall until the timeout."""
    _app()

    class _RaisingGate(QtDangerGate):
        def _show_dialog(self, action: DangerAction) -> bool:
            raise RuntimeError("dialog exploded")

    gate = _RaisingGate(timeout_s=5.0)   # long timeout: release must NOT need it
    action = DangerAction(kind="hv_ramp", summary="Ramp")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t0 = time.time()
    deadline = time.time() + 5.0
    while t.is_alive() and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    t.join(timeout=1.0)
    assert not t.is_alive()
    assert result == [False]
    assert time.time() - t0 < 4.0     # released by the finally, not the timeout


def test_qt_danger_gate_shutdown_denies_pending_and_future():
    _app()
    gate = _StubGate(True, timeout_s=5.0)
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    time.sleep(0.05)   # let the worker thread register its pending confirm
    gate.shutdown()
    t.join(timeout=5.0)

    assert not t.is_alive()
    assert result == [False]

    # Future calls are refused outright too, even on the GUI thread.
    assert gate.confirm(action) is False


def test_qt_danger_gate_abort_denies_pending_but_stays_usable():
    _app()
    gate = _StubGate(True, timeout_s=5.0)
    action = DangerAction(kind="move", summary="Move stage")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    time.sleep(0.05)
    gate.abort()
    t.join(timeout=5.0)

    assert not t.is_alive()
    assert result == [False]

    # abort() does not permanently close the gate — a later confirm on the
    # GUI thread still shows the (stubbed) dialog and can succeed.
    assert gate.confirm(action) is True
