"""
Scan run-control coordinator.

Owns the acquisition run-control glue that used to sit inline in
``tct_gui.TCTMainWindow`` (rule 5 — the main window is a composition root, not a
God object).  The coordinator:

* holds the :class:`ScanController` handle and the shared
  :class:`StateMachine`;
* owns the cross-thread callback bridge (:class:`_ScanBridge`) that marshals
  ``ScanController`` callbacks — fired from the daemon scan thread — onto the Qt
  main thread via queued signal/slot delivery;
* owns the ``_plan_run_active`` dual-dispatch flag that routes bridge signals to
  either the Scan Viewer or the Scan Planner panel;
* exposes **methods** the GUI connects panel signals *into* (start scan / plan /
  z-focus / voltage scan, pause/resume, arm-HV, abort) and **Qt signals** the GUI
  connects panel slots (and dialogs) *out of*.

The coordinator never touches a widget directly — every user-facing effect is a
Qt signal the composition root wires to a panel slot, a ``QMessageBox`` shim, or
the status bar.  This keeps the safety-critical run-control logic testable
headless and off the widget layer.

Behaviour is byte-identical to the pre-extraction ``tct_gui`` handlers; see the
matching docstrings for the invariants (fail-closed HV arming, pause/resume HV
re-assert, abort-preserves-data, plan-vs-classic dispatch).
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from controller.state_machine import StateMachine, AppState
from controller.scan_controller import (
    ScanController, ScanConfig, ZFocusScanConfig, VoltageScanConfig,
)
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import DangerGate
from gui.status_bus import notify

logger = logging.getLogger(__name__)


class _ScanBridge(QObject):
    """
    Marshals ScanController callbacks (called from background threads) onto
    the Qt main thread via queued signal/slot delivery.  This prevents
    PySide6 from crashing when a scan thread tries to update GUI widgets.
    """
    point_done   = Signal(object)        # ScanResult
    progress     = Signal(int, int)      # done, total
    finished     = Signal()
    error        = Signal(str)
    z_focus_pt   = Signal(float, float)  # z_mm, amplitude_V
    z_focus_done = Signal(float)         # best_z_mm
    vscan_point  = Signal(float, float, float)  # voltage_V, charge_pC, current_A
    manual_pause = Signal(str)           # plan executor ManualPauseStep prompt


class ScanCoordinator(QObject):
    """Run-control coordinator between the GUI panels and the ScanController.

    Public **methods** (connect panel signals here)::

        start_scan(ScanConfig)          (no GUI caller since S2c — kept for
                                         API stability; Planner is the only
                                         raster-start surface)
        start_z_focus(ZFocusScanConfig) ← ScanViewerPanel.z_focus_requested
        start_voltage_scan(VoltageScanConfig)
                                        ← BiasPanel.vscan_requested
        toggle_pause(bool)              ← ScanViewerPanel.pause_requested
        arm_hv()                        ← PlannerPanel.arm_hv_requested
        start_plan(ScanPlan)            ← PlannerPanel.start_plan_requested
        abort()                         ← *.abort_requested
        resume()                        (used by the manual-pause dialog)

    Public **signals** (connect panel slots / dialog shims here)::

        # Scan Viewer (fired for every run — plan or classic)
        point_done(object)              → ScanViewerPanel.on_point_done
        progress(int, int)              → ScanViewerPanel.on_progress
        scan_started()                  → ScanViewerPanel.on_scan_started
        scan_finished()                 → ScanViewerPanel.on_scan_finished
        z_focus_pt(float, float)        → ScanViewerPanel.on_z_focus_pt
        z_focus_done(float)             → ScanViewerPanel.on_z_focus_done
        # bias panel
        vscan_point(float, float, float)→ BiasPanel.on_vscan_point
        # Scan Planner (fired only for a planner-launched run)
        plan_progress(int, int)         → PlannerPanel.on_progress
        plan_error(str)                 → PlannerPanel.on_error
        plan_finished()                 → PlannerPanel.on_finished
        plan_running(bool)              → PlannerPanel.set_running
        hv_armed(bool)                  → PlannerPanel.set_hv_armed
        # composition-root dialog / status shims
        manual_pause(str)               → main-window manual-step dialog
        warn_dialog(str, str)           → QMessageBox.warning(title, text)
        error_dialog(str, str)          → QMessageBox.critical(title, text)
        status_message(str)             → status bar showMessage
    """

    # ── Scan Viewer (every run — plan or classic) ─────────────────────
    point_done   = Signal(object)              # ScanResult
    progress     = Signal(int, int)            # done, total
    scan_started = Signal()
    scan_finished = Signal()
    z_focus_pt   = Signal(float, float)        # z_mm, amplitude_V
    z_focus_done = Signal(float)               # best_z_mm
    # ── bias panel ────────────────────────────────────────────────────
    vscan_point  = Signal(float, float, float)  # voltage_V, charge_pC, current_A
    # ── Scan Planner (plan-run only) ──────────────────────────────────
    plan_progress = Signal(int, int)
    plan_error    = Signal(str)
    plan_finished = Signal()
    plan_running  = Signal(bool)
    hv_armed      = Signal(bool)
    # ── composition-root dialog / status shims ────────────────────────
    manual_pause  = Signal(str)                # forwarded plan manual-step prompt
    warn_dialog   = Signal(str, str)           # (title, message) → warning box
    error_dialog  = Signal(str, str)           # (title, message) → critical box
    status_message = Signal(str)               # → status bar

    def __init__(
        self,
        scanner: ScanController,
        state_machine: StateMachine,
        danger_gate: DangerGate,
        plan_limits_provider: Callable[[], PlanLimits],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._scanner = scanner
        self._sm = state_machine
        self._danger_gate = danger_gate
        self._plan_limits = plan_limits_provider
        # True while the active run was launched from the Scan Planner — gates
        # which panel receives progress/finished/error (see dispatchers below).
        self._plan_run_active = False

        # ── Thread-safe scan callback bridge ──────────────────────────
        # ScanController runs in a daemon threading.Thread; all GUI updates must
        # go through Qt queued signals to avoid cross-thread crashes.  The
        # bridge marshals onto the GUI thread, where these internal slots run and
        # re-emit the coordinator's outward signals to the panels (same thread →
        # direct delivery).
        self._bridge = _ScanBridge()
        self._bridge.point_done.connect(self._on_point_done)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.finished.connect(self._on_finished)
        self._bridge.error.connect(self._on_error)
        self._bridge.vscan_point.connect(self._on_vscan_point)
        self._bridge.z_focus_pt.connect(self._on_z_focus_pt)
        self._bridge.z_focus_done.connect(self._on_z_focus_done)
        self._bridge.manual_pause.connect(self._on_manual_pause)

        self._scanner.on_point_done   = lambda r:       self._bridge.point_done.emit(r)
        self._scanner.on_progress     = lambda d, t:    self._bridge.progress.emit(d, t)
        self._scanner.on_finished     = lambda:         self._bridge.finished.emit()
        self._scanner.on_error        = lambda msg:     self._bridge.error.emit(msg)
        self._scanner.on_vscan_point  = lambda v, c, i: self._bridge.vscan_point.emit(v, c, i)
        self._scanner.on_manual_pause = lambda msg:     self._bridge.manual_pause.emit(msg)

    # ------------------------------------------------------------------ #
    # State                                                              #
    # ------------------------------------------------------------------ #

    @property
    def plan_run_active(self) -> bool:
        """True while a planner-launched run is active (drives the panel's
        running state + gates plan-run dispatch)."""
        return self._plan_run_active

    # ------------------------------------------------------------------ #
    # Bridge dispatchers (GUI thread)                                     #
    # ------------------------------------------------------------------ #

    @Slot(object)
    def _on_point_done(self, result) -> None:
        # Fired for every run (classic or plan); the Scan Viewer renders
        # the live map for both (see design review §b feasibility note).
        self.point_done.emit(result)

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.progress.emit(done, total)
        # Plan runs additionally drive the planner's progress bar — gated so a
        # classic scan never leaks into the planner panel.
        if self._plan_run_active:
            self.plan_progress.emit(done, total)

    @Slot()
    def _on_finished(self) -> None:
        # Classic Scan-panel finish + status is unconditional (byte-identical to
        # the old _on_scan_finished, wired to bridge.finished for every run).
        self.scan_finished.emit()
        self.status_message.emit(f"Scan finished — state: {self._sm.state.name}")
        # Plan dispatch: forward only for a plan run, and clear the flag so later
        # classic scans don't leak into the panel.  The green "Run finished" paint
        # is reserved for a genuinely FINISHED terminal — after an abort / denied
        # confirm / fault the run must not be repainted as a clean finish
        # (on_error already carried the message and the crit styling); just
        # release the panel's running state.
        if self._plan_run_active:
            self._plan_run_active = False
            if self._sm.state is AppState.FINISHED:
                self.plan_finished.emit()
            else:
                self.plan_running.emit(False)

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        # Classic Scan-panel finish + critical dialog is unconditional
        # (byte-identical to the old _on_scan_error, wired for every run).
        self.scan_finished.emit()
        self.error_dialog.emit("Scan Error", msg)
        # Plan runs additionally surface the error in the planner panel — gated.
        if self._plan_run_active:
            self.plan_error.emit(msg)

    @Slot(float, float, float)
    def _on_vscan_point(self, voltage_V: float, charge_pC: float, current_A: float) -> None:
        self.vscan_point.emit(voltage_V, charge_pC, current_A)

    @Slot(float, float)
    def _on_z_focus_pt(self, z_mm: float, amplitude_V: float) -> None:
        self.z_focus_pt.emit(z_mm, amplitude_V)

    @Slot(float)
    def _on_z_focus_done(self, best_z_mm: float) -> None:
        self.z_focus_done.emit(best_z_mm)

    @Slot(str)
    def _on_manual_pause(self, prompt: str) -> None:
        # The plan executor hit a ManualPauseStep; forward the prompt to the
        # composition root, which shows the modal Resume/Abort dialog and calls
        # back into resume() / abort().
        self.manual_pause.emit(prompt)

    # ------------------------------------------------------------------ #
    # Public control interface (connect panel signals here)              #
    # ------------------------------------------------------------------ #

    @Slot(ScanConfig)
    def start_scan(self, cfg: ScanConfig) -> None:
        if not self._sm.can(AppState.RUNNING):
            self.warn_dialog.emit(
                "Cannot Start",
                f"Cannot start scan in state {self._sm.state.name}.\n"
                "Ensure devices are connected and stage is homed.")
            return
        # The ScanController allocates its own run directory + writer per run
        # (see ScanController._begin_run), so no writer is created here.
        try:
            self._scanner.start(cfg)
        except RuntimeError as exc:
            # start() is fail-closed (refuses a 2nd worker while PAUSED/running);
            # surface the refusal instead of painting a running cockpit.  Match
            # start_plan's pattern: emit scan_started only after start() returns.
            self.error_dialog.emit("Scan refused", str(exc))
            return
        self.scan_started.emit()

    @Slot(ZFocusScanConfig)
    def start_z_focus(self, cfg: ZFocusScanConfig) -> None:
        if not self._sm.can(AppState.RUNNING):
            self.warn_dialog.emit(
                "Cannot Start",
                f"Cannot start Z-focus scan in state {self._sm.state.name}.\n"
                "Ensure devices are connected.")
            return
        # Bridge signals are connected once in __init__ — connecting them here
        # leaked a duplicate connection per run.
        try:
            self._scanner.start_z_focus_scan(
                cfg,
                on_point=lambda z, a: self._bridge.z_focus_pt.emit(z, a),
                on_done=lambda z:     self._bridge.z_focus_done.emit(z),
            )
        except RuntimeError as exc:
            # start_z_focus_scan() is fail-closed (refuses a 2nd worker while
            # PAUSED/running); surface the refusal instead of painting a false
            # "running" status for a live motion scan.  Match start_plan/
            # start_scan: emit the running status only after start returns.
            self.error_dialog.emit("Z-focus scan refused", str(exc))
            return
        self.status_message.emit("Z-focus scan running…")

    @Slot(VoltageScanConfig)
    def start_voltage_scan(self, cfg: VoltageScanConfig) -> None:
        if not self._sm.can(AppState.RUNNING):
            self.warn_dialog.emit(
                "Cannot Start",
                f"Cannot start voltage scan in state {self._sm.state.name}.\n"
                "Ensure devices are connected.")
            return
        try:
            self._scanner.start_voltage_scan(cfg)
        except RuntimeError as exc:
            # start_voltage_scan() is fail-closed (refuses a 2nd worker while
            # PAUSED/running); surface the refusal instead of painting a false
            # "running" status for a live HV scan.  Match start_plan/start_scan:
            # emit the running status only after start returns.
            self.error_dialog.emit("Voltage scan refused", str(exc))
            return
        self.status_message.emit("Voltage scan running…")

    @Slot(bool)
    def toggle_pause(self, pause: bool) -> None:
        try:
            if pause:
                self._scanner.pause()
                self.status_message.emit("Scan paused")
            else:
                self._scanner.resume()
                self.status_message.emit("Scan resumed")
        except Exception as exc:
            logger.warning("Pause/resume failed: %s", exc)

    @Slot()
    def arm_hv(self) -> None:
        """Panel Arm-HV (already user-confirmed in the panel's own dialog) →
        controller latch, reflected back so the panel can unlock Start."""
        try:
            self._scanner.arm_hv(True)
            self.hv_armed.emit(True)
        except Exception as exc:
            notify(f"Arm HV failed: {exc}", "error")
            self.hv_armed.emit(False)

    @Slot(object)
    def start_plan(self, plan) -> None:
        if not self._sm.can(AppState.RUNNING):
            # Any refusal un-arms, same as the exception path below — the
            # documented contract is "a refused start never leaves HV armed".
            self._scanner.arm_hv(False)
            self.hv_armed.emit(False)
            self.warn_dialog.emit(
                "Not ready", "Cannot start a plan in the current state.")
            return
        try:
            self._scanner.start_plan(plan, self._plan_limits(), self._danger_gate)
            self._plan_run_active = True
            # The Scan Viewer's run-active state (map clear, Pause/Abort
            # enable, chip, ETA clock) keys off scan_started — a plan run
            # must fire it exactly like a classic start.  Success path only:
            # a refused/raised start must never paint a running cockpit.
            self.scan_started.emit()
        except Exception as exc:
            # A refused start consumes the arm latch (controller side) — keep the
            # panel's Start locked in step.
            self.hv_armed.emit(False)
            self.error_dialog.emit("Plan refused", str(exc))

    @Slot(object, object)
    def execute_plan(self, plan, gate) -> None:
        """Two-step-latch Execute path (design law 5): HV was authorized ONCE by
        the panel's arm latch over the full ArmedEnvelope, so arm HV and start
        the plan gated by the caller-supplied ``ArmedEnvelopeGate`` (which
        auto-approves every live danger provably inside the armed envelope and
        fail-closes anything outside it). Mirrors :meth:`start_plan`'s refuse-
        before-any-state-change discipline; a refusal un-arms so the panel's
        latch stays in step (``hv_armed(False)`` re-locks it)."""
        if not self._sm.can(AppState.RUNNING):
            self._scanner.arm_hv(False)
            self.hv_armed.emit(False)
            self.warn_dialog.emit(
                "Not ready", "Cannot start a plan in the current state.")
            return
        try:
            self._scanner.arm_hv(True)
            self._scanner.start_plan(plan, self._plan_limits(), gate)
            self._plan_run_active = True
            self.scan_started.emit()
        except Exception as exc:
            self.hv_armed.emit(False)
            self.error_dialog.emit("Plan refused", str(exc))

    @Slot()
    def resume(self) -> None:
        """Resume a paused run (used by the manual-step dialog's Resume)."""
        self._scanner.resume()

    @Slot()
    def abort(self) -> None:
        """Abort the running scan/plan (fail-safe: preserves data already taken,
        flushes files, leaves hardware safe — all in ScanController.abort)."""
        self._scanner.abort()
