"""``RunStateViewModel`` — the read-only run/scan-state seam for the QML shell.

Sibling of :class:`gui.scope_viewmodel.ScopeViewModel`. Per
``docs/design/run_state_facade.md``, the QML Scan Viewer must bind to scan/run
state through a **view-model QObject** (Q_PROPERTY + one ``changed`` NOTIFY)
rather than reaching into ``ScanController``/``StateMachine``. This is that
seam: a **read-only mirror** of already-owned run state (machine state,
running/paused/terminal flags, progress, current point, elapsed, last error,
run metadata), exposed as NOTIFY-able Qt properties.

The single most important property of this class (safety-critical, encoded as a
test): it holds **NO** reference to ``ScanController``/``StateMachine``/
``ScanCoordinator`` and exposes **NO** callable that starts/pauses/stops/aborts
a run. It is *fed* values on the GUI thread; it cannot *reach* anything. That is
what structurally guarantees the read/command boundary — QML physically has no
path from ``runState`` to a run-control command (hardware safety rule 2). Run
control stays exactly where it is (the Scan Planner arms/starts via the
``DangerGate``; the Scan Viewer's Pause/Abort emit to ``ScanCoordinator``).

Threading: mutated on the GUI thread only — the poll feed (``update``) rides the
composition root's shared 1 Hz ``_light_timer``; the signal feeds (``on_*``)
arrive on ``ScanCoordinator`` signals already marshaled from the worker thread
onto the GUI thread by ``_ScanBridge``. Owns no thread, no timer, no lock, no
device handle — identical discipline to ``ScopeViewModel``.

ETA note (superseded by Adam's Q1 ruling, ``docs/design/u1_staging.md`` §4.3/
§8, 2026-07-15 — supersedes the letter of the 2026-07-11 placeholder ruling
while honoring its intent of "no competing estimate"): ``etaText`` is now the
rate-derived estimate ported 1:1 from ``ScanViewerPanel._compute_eta`` (the
classic panel's own copy is deleted in the same beat that lands this move —
there is exactly ONE ETA derivation after U1.2). The refinement of sourcing
ETA from the core ``controller/plan_estimate.py`` instead (so the Planner's
pre-run estimate and the live ETA agree) stays queued, unchanged — not built
here. ``elapsedText`` is a measured wall-clock elapsed (not an estimate) and
is derived here, unchanged by this move.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Property, QObject, Signal

# AppState members whose name marks a run as over. Keyed by ``.name`` string so
# the view-model needs no ``controller`` import — it stays a pure mirror with no
# reference through which a command could be issued (the §1 boundary).
_TERMINAL_STATES = frozenset({"FINISHED", "ABORTED", "ERROR"})

_IDLE_POINT_TEXT = "x=-- y=-- z=--"


class RunStateViewModel(QObject):
    """Read-only Qt-property mirror of scan/run state for the QML Scan Viewer."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None, *, clock=time.monotonic) -> None:
        super().__init__(parent)
        self._clock = clock              # injectable for deterministic tests
        self._state_name = "DISCONNECTED"
        self._running = False
        self._paused = False
        self._terminal = False
        self._active = False             # a run is in progress (running or paused)
        self._done = 0
        self._total = 0
        self._point = None               # last ScanPoint (or None)
        self._error_text = ""
        self._scan_type = ""
        self._run_path = ""
        self._t0: float | None = None    # monotonic start (set on on_scan_started)
        self._elapsed_frozen: float | None = None  # elapsed captured at finish

    # -- POLL feed (1 Hz, GUI thread — plain method, NOT a @Slot) ---------- #
    def update(self, *, state=None, scan_type=None, run_path=None) -> None:
        """Snapshot machine state + run metadata from the composition root's
        cached-state poll. Mirrors ``ScopeViewModel.update``: kwargs are
        already-read values (no I/O). ``state`` is an ``AppState`` (keyed by its
        ``.name``); ``scan_type``/``run_path`` are strings. Omitted kwargs keep
        the previous value."""
        if state is not None:
            name = getattr(state, "name", str(state))
            self._state_name = name
            self._running = (name == "RUNNING")
            self._paused = (name == "PAUSED")
            self._active = self._running or self._paused
            self._terminal = name in _TERMINAL_STATES
        if scan_type is not None:
            self._scan_type = str(scan_type)
        if run_path is not None:
            self._run_path = str(run_path)
        self.changed.emit()

    # -- SIGNAL feed (existing coordinator signals, GUI thread) ------------ #
    def on_scan_started(self) -> None:
        """``ScanCoordinator.scan_started`` — a run has begun. Reset per-run
        state and mark active immediately (the poll's ``sm.state`` read can lag
        the transition by up to one 1 Hz tick — scanType/running are advisory
        at run start)."""
        self._done = 0
        self._total = 0
        self._point = None
        self._error_text = ""
        self._active = True
        self._t0 = self._clock()
        self._elapsed_frozen = None
        self.changed.emit()

    def on_progress(self, done, total) -> None:
        """``ScanCoordinator.progress`` — points completed / total."""
        self._done = int(done)
        self._total = int(total)
        self.changed.emit()

    def on_point_done(self, result) -> None:
        """``ScanCoordinator.point_done`` — a ``ScanResult`` for the last point."""
        self._point = getattr(result, "point", None)
        self.changed.emit()

    def on_scan_finished(self) -> None:
        """``ScanCoordinator.scan_finished`` — clear active but retain the final
        counts (the finished cockpit still shows the last progress) and freeze
        the elapsed readout."""
        self._active = False
        self._elapsed_frozen = self._elapsed_s()
        self.changed.emit()

    def on_error(self, title, message) -> None:
        """``ScanCoordinator.error_dialog`` — last error message. (May carry a
        pre-flight "Plan refused" refusal — documented, still run-state
        relevant.)"""
        self._error_text = str(message)
        self.changed.emit()

    # -- internal (presentation derivation only — no run-control policy) --- #
    def _elapsed_s(self) -> float:
        if self._elapsed_frozen is not None:
            return self._elapsed_frozen
        if self._t0 is None:
            return 0.0
        return self._clock() - self._t0

    @staticmethod
    def _format_duration(seconds: float | None) -> str:
        """Port of ``ScanViewerPanel._format_duration`` — one number both
        surfaces can later agree on. Pure presentation."""
        if seconds is None:
            return "--"
        seconds = max(0.0, float(seconds))
        if seconds < 60:
            return f"{seconds:.0f} s"
        if seconds < 3600:
            return f"{seconds / 60:.1f} min"
        return f"{seconds / 3600:.1f} h"

    def _compute_eta(self) -> str:
        """Port of ``ScanViewerPanel._compute_eta`` (Adam's Q1 ruling,
        ``docs/design/u1_staging.md`` §4.3/§8) — the classic panel's copy is
        deleted in the same beat, so this is the ONE eta derivation. Rate
        derived from observed progress/elapsed; sourcing from the core
        ``plan_estimate.py`` instead stays a queued refinement, not built
        here."""
        if self._done <= 0 or self._total <= 0:
            return "--"
        elapsed = self._elapsed_s()
        if elapsed <= 0:
            return "--"
        rate = self._done / elapsed
        if rate <= 0:
            return "--"
        remaining = max(0, self._total - self._done)
        return self._format_duration(remaining / rate)

    # -- QML-facing read-only properties ----------------------------------- #
    @Property(str, notify=changed)
    def stateName(self) -> str:
        return self._state_name

    @Property(bool, notify=changed)
    def running(self) -> bool:
        return self._running

    @Property(bool, notify=changed)
    def paused(self) -> bool:
        return self._paused

    @Property(bool, notify=changed)
    def active(self) -> bool:
        return self._active

    @Property(bool, notify=changed)
    def terminal(self) -> bool:
        return self._terminal

    @Property(int, notify=changed)
    def done(self) -> int:
        return self._done

    @Property(int, notify=changed)
    def total(self) -> int:
        return self._total

    @Property(float, notify=changed)
    def progressFraction(self) -> float:
        if self._total <= 0:
            return 0.0
        return float(self._done) / float(self._total)

    @Property(str, notify=changed)
    def pointText(self) -> str:
        p = self._point
        if p is None:
            return _IDLE_POINT_TEXT
        return f"x={p.x_mm:.3f} y={p.y_mm:.3f} z={p.z_mm:.3f}"

    @Property(str, notify=changed)
    def etaText(self) -> str:
        return self._compute_eta()

    @Property(str, notify=changed)
    def elapsedText(self) -> str:
        return self._format_duration(self._elapsed_s())

    @Property(str, notify=changed)
    def errorText(self) -> str:
        return self._error_text

    @Property(str, notify=changed)
    def scanType(self) -> str:
        return self._scan_type

    @Property(str, notify=changed)
    def runPath(self) -> str:
        return self._run_path

    @Property(str, notify=changed)
    def statusText(self) -> str:
        """Compact one-line summary, e.g. ``"Running 128/400"``."""
        if self._running:
            label = "Running"
        elif self._paused:
            label = "Paused"
        else:
            label = self._state_name.title()
        if self._total > 0:
            return f"{label} {self._done}/{self._total}"
        return label
