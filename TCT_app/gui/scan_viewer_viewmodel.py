"""``ScanViewerViewModel`` — viewer-local read-only state for the Scan Viewer
panel (U1.2, ``docs/design/u1_staging.md`` §4.3).

Composes the existing :class:`~gui.run_state_viewmodel.RunStateViewModel` as
a ``run`` sub-view-model rather than re-deriving run state — progress, ETA,
elapsed, active/terminal flags, and the last scan-result point text all have
exactly ONE home (``RunStateViewModel``); this class never forks that
derivation. QML's later ``ScanViewer.qml`` binds ``viewer.run.progressFraction``
etc. directly through the constant ``run`` property.

This class owns only the state genuinely specific to the Scan Viewer panel
that ``RunStateViewModel`` does not (and should not) model:

* **Tile staleness** (law 4/8 — "0/0"/"--" painted crisp-fresh is a claim the
  panel cannot back): ``progressStale``/``etaStale``/``pointStale`` are True
  the instant a run is armed and clear only once a real feed lands.
* **Current-position text** (``currentPositionText``) — a *live position*
  readout fed by BOTH scan-result points (``on_point_done``) and a live
  motor-position feed (``set_current_position``). This is deliberately a
  second text mirror, not a duplicate of ``run.pointText``: ``run.pointText``
  mirrors only the last *scan-result* point (data-taking events), while this
  mirrors "the last known position from either source", exactly matching the
  single visual tile the classic panel painted from two feeds.
* **Manual-pause text** (``manualPauseMessage``).
* **The Z-focus live curve data model** — point accumulation
  (``on_z_focus_pt``), reset-on-start-of-a-new-focus-run
  (``reset_z_focus_curve``), and the best-Z summary/header-chip text
  (``on_z_focus_done`` → ``bestZSummaryText``/``bestZDetailText``). The
  Apply-button raw value, the pyqtgraph marker, and the ``Best Z: ...`` detail
  label stay panel-local presentation (``gui/scan_viewer_panel.py``) — they
  are not "run state" and the S2 residue tests pin them there directly.
* **Open-in-analysis eligibility** (``openInAnalysisEligible``) and the
  last-run-path mirror (``lastRunPath``) that feeds it.

  Deviation from the §4.3 wording ("terminal AND runPath"): eligibility here
  is ``(not run.active) AND lastRunPath`` rather than ``run.terminal AND
  lastRunPath``. ``run.terminal`` is fed only by ``RunStateViewModel.update()``
  (the composition root's 1 Hz poll) — a feed path this panel-constructed VM
  does not receive in U1 (VM lifetime is panel-owned this stage; wiring the
  poll is a later port-stage concern, and widening ``run_state_viewmodel.py``
  beyond the Q1 ETA move is out of this beat's lock). ``run.active`` IS fed
  by the same events this VM already forwards (``on_scan_started``/
  ``on_scan_finished``), so its complement is available with zero latency and
  is behaviourally identical to the legacy panel's own ``not self._run_active``
  gate for every case the reclaimed tests pin.

Boundary (identical to ``RunStateViewModel`` — see ``docs/design/
run_state_facade.md`` §1): holds NO ``ScanController``/``StateMachine``/
``ScanCoordinator``/``DangerGate`` reference and exposes NO callable that
starts/pauses/stops/resumes/aborts/arms anything. Pause/Abort/Z-focus-start/
apply-best-z/open-in-analysis stay command *signals* on the panel
(constraint 3) — this view-model is *fed*, it never *reaches*. Owns no timer,
no thread (mirrors ``RunStateViewModel``'s own discipline).

Feed surface (plain methods, GUI-thread only — called by the panel with
values it already receives from ``ScanCoordinator``, never new I/O):
``on_scan_started/on_progress/on_point_done/on_scan_finished/on_error``
(forwarded into ``self.run`` plus this class's own viewer-local handling),
``set_current_position``, ``set_last_run_path``, ``on_manual_pause``,
``on_z_focus_pt``, ``on_z_focus_done``, ``reset_z_focus_curve``.

VM lifetime (U1 rule, ``docs/design/u1_staging.md`` §1.1): panel-constructed
(``ScanViewerPanel`` builds and owns this VM); composition-root construction +
QML context-property registration is a later port-stage concern.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Property, QObject, Signal

from gui.run_state_viewmodel import RunStateViewModel

_IDLE_POSITION_TEXT = "x=-- y=-- z=--"


class ScanViewerViewModel(QObject):
    """Viewer-local read-only Qt-property state, composing
    ``RunStateViewModel`` as its ``run`` sub-view-model (one run-state
    derivation, never a fork)."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None, *, clock=time.monotonic) -> None:
        super().__init__(parent)
        self._run = RunStateViewModel(parent=self, clock=clock)

        self._progress_stale = False
        self._eta_stale = False
        self._point_stale = False
        self._position_text = _IDLE_POSITION_TEXT

        self._manual_pause_message = ""

        self._zf_z: list[float] = []
        self._zf_a: list[float] = []
        self._best_z_summary = ""
        self._best_z_detail = ""

        self._last_run_path: str | None = None

    # -- SIGNAL feed (existing coordinator signals, forwarded into `run`) -- #
    def on_scan_started(self) -> None:
        self.run.on_scan_started()
        self._progress_stale = True
        self._eta_stale = True
        self._point_stale = True
        self._position_text = _IDLE_POSITION_TEXT
        # Invalidate the previous run's handoff path — a run that never
        # publishes a fresh path (e.g. aborted before the writer opened)
        # must never re-offer the *prior* run's file on finish.
        self._last_run_path = None
        self.changed.emit()

    def on_progress(self, done, total) -> None:
        self.run.on_progress(done, total)
        # Matches the legacy panel gate exactly: the progress tile only
        # de-stales while a run is active.
        if self.run.active:
            self._progress_stale = False
        if self.run.etaText != "--":
            self._eta_stale = False
        self.changed.emit()

    def on_point_done(self, result) -> None:
        self.run.on_point_done(result)
        point = getattr(result, "point", None)
        if point is not None:
            self._position_text = (
                f"x={point.x_mm:.3f} y={point.y_mm:.3f} z={point.z_mm:.3f}")
        if self.run.active:
            self._point_stale = False
        self.changed.emit()

    def on_scan_finished(self) -> None:
        self.run.on_scan_finished()
        self.changed.emit()

    def on_error(self, title, message) -> None:
        self.run.on_error(title, message)
        self.changed.emit()

    # -- viewer-local feeds (NOT part of run state) ------------------------ #
    def set_current_position(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        self._position_text = f"x={x_mm:.3f} y={y_mm:.3f} z={z_mm:.3f}"
        if self.run.active:
            self._point_stale = False
        self.changed.emit()

    def set_last_run_path(self, path: str | None) -> None:
        self._last_run_path = path
        self.changed.emit()

    def on_manual_pause(self, message: str) -> None:
        self._manual_pause_message = str(message)
        self.changed.emit()

    def on_z_focus_pt(self, z_mm: float, amplitude_V: float) -> None:
        self._zf_z.append(float(z_mm))
        self._zf_a.append(float(amplitude_V))
        self.changed.emit()

    def on_z_focus_done(self, best_z_mm: float, mode: str = "edge_scan") -> None:
        mode_label = "edge scan" if mode == "edge_scan" else "amplitude"
        self._best_z_summary = f"Best Z {float(best_z_mm):.3f} mm"
        self._best_z_detail = (
            f"from {mode_label} — Apply to Planner stages it, never moves the motor")
        self.changed.emit()

    def reset_z_focus_curve(self) -> None:
        """A fresh "Find focus" run must not keep showing the previous run's
        curve (fed by the panel from its Find-focus click, alongside its own
        stale-result Apply-button reset — see ``gui/scan_viewer_panel.py``
        ``_emit_z_focus``)."""
        self._zf_z = []
        self._zf_a = []
        self.changed.emit()

    # -- QML-facing read-only properties ------------------------------------ #
    @Property(QObject, constant=True)
    def run(self) -> RunStateViewModel:
        return self._run

    @Property(bool, notify=changed)
    def progressStale(self) -> bool:
        return self._progress_stale

    @Property(bool, notify=changed)
    def etaStale(self) -> bool:
        return self._eta_stale

    @Property(bool, notify=changed)
    def pointStale(self) -> bool:
        return self._point_stale

    @Property(str, notify=changed)
    def currentPositionText(self) -> str:
        return self._position_text

    @Property(str, notify=changed)
    def manualPauseMessage(self) -> str:
        return self._manual_pause_message

    @Property(list, notify=changed)
    def zFocusZ(self) -> list:
        return list(self._zf_z)

    @Property(list, notify=changed)
    def zFocusA(self) -> list:
        return list(self._zf_a)

    @Property(str, notify=changed)
    def bestZSummaryText(self) -> str:
        return self._best_z_summary

    @Property(str, notify=changed)
    def bestZDetailText(self) -> str:
        return self._best_z_detail

    @Property(str, notify=changed)
    def lastRunPath(self) -> str:
        return self._last_run_path or ""

    @Property(bool, notify=changed)
    def openInAnalysisEligible(self) -> bool:
        """``NOT run.active AND lastRunPath`` — see the module docstring's
        "Deviation from the §4.3 wording" note for why this reads ``active``
        rather than ``terminal``."""
        return bool((not self.run.active) and self._last_run_path)
