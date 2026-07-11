"""GUI-thread watchdog: the DYNAMIC enforcement half of the three-layer law
(Kaya's architecture ratification, 2026-07-11 — UI / fast Python backend /
driver, and **compute or blocking I/O must never run on the GUI thread**; see
``docs/research/qml_hybrid_architecture.md`` §9, R6, and the KDAB
``UiWatchDog`` prior art it cites).

Founding case: the Scan Routine Planner's point estimate
(``controller.plan_estimate.estimate_plan``) used to run *synchronously* in
``PlannerPanel._recompute_estimate()`` on the GUI thread. For a large plan
(hundreds of thousands of leaf visits) that walk takes over a second of pure
Python — during which the whole window, including its own responsiveness
probes, is frozen solid. ``tests/test_layer_contracts.py`` (the STATIC half)
cannot catch this: ``estimate_plan`` lives in the *correct* layer
(``controller/``), so no import is wrong — the bug is purely "right layer,
wrong thread." Only a runtime responsiveness probe catches that class of bug,
which is what this file is.

Design: install a **10 ms heartbeat QTimer** on the GUI thread, pump the event
loop while a **representative heavy workload** runs (here: a real
``PlannerPanel`` recomputing the estimate for a plan large enough that the old
synchronous path visibly stalls — see the module-level benchmark note below),
and assert the heartbeat never goes quiet for longer than a pragmatic bound.
Manual proof this test would have FAILED against the old synchronous path
(temporarily replacing the trigger with a direct, on-GUI-thread
``estimate_plan(plan)`` call, run once during this task and not committed —
see the task report): heartbeat gap peaked at **~1.31 s** for the same
500x500-point plan that the fixed off-thread path keeps under ~35 ms. That
sabotage run is not part of this file; only the passing, off-thread-path
assertion is.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# Pragmatic bound, not a tight one: Windows CI scheduling jitter is real, and
# the point of this test is to catch a multi-hundred-ms-to-second GUI stall
# (the historic planner freeze), not to police single-digit-ms scheduling
# noise. The fixed off-thread path measures ~30-40 ms on this machine (see the
# module docstring); the OLD synchronous path measured ~1.3 s on the same
# workload -- three orders of magnitude apart, so this bound has wide margin
# on both sides without being flaky.
_MAX_HEARTBEAT_GAP_S = 0.5
_HEARTBEAT_INTERVAL_MS = 10
_WORKLOAD_TIMEOUT_S = 20.0


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Heartbeat:
    """A QTimer ticking on the GUI thread; records the wall-clock gap between
    consecutive ticks. A blocked GUI thread cannot deliver ANY Qt timer event
    (Qt only dispatches ``timeout`` from inside a pumped event loop), so a
    synchronous compute stall shows up directly as one abnormally large gap
    between the tick just before the stall and the tick right after it
    returns -- exactly the signal this class exists to catch."""

    def __init__(self, interval_ms: int = _HEARTBEAT_INTERVAL_MS) -> None:
        self.ticks: list[float] = []
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_tick)

    def _on_tick(self) -> None:
        self.ticks.append(time.monotonic())

    def start(self) -> None:
        self.ticks.clear()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def max_gap(self) -> float:
        if len(self.ticks) < 2:
            return 0.0
        return max(b - a for a, b in zip(self.ticks, self.ticks[1:]))


def _pump_while(app: QApplication, predicate, timeout_s: float) -> bool:
    """Pump the event loop until *predicate()* is true or *timeout_s* elapses.
    Returns whether the predicate was satisfied. The sleep granularity (5 ms)
    is deliberately coarser than the 10 ms heartbeat interval so this driving
    loop itself never becomes the GIL-contention bottleneck it is trying to
    measure around."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _pump_for(app: QApplication, seconds: float) -> None:
    """Unconditionally pump for a fixed duration (teardown flush -- lets a
    queued thread-quit/deleteLater actually land; same idiom as the
    ``_pump()`` helper other panel test files use)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


# --------------------------------------------------------------------------- #
# Workload registry -- a small seam so a future workload (e.g. a live         #
# simulated-acquire loop) can be added without touching the test body.        #
# Each factory returns (setup, trigger, is_done, teardown):                   #
#   setup()    -> workload state (e.g. the panel)                            #
#   trigger(state)   -> kick off the heavy compute (must return promptly)     #
#   is_done(state)   -> True once the result has landed back on the GUI thread#
#   teardown(state)  -> release any worker thread / resources                 #
# --------------------------------------------------------------------------- #

def _planner_huge_estimate_workload():
    """500x500 stage grid, acquire+save per point = 500,000 leaf visits (a
    ~1.3 s pure-Python walk stand-alone; see the manual benchmark in this
    task's report) -- the historic Scan Planner stall case, driven through the
    REAL ``PlannerPanel._recompute_estimate()`` path (not a stand-in)."""
    from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
    from gui.planner_panel import PlannerPanel

    def setup():
        acq = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={"n_averages": 4})
        save = ActionBlock(action=ActionType.SAVE_POINT, params={})
        y = LoopBlock(axis=Axis.STAGE_Y, start=0.0, stop=49.9, step=0.1,
                      children=[acq, save])
        x = LoopBlock(axis=Axis.STAGE_X, start=0.0, stop=49.9, step=0.1,
                      children=[y])
        plan = ScanPlan(name="watchdog_huge", root=[x])

        panel = PlannerPanel()
        panel._plan = plan
        panel._last_estimate = None
        panel._last_estimate_key = None
        return panel

    def trigger(panel):
        panel._recompute_estimate()   # dispatches off-thread: 500k > threshold

    def is_done(panel):
        return panel._chip_points.text() not in ("Estimating...", "—", "")

    def teardown(panel):
        panel.shutdown()

    return setup, trigger, is_done, teardown


def _planner_sync_boundary_workload():
    """158x158 stage grid, acquire+save per point = 49,928 leaf visits -- just
    UNDER ``PlannerPanel._estimate_async_threshold`` (50,000) -- so this stays
    on the SYNCHRONOUS estimate path *by design* (small/medium plans compute
    inline for a snappier round-trip than a worker round-trip would give
    them; the threshold exists to draw that line). This is not the bug being
    guarded against above -- it is the sync-path boundary itself: a
    just-under-threshold plan measured ~85 ms stand-alone on this machine (see
    this task's report), 2-3x on a slower one, which creeps toward but stays
    comfortably under the heartbeat bound. Pins that boundary so a future
    threshold change or an ``estimate_plan`` slowdown cannot silently erode it
    unnoticed (Mary S1 review nit, landed same beat as the huge-estimate
    workload above)."""
    from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
    from gui.planner_panel import PlannerPanel

    def setup():
        acq = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={"n_averages": 4})
        save = ActionBlock(action=ActionType.SAVE_POINT, params={})
        y = LoopBlock(axis=Axis.STAGE_Y, start=0.0, stop=15.7, step=0.1,
                      children=[acq, save])
        x = LoopBlock(axis=Axis.STAGE_X, start=0.0, stop=15.7, step=0.1,
                      children=[y])
        plan = ScanPlan(name="watchdog_sync_boundary", root=[x])

        panel = PlannerPanel()
        panel._plan = plan
        panel._last_estimate = None
        panel._last_estimate_key = None
        return panel

    def trigger(panel):
        # leaf_visits (49,928) <= threshold (50,000) -> stays on the SYNC
        # path by design; this call is expected to block briefly (~85 ms) on
        # the GUI thread itself -- that is the boundary this workload pins.
        panel._recompute_estimate()

    def is_done(panel):
        return panel._chip_points.text() not in ("Estimating...", "—", "")

    def teardown(panel):
        panel.shutdown()

    return setup, trigger, is_done, teardown


_WORKLOADS = {
    "planner_huge_estimate": _planner_huge_estimate_workload,
    "planner_sync_boundary": _planner_sync_boundary_workload,
}


# --------------------------------------------------------------------------- #
# The watchdog test                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("workload_name", sorted(_WORKLOADS))
def test_gui_heartbeat_survives_heavy_workload(workload_name):
    """PINS THE THREE-LAYER LAW: compute must never block the GUI thread.

    Founding case: the Scan Planner's point estimate used to run synchronously
    on the GUI thread and stalled the window on a large plan (see this file's
    module docstring). This test drives that exact workload through the real
    panel and asserts the GUI-thread heartbeat never goes quiet for longer
    than a pragmatic bound. It is a REGRESSION GATE for the off-thread fix in
    ``gui/planner_panel.py`` (``_EstimateWorker`` / ``_queue_estimate``): if
    the estimate call is ever moved back onto the GUI thread (directly or via
    a non-queued connection), this test fails.
    """
    app = _app()
    setup, trigger, is_done, teardown = _WORKLOADS[workload_name]()
    state = setup()
    heartbeat = _Heartbeat()
    try:
        heartbeat.start()
        # A few warm-up ticks before the workload starts, so max_gap() has a
        # real baseline interval to compare the workload period against.
        _pump_while(app, lambda: len(heartbeat.ticks) >= 3, timeout_s=1.0)

        trigger(state)   # must return promptly -- the compute itself is off-thread

        finished = _pump_while(app, lambda: is_done(state), timeout_s=_WORKLOAD_TIMEOUT_S)
        assert finished, (
            f"workload {workload_name!r} did not complete within "
            f"{_WORKLOAD_TIMEOUT_S}s -- widen the timeout or shrink the workload"
        )

        gap = heartbeat.max_gap()
        assert gap < _MAX_HEARTBEAT_GAP_S, (
            f"GUI-thread heartbeat stalled {gap:.3f}s under {workload_name!r} -- "
            "compute leaked onto the GUI thread (three-layer law violation); "
            f"bound is {_MAX_HEARTBEAT_GAP_S}s"
        )
        assert len(heartbeat.ticks) > 3, "heartbeat never advanced during the workload"
    finally:
        heartbeat.stop()
        teardown(state)
        _pump_for(app, 0.2)
