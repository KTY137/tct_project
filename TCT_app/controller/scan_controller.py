"""
TCT scan controller.

Drives the full automated scan loop:
  move → settle → image → trigger → acquire → analyse → save → update map.

References only abstract base classes (MotorStageBase, IntensityMonitorBase)
so the scan logic is completely decoupled from the hardware backend.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import numpy as np

from controller.state_machine import StateMachine, AppState
from controller.device_manager import DeviceManager
from controller.scan_plan import ScanPlan
from controller.plan_compiler import (
    compile_plan, MoveStep, BiasStep, AcquireStep, SaveStep,
    WaitStep, ManualPauseStep, ReadSlowControlStep,
)
from controller.scan_plan_validator import validate_plan, errors, PlanLimits
from controller.danger_gate import DangerGate, DangerAction
from controller.arm_envelope import ArmedEnvelope, envelope_from_plan
from devices.base import DeviceError
from devices.bias_channel import BiasChannel
from devices.slow_control_base import AlarmStatus
from analysis.waveform_analysis import analyse_waveform, WaveformResult
from analysis.laser_normalization import normalise
from data.hdf5_writer import HDF5Writer

logger = logging.getLogger(__name__)

# Terminal AppState -> HDF5Writer outcome string (see ScanController._end_run).
# Deliberately a plain dict.get() with an "unknown" default in the caller: a
# state machine that somehow ends outside {FINISHED, ABORTED, ERROR} (the
# bounded settle helpers log a warning but never raise) must never be read as
# a clean finish either.
_STATE_OUTCOME = {
    AppState.FINISHED: "finished",
    AppState.ABORTED: "aborted",
    AppState.ERROR: "error",
}


@dataclass
class ScanConfig:
    x_start_mm: float = -1.0
    x_stop_mm:  float =  1.0
    x_step_mm:  float =  0.1
    y_start_mm: float = -1.0
    y_stop_mm:  float =  1.0
    y_step_mm:  float =  0.1
    z_mm:       float =  0.0
    n_averages: int   =  1
    settle_time_s: float = 0.05
    # Bias-supply channel this scan monitors / records for compliance.
    # None = the primary channel (DeviceManager.bias_supply) = historic behavior.
    bias_channel: int | None = None


@dataclass
class ZFocusScanConfig:
    """
    Z-axis focal-point calibration scan.

    Two modes
    ---------
    mode = "amplitude"
        Legacy mode: hold (x_mm, y_mm) fixed and sweep Z.  Best Z = max DUT
        amplitude.  Only reliable when the beam is positioned over the silicon
        bulk (between strip metallisation).

    mode = "edge_scan"  (recommended)
        Physically correct mode per Particulars / standard TCT practice.
        At each Z step the stage scans a short X range crossing a metal/silicon
        edge.  The spatial gradient |dQ/dx| is computed; best Z is where this
        gradient is maximum, i.e. the beam spot is smallest and the edge
        transition is sharpest.  This method works regardless of whether the
        beam is between strips or not, and is insensitive to absolute signal
        level variations.
    """
    mode:       str   = "amplitude"   # "amplitude" | "edge_scan"

    # Common Z-sweep parameters
    x_mm:       float = 0.0    # fixed X position (amplitude mode) or X scan centre
    y_mm:       float = 0.0    # fixed Y position during full scan
    z_start_mm: float = -2.0
    z_stop_mm:  float =  2.0
    z_step_mm:  float =  0.1
    n_averages: int   =  3
    settle_time_s: float = 0.05

    # Edge-scan mode additional parameters
    # A short X scan is taken at each Z step.  Place x_edge_center_mm at the
    # approximate position of a metal/silicon transition (strip edge or pad edge).
    x_edge_center_mm: float = 0.0   # centre of the X scan (at the edge)
    x_edge_range_mm:  float = 0.1   # half-width of X scan (total = 2× this)
    x_edge_step_mm:   float = 0.005 # X step during edge scan (~5 µm)


@dataclass
class VoltageScanConfig:
    """
    Bias voltage scan at a fixed position.

    Steps the Keithley from v_start to v_stop in v_step increments,
    acquiring waveforms at each voltage.  Ramps back to 0 V when done.
    Aborts immediately if the bias supply hits current compliance.
    """
    v_start_V:    float = 0.0
    v_stop_V:     float = -300.0
    v_step_V:     float = -10.0    # sign sets direction
    ramp_step_V:  float = 5.0      # step size during ramp
    ramp_delay_s: float = 0.1      # delay per ramp step
    hold_delay_s: float = 1.0      # wait after reaching setpoint
    n_averages:   int   = 3
    x_mm: float = 0.0
    y_mm: float = 0.0
    z_mm: float = 0.0
    # Bias-supply channel this IV sweep drives.
    # None = the primary channel (DeviceManager.bias_supply) = historic behavior.
    bias_channel: int | None = None


@dataclass
class ScanPoint:
    x_mm: float
    y_mm: float
    z_mm: float
    index: int


@dataclass
class ScanResult:
    point: ScanPoint
    timestamp: float
    ref_amplitude_V: float
    ref_charge_pC: float
    dut_amplitude_V: float
    dut_charge_pC: float
    dut_charge_norm: float
    baseline_rms_V: float
    drift_time_s:  float | None = None   # carrier drift time = trailing - onset
    rise_time_s:   float | None = None   # 10%→90% rise time
    cfd_time_s:    float | None = None   # CFD threshold crossing time
    onset_time_s:  float | None = None   # leading-edge onset time
    camera_frame: np.ndarray | None = None
    ref_waveform: np.ndarray | None = None
    dut_waveform: np.ndarray | None = None
    time_axis: np.ndarray | None = None
    # Measured per-point context (not recomputable offline)
    bias_voltage_V: float | None = None
    bias_current_A: float | None = None
    slow_control: dict | None = None
    # Absolute-charge calibration result (set when a calibration is configured)
    dut_charge_cal: float | None = None
    charge_units: str | None = None


def _build_scan_points(cfg: ScanConfig) -> list[ScanPoint]:
    xs = np.arange(cfg.x_start_mm, cfg.x_stop_mm + cfg.x_step_mm / 2, cfg.x_step_mm)
    ys = np.arange(cfg.y_start_mm, cfg.y_stop_mm + cfg.y_step_mm / 2, cfg.y_step_mm)
    points: list[ScanPoint] = []
    for i, x in enumerate(xs):
        row = ys if i % 2 == 0 else ys[::-1]   # boustrophedon
        for y in row:
            points.append(ScanPoint(x_mm=float(x), y_mm=float(y), z_mm=cfg.z_mm, index=len(points)))
    return points


class ScanController:
    """
    Executes an automated 2-D (X/Y) TCT scan.

    Callbacks
    ---------
    on_point_done(result: ScanResult)   — called after each scan point
    on_progress(done: int, total: int)  — called after each scan point
    on_finished()                       — called when scan completes or aborts
    on_error(msg: str)                  — called on unrecoverable error
    """

    def __init__(
        self,
        devices: DeviceManager,
        state_machine: StateMachine,
        writer: HDF5Writer | None = None,
    ) -> None:
        self._dev = devices
        self._sm = state_machine
        # A fresh per-run writer is allocated by _begin_run; passing one here
        # is only useful for tests.
        self._writer = writer
        self._thread: threading.Thread | None = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._abort_event = threading.Event()

        # Path of the HDF5 file the most recent run wrote, for the future
        # "Open in Analysis" hand-off (design review Q6ii).  Set on the worker
        # thread in _end_run (before on_finished fires) and read from the GUI
        # thread via last_run_path — guarded by a lock so the cross-thread read
        # never sees a torn reference.  Cleared at the start of every run
        # (_begin_run) so a fresh/aborted run never surfaces a stale path.
        self._run_path_lock = threading.Lock()
        self._last_run_path: Path | None = None

        # Scan type of the run currently in flight, for the run-state facade the
        # GUI polls (~1 Hz) so it can label the active scan without owning any
        # run state itself.  Set in _begin_run (where the canonical scan_type
        # string is already known) and cleared back to None in _end_run, so it
        # is non-None exactly while a run is executing.  A plain attribute, read
        # lock-free from the GUI thread exactly like ``sm.state`` is polled: a
        # str/None reference read/write is atomic under the GIL, so no lock is
        # needed (unlike last_run_path, kept behind a lock only for parity with
        # the pre-existing design).
        self._current_scan_type: str | None = None

        # Free-text reason for the run's terminal state, for the HDF5 outcome
        # record (see _end_run / HDF5Writer.set_outcome).  None for a clean
        # finish.  Set via _fire_error (every internal fault path funnels
        # through it) or abort()'s own reason argument; reset per run in
        # _begin_run so a prior run's reason never leaks into the next file.
        self._last_run_reason: str | None = None

        # Per-run HV arm latch (plan executor).  Only ever set True by
        # arm_hv(True) after a real user confirmation; cleared at the end of
        # every run so arming is never sticky across runs.
        self._hv_armed = False
        # Consecutive unreadable-bias counter, shared by the classic scan loop
        # and the plan executor via _check_compliance; reset at each run start.
        self._bias_read_failures = 0
        # Set whenever the run is paused (pause() or a ManualPauseStep); the
        # plan executor re-asserts HV on the following resume (the compiled
        # BiasStep list is deduped, so a resume must re-establish bias itself).
        self._reassert_pending = False

        # Slow-control excursion latch (DECISIONS 2026-07-12 policy): the set of
        # channel names currently in an acknowledged WARN / UNAVAILABLE excursion.
        # A channel is latched when the policy first pauses on it and cleared only
        # when it reads OK again, so an ongoing WARN does not re-pause every
        # snapshot after the operator acks (Resume).  ALARM ignores the latch —
        # it always fail-safe aborts.  Reset per run in _begin_run.
        self._sc_latched: set[str] = set()

        # Public callbacks
        self.on_point_done: Callable[[ScanResult], None] | None = None
        self.on_progress:   Callable[[int, int], None]   | None = None
        self.on_finished:   Callable[[], None]           | None = None
        self.on_error:      Callable[[str], None]        | None = None
        # Voltage scan callback: (voltage_V, dut_charge_pC, current_A)
        self.on_vscan_point: Callable[[float, float, float], None] | None = None
        # Manual-pause prompt surfacing.  ManualPauseStep clears the pause event
        # and fires this so the GUI can show the operator what to do (on_progress
        # carries no message).  Controller-owned hook; the GUI wires a dialog to
        # it and calls resume() when the operator is done.
        self.on_manual_pause: Callable[[str], None] | None = None

    # ------------------------------------------------------------------ #
    # Run-directory / writer allocation                                   #
    # ------------------------------------------------------------------ #

    def _next_run_dir(self) -> Path:
        base = self._dev.data_dir
        base.mkdir(parents=True, exist_ok=True)
        existing = sorted(base.glob("run_*"))
        return base / f"run_{len(existing) + 1:05d}"

    @property
    def last_run_path(self) -> Path | None:
        """HDF5 file path the most recent run wrote, or None.

        Thread-safe accessor for the GUI (read after ``on_finished``): None
        before any run and while a run is in progress, then the just-written
        ``waveforms.h5`` path once the run's writer is closed.  Populated in
        :meth:`_end_run` before ``on_finished`` fires; cleared in
        :meth:`_begin_run` on every new run start.
        """
        with self._run_path_lock:
            return self._last_run_path

    def _set_last_run_path(self, path: Path | None) -> None:
        with self._run_path_lock:
            self._last_run_path = path

    @property
    def current_scan_type(self) -> str | None:
        """Scan type of the run currently executing, or ``None`` when idle.

        Read-only, lock-free accessor for the GUI's run-state facade (polled
        ~1 Hz): the canonical scan_type string (``"xy_scan"``,
        ``"voltage_scan"``, ``"recipe_plan"``, …) while a run is in flight,
        ``None`` before any run starts and again once a run finishes/aborts.
        Set in :meth:`_begin_run`, cleared in :meth:`_end_run`.  A plain
        attribute read — atomic under the GIL, mirroring how ``sm.state`` is
        polled cross-thread — so it never needs a lock.
        """
        return self._current_scan_type

    def _begin_run(self, scan_type: str, cfg) -> HDF5Writer:
        """Allocate a fresh run directory + writer, attach run metadata, open it."""
        # A new run supersedes any previous run's path (cleared on start; set
        # again in _end_run once this run's file is closed).
        self._set_last_run_path(None)
        # Fresh slow-control excursion latch per run — an excursion from a prior
        # run never suppresses the first pause of this one.
        self._sc_latched.clear()
        # A fresh run starts with no terminal-state reason; a clean finish
        # never inherits the previous run's abort/error text.
        self._last_run_reason = None
        # Publish the active scan type for the GUI's run-state facade; cleared
        # in _end_run's finally so it is non-None exactly while a run runs.
        self._current_scan_type = scan_type
        run_info = self._build_run_info(scan_type, cfg)
        self._writer = HDF5Writer(
            self._next_run_dir(),
            save_options=self._dev.save_options,
            run_info=run_info,
        )
        self._writer.open()
        return self._writer

    def _end_run(self) -> None:
        """Close the current writer, swallowing errors so cleanup never raises.

        Publishes the just-written HDF5 path via :attr:`last_run_path` *before*
        ``on_finished`` fires (every run body calls this in its ``finally`` right
        before the finished callback), so the GUI can hand the run off to
        analysis.  The path is published even on an aborted/errored run — data
        taken before the fault is preserved and still openable.

        Also records how the run ended: every run body resolves its terminal
        state (:meth:`_settle_terminal_state` / :meth:`_settle_error_state`)
        BEFORE its ``finally`` calls here, so ``self._sm.state`` is already
        FINISHED/ABORTED/ERROR.  That plus whatever reason the fault path
        recorded (:attr:`_last_run_reason`, set by :meth:`_fire_error` or
        ``abort()``) is the file's only record of outcome — without it a
        trip-aborted run and a clean short one are byte-for-byte identical.
        """
        try:
            if self._writer is not None:
                self._writer.set_outcome(
                    _STATE_OUTCOME.get(self._sm.state, "unknown"),
                    reason=self._last_run_reason,
                )
                self._writer.close()
        except Exception:
            logger.warning("Writer close failed", exc_info=True)
        finally:
            # .path survives close() (only the file handle is dropped), so the
            # accessor exposes it whether or not the flush/close succeeded.
            if self._writer is not None:
                self._set_last_run_path(self._writer.path)
            # Run over: current_scan_type reverts to None (idle) for the facade.
            self._current_scan_type = None

    def _save_z_focus(self, z_mm: float, metric: float) -> None:
        try:
            if self._writer is not None:
                self._writer.save_z_focus_point(z_mm, metric)
        except Exception:
            logger.warning("z-focus save failed", exc_info=True)

    def _save_voltage(self, voltage_V: float, charge_pC: float, current_A: float) -> None:
        try:
            if self._writer is not None:
                self._writer.save_voltage_point(voltage_V, charge_pC, current_A)
        except Exception:
            logger.warning("voltage-scan save failed", exc_info=True)

    def _build_run_info(self, scan_type: str, cfg) -> dict:
        try:
            scan_cfg = asdict(cfg) if is_dataclass(cfg) and not isinstance(cfg, type) else {}
        except Exception:
            scan_cfg = {}
        info: dict = {"scan_type": scan_type, "scan_config": scan_cfg}
        try:
            info["devices_config"] = self._dev.config_snapshot()
        except Exception:
            pass
        try:
            info["charge_calibration"] = self._dev.raw_config.get("charge_calibration", {})
        except Exception:
            pass
        lim = getattr(self._dev.motor, "limits", None)
        if lim is not None:
            info["software_limits"] = {
                "x_min": lim.x_min, "x_max": lim.x_max,
                "y_min": lim.y_min, "y_max": lim.y_max,
                "z_min": lim.z_min, "z_max": lim.z_max,
            }
        return info

    def _resolve_bias(self, cfg) -> BiasChannel:
        """Resolve which bias-supply channel this run drives / records.

        ``cfg.bias_channel is None`` (the default) returns the primary proxy,
        ``self._dev.bias_supply`` — byte-for-byte the historic single-channel
        path.  An explicit integer selects ``self._dev.bias_channels[idx]``.

        An out-of-range or non-integer index raises *before* any hardware
        action and refuses to start: HV channel selection must be explicit and
        must never silently fall back to another channel.
        """
        idx = getattr(cfg, "bias_channel", None)
        if idx is None:
            return self._dev.bias_supply
        channels = self._dev.bias_channels
        n = len(channels)
        if isinstance(idx, bool) or not isinstance(idx, int) or not (0 <= idx < n):
            raise ValueError(
                f"bias_channel={idx!r} is out of range — the bias supply "
                f"exposes {n} channel(s) (valid indices 0..{n - 1}). Refusing "
                "to start; HV channel selection must be explicit and never "
                "silently falls back to another channel."
            )
        return channels[idx]

    # ------------------------------------------------------------------ #
    # Public control interface                                            #
    # ------------------------------------------------------------------ #

    def _refuse_if_active(self) -> None:
        """Fail-closed guard shared by EVERY scan/plan entry point.

        Fuzz-found (test_state_fuzz): ``can(RUNNING)`` is True from PAUSED (the
        resume edge), so guarding on it alone lets a start spawn a SECOND worker
        while a run is parked in PAUSED — both sharing writer / abort / HV /
        state machine (data corruption + uncoordinated HV hazard; Mary
        REQUEST-CHANGES on dac5b67, reproduced on the z-focus / voltage paths).
        Only :meth:`resume` may leave PAUSED; refuse any start while a run is
        paused OR a worker thread is still alive.  Additive to each caller's
        existing ``can(RUNNING)`` check — fail-closed, before any state change
        or hardware action.
        """
        if self._sm.state is AppState.PAUSED or (
            self._thread is not None and self._thread.is_alive()
        ):
            raise RuntimeError("A run is already active (paused or running).")

    def start(self, cfg: ScanConfig) -> None:
        if not self._sm.can(AppState.RUNNING):
            raise RuntimeError("Cannot start scan in current state.")
        self._refuse_if_active()        # fail-closed: never a 2nd worker from PAUSED
        bias = self._resolve_bias(cfg)  # validate BEFORE any state change / hardware
        self._abort_event.clear()
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)
        self._thread = threading.Thread(
            target=self._run, args=(cfg, bias), daemon=True, name="ScanThread"
        )
        self._thread.start()

    def arm_hv(self, confirmed: bool) -> None:
        """Latch permission for the next plan run to drive HV.

        Sets the private ``_hv_armed`` latch that :meth:`start_plan` requires
        before it will accept a plan containing a ``BiasStep``.  **Only ever
        call this with ``True`` after a real user confirmation** (the HV-arm
        checkbox / dialog on the UI thread).  The latch is per-run — every run
        clears it on completion (:meth:`_run_plan` ``finally``) — so arming is
        never sticky across runs.
        """
        self._hv_armed = bool(confirmed)

    def arm_envelope_for(
        self, plan: ScanPlan, *, timeout_s: float | None = None
    ) -> ArmedEnvelope:
        """Derive the :class:`ArmedEnvelope` the two-step latch will authorize.

        Resolves the plan's bias channel exactly as :meth:`start_plan` does (via
        :meth:`_resolve_bias`, honoring ``plan.safety['bias_channel']``), compiles
        the plan, and returns the bounded, enumerated envelope (channels, signed
        HV range, ramp shape, per-axis motion bounds, optional expiry) with a
        human-readable :attr:`~ArmedEnvelope.summary`.

        Pure/read-only: no hardware I/O, no state change.  The GUI (Noah's beat)
        calls this to render the Arm latch, then on Execute builds an
        :class:`~controller.arm_envelope.ArmedEnvelopeGate` around the returned
        envelope, calls :meth:`arm_hv` ``(True)``, and passes the gate to
        :meth:`start_plan`.  ``timeout_s`` sets an OPTIONAL gate expiry (a
        defense-in-depth freshness bound); the ~10 s Arm->Execute latch of design
        law 5 is a separate GUI timer, NOT this value.
        """
        bias = self._resolve_bias(
            SimpleNamespace(bias_channel=(plan.safety or {}).get("bias_channel"))
        )
        return envelope_from_plan(plan, bias.channel, timeout_s=timeout_s)

    def start_plan(
        self, plan: ScanPlan, limits: PlanLimits, gate: DangerGate
    ) -> None:
        """Validate, arm-check, and launch a compiled :class:`ScanPlan`.

        Mirrors :meth:`start`: the same ``can(RUNNING)`` guard, the same
        refuse-*before*-any-state-change discipline, the same daemon thread and
        cooperative pause/abort.  On top of that it adds the plan's fail-closed
        HV gate:

        1. ``can(AppState.RUNNING)`` else ``RuntimeError`` (identical to
           :meth:`start`).
        2. :func:`validate_plan` against *limits* — any ERROR raises
           ``ValueError`` and refuses to start (fail closed, before any state
           change or hardware action).
        3. If the compiled plan contains a ``BiasStep`` and HV is not armed,
           raise ``RuntimeError`` — a bias-driving plan needs an explicit
           :meth:`arm_hv` after a user confirmation.
        4. Resolve the bias channel BEFORE any state change (via the existing
           :meth:`_resolve_bias`, using ``plan.safety['bias_channel']`` when
           present, else the primary proxy — same validation semantics).
        5. Clear abort / set pause, transition ``RUNNING``, spawn ``_run_plan``.

        Any refusal in the pre-flight clears the per-run HV arm latch, so a
        failed *armed* start never leaks arming into a later plan (RISK, M2.2
        review); a successful start keeps the arm until the run consumes it.
        The plan is compiled exactly once here and the compiled steps are handed
        to :meth:`_run_plan` (no re-compile downstream).

        Every ``BiasStep`` and the first stage move is *additionally* gated
        through *gate* at run time — validation and arming are the paper gate,
        *gate* is the live per-danger confirmation.
        """
        # Pre-flight — every refusal below clears the per-run HV arm latch so a
        # failed *armed* start is never sticky into a later plan.  A SUCCESSFUL
        # start keeps the arm; it is consumed at run end (_run_plan finally).
        try:
            # 1. State guard (identical to start, incl. the fuzz-found
            #    start-while-PAUSED / worker-alive refusal — fail-closed).
            if not self._sm.can(AppState.RUNNING):
                raise RuntimeError("Cannot start scan in current state.")
            self._refuse_if_active()    # fail-closed: never a 2nd worker from PAUSED

            # 2. Pure pre-flight — refuse a bad plan before touching anything.
            errs = errors(validate_plan(plan, limits))
            if errs:
                raise ValueError(
                    "Scan plan failed validation — refusing to start:\n"
                    + "\n".join(f"  • {e}" for e in errs)
                )

            # 3. Compile ONCE — the single source of truth handed to _run_plan.
            steps = compile_plan(plan)

            # 4. Fail-closed HV arm check for a bias-driving plan.  (When this
            #    raises the latch is already False, so the reset below is a
            #    harmless no-op.)
            if any(isinstance(s, BiasStep) for s in steps) and not self._hv_armed:
                raise RuntimeError(
                    "Plan drives HV but HV is not armed — call arm_hv(True) after "
                    "a user confirmation before starting."
                )

            # 5. Resolve the bias channel BEFORE any state change / hardware.  A
            #    plan selects its channel via safety['bias_channel'];
            #    _resolve_bias validates it (out-of-range / wrong-type raises).
            bias = self._resolve_bias(
                SimpleNamespace(bias_channel=(plan.safety or {}).get("bias_channel"))
            )
        except Exception:
            self._hv_armed = False        # a refused start never leaves HV armed
            raise

        self._abort_event.clear()
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)
        self._thread = threading.Thread(
            target=self._run_plan, args=(plan, steps, bias, gate), daemon=True,
            name="PlanThread",
        )
        self._thread.start()

    def pause(self) -> None:
        self._pause_event.clear()
        # Remember that we paused so the plan executor re-asserts HV on resume
        # (harmless no-op for the classic scan loops, which ignore the flag).
        self._reassert_pending = True
        self._sm.transition(AppState.PAUSED)

    def resume(self) -> None:
        # No-op unless actually paused: a resume racing a run that already
        # finished/aborted (e.g. the manual-pause dialog answered late) must
        # not attempt an illegal PAUSED->RUNNING transition and raise into
        # the caller's (GUI) thread.
        if self._sm.state is not AppState.PAUSED:
            return
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)

    def abort(self, reason: str | None = None) -> None:
        """Operator/GUI abort request.

        *reason* is optional free text for the HDF5 outcome record (falls
        back to a generic "Operator abort" so a bare ``abort()`` — every
        existing caller — still leaves an honest, non-empty reason in the
        file rather than an unexplained ``aborted``).
        """
        self._last_run_reason = reason or "Operator abort"
        self._abort_event.set()
        self._pause_event.set()  # unblock if paused
        self._dev.motor.stop()

    def park_safe(self) -> None:
        """Assert the between-entries safe state: HV to 0 V, output OFF, motors stopped.

        The public parking seam the Scan Sequencer calls BETWEEN plan entries
        (after ``record_outcome``, before the next ``next_entry``) and the last
        line of defense on any teardown path.  It is a **thin composition of the
        existing run-loop fail-safe primitives** — it introduces no new behaviour:

        * :meth:`_bias_failsafe` — ramp the resolved bias channel to 0 V (its own
          ``try``) then open the output (its own ``try``), the exact two-step
          discipline every fault/deny/abort path already applies;
        * :meth:`_motor_stop_safe` — best-effort halt of all stage axes.

        **No parking MOTION is ever commanded.**  "Park" here means HV to 0 V +
        output off + motors *stopped* — never an XY/Z move to some "park
        position" (hardware safety rule 1: no auto-motion; a move commanded
        between entries could crash the stage or the DUT into the optics).

        Safe and **idempotent in every state** — it never raises into the caller,
        because it IS the caller's safety net:

        * no run active / already parked / supply already at 0 V + off → no-op;
        * after FINISHED → a harmless belt-and-braces re-assert;
        * after ERROR / ABORTED → the executor's fail-safe already ran, so
          re-asserting is harmless;
        * bias supply (or the whole stack) disconnected → a clean no-op, logged
          at debug, never a raise.

        Internal failures are swallowed and logged: the two-``try`` fail-safe
        already guarantees the output-off attempt is made even if the ramp-down
        raises, and the motor halt is independently guarded.
        """
        # Resolve the primary bias channel exactly as the fault/abort paths do
        # (default cfg -> self._dev.bias_supply).  Resolution itself must never
        # propagate: park_safe is the last line of defense.
        bias: BiasChannel | None = None
        try:
            bias = self._resolve_bias(SimpleNamespace(bias_channel=None))
        except Exception:
            logger.debug("park_safe: no bias channel to park", exc_info=True)

        # Gate on connectivity like _check_compliance does: a disconnected supply
        # is a clean, quiet no-op (calling ramp_to on it would only raise into the
        # fail-safe's WARN branch).  The whole block is belt-and-braces guarded so
        # a driver-side surprise can never skip the motor halt below.
        try:
            if bias is None:
                pass
            elif bias.connected:
                self._bias_failsafe(bias)   # ramp->0 (own try) then output off (own try)
            else:
                logger.debug("park_safe: bias supply not connected — HV park is a no-op")
        except Exception:
            logger.debug("park_safe: bias park skipped", exc_info=True)

        self._motor_stop_safe()             # best-effort halt; never a MOVE

    def _fire_error(self, msg: str) -> None:
        """Record *msg* as this run's terminal-state reason, then forward it.

        Every internal fault path (an unhandled exception, a bias compliance/
        hardware-fault abort, a slow-control ALARM abort, a denied danger
        confirmation) funnels through here instead of calling ``on_error``
        directly, so the text written into the HDF5 outcome record
        (:attr:`_last_run_reason`, consumed by :meth:`_end_run`) is EXACTLY
        what the operator saw on screen — one source of truth, never a second
        message that can drift from the GUI's.
        """
        self._last_run_reason = msg
        if self.on_error:
            self.on_error(msg)

    def start_z_focus_scan(
        self,
        cfg: "ZFocusScanConfig",
        on_point: Callable[[float, float], None] | None = None,
        on_done:  Callable[[float], None] | None = None,
    ) -> None:
        """
        Run a Z-axis focal-point scan in a background thread.

        Sweeps Z from cfg.z_start_mm to cfg.z_stop_mm, measuring DUT
        amplitude at each step.  Reports each (z_mm, amplitude_V) via
        on_point, and the optimal Z via on_done when finished.
        """
        if not self._sm.can(AppState.RUNNING):
            raise RuntimeError("Cannot start Z-focus scan in current state.")
        self._refuse_if_active()        # fail-closed: never a 2nd worker from PAUSED
        self._abort_event.clear()
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)
        self._thread = threading.Thread(
            target=self._run_z_focus,
            args=(cfg, on_point, on_done),
            daemon=True,
            name="ZFocusThread",
        )
        self._thread.start()

    def start_voltage_scan(
        self,
        cfg: "VoltageScanConfig",
    ) -> None:
        """Run a bias voltage scan (IV curve) in a background thread."""
        if not self._sm.can(AppState.RUNNING):
            raise RuntimeError("Cannot start voltage scan in current state.")
        self._refuse_if_active()        # fail-closed: never a 2nd worker from PAUSED
        bias = self._resolve_bias(cfg)  # validate BEFORE any state change / hardware
        self._abort_event.clear()
        self._pause_event.set()
        self._sm.transition(AppState.RUNNING)
        self._thread = threading.Thread(
            target=self._run_voltage_scan,
            args=(cfg, bias),
            daemon=True,
            name="VoltageScanThread",
        )
        self._thread.start()

    # ------------------------------------------------------------------ #
    # Terminal-state resolution (shared by the run loops)                 #
    # ------------------------------------------------------------------ #

    # How many transition attempts a settle helper makes before giving up.  A
    # settle needs at most two edges (PAUSED->RUNNING->FINISHED/ERROR); the
    # extra headroom absorbs a GUI pause/resume racing the promotion.
    _SETTLE_ATTEMPTS = 6

    def _settle_terminal_state(self) -> None:
        """Resolve a run loop's terminal state from RUNNING **or** PAUSED.

        A cooperative pause — the GUI Pause button or a slow-control safe-hold
        (:meth:`_slow_control_warn_hold`) — parks the loop with the state
        machine in PAUSED.  PAUSED has no legal edge to FINISHED, so a run that
        ends while parked (pause pressed on the last step) must be promoted
        through RUNNING first.  ABORTED is legal from both states, so an abort
        needs no promotion.

        **Race-safe** (Mary, review of 3f6e2b7): the promotion is two calls
        against an *unlocked* :class:`StateMachine`, so a GUI ``resume()`` (or
        ``pause()``) landing between them makes the next ``transition`` illegal
        — a CLEAN run would then be reported as ``ERROR("Invalid transition:
        RUNNING → RUNNING")``.  Every edge is therefore ``can()``-guarded, a lost
        race is swallowed, and the state is **re-read** each attempt so the
        helper still converges on a terminal state (bounded by
        ``_SETTLE_ATTEMPTS`` — it can never spin).
        """
        for _ in range(self._SETTLE_ATTEMPTS):
            state = self._sm.state
            if state not in (AppState.RUNNING, AppState.PAUSED):
                return                          # already terminal — leave it
            if self._abort_event.is_set():
                target = AppState.ABORTED       # legal from RUNNING + PAUSED
            elif state is AppState.PAUSED:
                target = AppState.RUNNING       # promote: PAUSED has no FINISHED edge
            else:
                target = AppState.FINISHED
            try:
                if self._sm.can(target):
                    self._sm.transition(target)
            except ValueError:
                continue        # raced a GUI pause/resume — re-read and retry
        logger.warning("Terminal state unresolved (still %s)", self._sm.state.name)

    def _settle_error_state(self) -> None:
        """Fail into ERROR from RUNNING **or** PAUSED.

        PAUSED→ERROR is not a legal edge, so a fault raised while a run is
        parked has to be promoted through RUNNING first.  Same race-safety as
        :meth:`_settle_terminal_state`: every edge is ``can()``-guarded and a
        lost race with a GUI pause/resume is swallowed, because a ``ValueError``
        raised *here* would propagate out of the caller's ``except`` block and
        the operator would never see the ORIGINAL fault.  Callers therefore also
        fire ``on_error`` BEFORE calling this — the fault message can never be
        lost to a settle race.
        """
        for _ in range(self._SETTLE_ATTEMPTS):
            state = self._sm.state
            if state is AppState.PAUSED:
                target = AppState.RUNNING       # promote, then ERROR next pass
            elif self._sm.can(AppState.ERROR):
                target = AppState.ERROR
            else:
                return                          # already terminal — leave it
            try:
                if self._sm.can(target):
                    self._sm.transition(target)
            except ValueError:
                continue        # raced a GUI pause/resume — re-read and retry
            if target is AppState.ERROR:
                return
        logger.warning("Error state unresolved (still %s)", self._sm.state.name)

    # ------------------------------------------------------------------ #
    # Paused-run supervision (the park loop every run loop waits in)      #
    # ------------------------------------------------------------------ #

    # Supervision cadence while a run is parked in PAUSED.  Bounded poll, no new
    # thread: the worker is already blocked in the park, so it does the watching.
    _PAUSE_POLL_S = 0.5

    def _park_while_paused(self, bias: BiasChannel | None) -> None:
        """Block while the run is paused — **supervising the hardware it holds**.

        Replaces the bare ``self._pause_event.wait()`` every run loop used to
        park in.  A pause HOLDS HV at the last set point (the ratified WARN
        safe-hold semantic, DECISIONS 2026-07-12 §2), but a blocked worker
        re-reads *nothing*: a paused run could sit at HV indefinitely with no
        compliance check and no slow-control evaluation, and the only thing
        watching was a display-only GUI tile (Mary, review of 3f6e2b7).

        So the park is a **bounded-cadence poll** instead of an unbounded wait:
        every ``_PAUSE_POLL_S`` the worker re-checks bias compliance and the
        slow-control channels (:meth:`_supervise_parked_run`).  A compliance trip
        or an ALARM while parked fail-safe aborts exactly as it does mid-run (HV
        ramped down, output off, abort event set) and releases the park so the
        loop breaks.  Not paused → ``wait`` returns immediately and this costs
        nothing.
        """
        while not self._pause_event.wait(timeout=self._PAUSE_POLL_S):
            if self._abort_event.is_set():
                return                          # abort() unblocks the park itself
            self._supervise_parked_run(bias)

    def _supervise_parked_run(self, bias: BiasChannel | None) -> None:
        """One supervision sweep of a run parked in PAUSED (HV still energized).

        Same two guards the run loop applies between steps, at the park cadence:

        * bias hardware fault / compliance / readability — :meth:`_check_compliance`
          (a latched trip, an output the module dropped behind our back, or a
          compliance trip sets the abort event, ramps HV down and opens the output;
          3 consecutive unreadable reads raise ``DeviceError``, which propagates
          into the run loop's ``except`` and fails the run safe).  A paused run is
          the WORST place to miss a trip — it can sit at HV indefinitely — so the
          watchdog inherits the hardware-fault guard from the shared helper;
        * the slow-control excursion policy — an ALARM while parked is a full
          fail-safe abort (ratified policy), a WARN is already held.

        On abort the pause event is re-set so :meth:`_park_while_paused` returns
        and the loop's ``if self._abort_event.is_set(): break`` fires.
        """
        if bias is None:
            return
        if self._check_compliance(bias, context=" while paused"):
            self._pause_event.set()             # release the park -> loop breaks
            return
        self._apply_slow_control_policy(self._slow_control_read_all(), bias)
        if self._abort_event.is_set():
            self._pause_event.set()             # release the park -> loop breaks

    # ------------------------------------------------------------------ #
    # Scan loop (runs in background thread)                               #
    # ------------------------------------------------------------------ #

    def _run(self, cfg: ScanConfig, bias: BiasChannel) -> None:
        points = _build_scan_points(cfg)
        total = len(points)
        logger.info("Scan started: %d points", total)

        self._bias_read_failures = 0
        try:
            self._begin_run("xy_scan", cfg)
            for point in points:
                # Pause / abort checks.  The park SUPERVISES the parked run
                # (compliance + slow control at a bounded cadence) instead of
                # blocking blind — see _park_while_paused.
                self._park_while_paused(bias)
                if self._abort_event.is_set():
                    logger.info("Scan aborted at point %d / %d", point.index, total)
                    break

                result = self._acquire_point(point, cfg, bias)

                if self._abort_event.is_set():
                    break

                # Compliance-trip safety check during scan (shared helper): the
                # only protection against cooking a sensor mid-scan, so it
                # aborts + ramps down on a trip and fails safe after 3
                # consecutive unreadable reads.
                if self._check_compliance(bias, context=f" at point {point.index}"):
                    break

                self._writer.save_point(result)

                if self.on_point_done:
                    self.on_point_done(result)
                if self.on_progress:
                    self.on_progress(point.index + 1, total)

            # Resolve the end state for every exit path (abort / compliance
            # break / clean finish / safe-hold on the last point), race-safe
            # against a GUI pause or resume — see _settle_terminal_state.
            self._settle_terminal_state()

        except Exception as exc:
            logger.exception("Scan error")
            # on_error FIRST: a settle that raced a GUI pause/resume must never
            # swallow the operator's only view of the original fault.
            self._fire_error(str(exc))
            self._settle_error_state()
        finally:
            # Fail-safe rule 5 ('stop motion'): halt any in-flight stage move on
            # an exception-driven exit (abort() already stops the motor, but a
            # fault DURING a move does not).  Best-effort/isolated; no-op on a
            # clean finish.
            self._motor_stop_safe()
            self._end_run()
            # Always turn off laser trigger after scan
            try:
                self._dev.waveform_generator.output_off()
            except Exception:
                logger.warning("Waveform-generator output_off failed", exc_info=True)
            if self.on_finished:
                self.on_finished()

    def _run_z_focus(
        self,
        cfg: "ZFocusScanConfig",
        on_point: Callable[[float, float], None] | None,
        on_done:  Callable[[float], None] | None,
    ) -> None:
        """
        Background thread for Z focal-point scan.

        Two modes (cfg.mode):
          "amplitude"  — legacy: max DUT amplitude at fixed XY.
          "edge_scan"  — correct: max edge sharpness from a short X scan at
                         each Z, per Particulars / standard TCT practice.
        """
        if cfg.mode == "edge_scan":
            self._run_z_focus_edge(cfg, on_point, on_done)
        else:
            self._run_z_focus_amplitude(cfg, on_point, on_done)

    def _run_z_focus_amplitude(
        self,
        cfg: "ZFocusScanConfig",
        on_point: Callable[[float, float], None] | None,
        on_done:  Callable[[float], None] | None,
    ) -> None:
        """
        Legacy amplitude mode: sweep Z at a fixed (x, y) and return the Z
        with the highest DUT amplitude.

        Limitation: only works reliably when the beam is positioned over the
        silicon bulk (between strips).  Use edge_scan mode for robust focus
        finding.
        """
        dev = self._dev
        zs = np.arange(cfg.z_start_mm, cfg.z_stop_mm + cfg.z_step_mm / 2, cfg.z_step_mm)
        total = len(zs)
        results: list[tuple[float, float]] = []
        # The DUT is biased during a focus scan even though this loop does not
        # drive HV — the slow-control policy needs a channel to fail safe on, and
        # a ZFocusScanConfig carries no bias_channel, so _resolve_bias returns the
        # primary proxy (exactly what start_voltage_scan does for cfg.bias_channel
        # = None).  Resolved before any hardware action.
        bias = self._resolve_bias(cfg)

        try:
            self._begin_run("z_focus_amplitude", cfg)
            dev.waveform_generator.output_on()
            time.sleep(0.01)

            for i, z in enumerate(zs):
                # Cooperative pause / abort between steps (non-negotiable 2):
                # a z-focus run drives real motion, so Pause must actually park
                # the loop — not just flip the state machine while the stage
                # keeps stepping.  abort() sets _pause_event too, so an abort
                # from PAUSED unblocks here and exits on the check below.  The
                # park supervises compliance + slow control while held.
                self._park_while_paused(bias)
                if self._abort_event.is_set():
                    break
                dev.motor.move_to(cfg.x_mm, cfg.y_mm, float(z))
                dev.motor.wait_until_ready()
                time.sleep(cfg.settle_time_s)

                amps = []
                for _ in range(max(cfg.n_averages, 1)):
                    t2, v2 = dev.scope.read_channel(2)
                    res = analyse_waveform(t2, v2, **self._dev.analysis_kwargs)
                    amps.append(res.amplitude_V)
                amp_mean = float(np.mean(amps))
                results.append((float(z), amp_mean))
                self._save_z_focus(float(z), amp_mean)
                logger.debug("Z-focus (amplitude): z=%.3f mm  amp=%.4f V", z, amp_mean)
                if on_point:
                    on_point(float(z), amp_mean)
                # Law 8 / honest cockpit: this loop knows its length, so it
                # reports real progress (and therefore a real ETA) instead of
                # leaving the tiles frozen at "0/0" for the whole run.
                if self.on_progress:
                    self.on_progress(i + 1, total)

                # Environmental interlock (DECISIONS 2026-07-12 §2): this loop
                # reads the scope directly and never went through _acquire_core,
                # so it USED to run with NO temperature/humidity interlock at all.
                # WARN -> safe-hold pause; ALARM -> fail-safe abort (HV down).
                self._apply_slow_control_policy(self._slow_control_read_all(), bias)
                if self._abort_event.is_set():
                    break

            dev.waveform_generator.output_off()

            if results and not self._abort_event.is_set():
                best_z = max(results, key=lambda p: p[1])[0]
                logger.info("Z-focus best z = %.3f mm (amplitude mode)", best_z)
                if on_done:
                    on_done(best_z)

            self._settle_terminal_state()
        except Exception as exc:
            logger.exception("Z-focus amplitude scan error")
            # on_error BEFORE the settle — a settle racing a GUI pause/resume
            # must never swallow the fault message.
            self._fire_error(str(exc))
            self._settle_error_state()
        finally:
            try:
                dev.waveform_generator.output_off()
            except Exception:
                pass
            self._motor_stop_safe()
            self._end_run()
            if self.on_finished:
                self.on_finished()

    def _run_z_focus_edge(
        self,
        cfg: "ZFocusScanConfig",
        on_point: Callable[[float, float], None] | None,
        on_done:  Callable[[float], None] | None,
    ) -> None:
        """
        Edge-scan focus mode (physically correct).

        At each Z step a short X scan crosses a metal/silicon edge.
        Edge sharpness = max |dQ/dx| over the X profile.  The Z with the
        highest sharpness has the smallest beam spot = best focus.

        This is the technique described in the Particulars TCT manual:
        an error-function transition in charge collection becomes steepest
        (smallest FWHM) exactly at the focal plane of the objective.
        """
        dev = self._dev
        zs = np.arange(cfg.z_start_mm, cfg.z_stop_mm + cfg.z_step_mm / 2, cfg.z_step_mm)
        xs = np.arange(
            cfg.x_edge_center_mm - cfg.x_edge_range_mm,
            cfg.x_edge_center_mm + cfg.x_edge_range_mm + cfg.x_edge_step_mm / 2,
            cfg.x_edge_step_mm,
        )
        total = len(zs)
        results: list[tuple[float, float]] = []   # (z_mm, sharpness)
        # See _run_z_focus_amplitude: the focus loops drive no HV but the DUT is
        # biased, so the excursion policy needs the primary bias channel to fail
        # safe on.  Resolved before any hardware action.
        bias = self._resolve_bias(cfg)

        try:
            self._begin_run("z_focus_edge", cfg)
            dev.waveform_generator.output_on()
            time.sleep(0.01)

            for i, z in enumerate(zs):
                # Cooperative pause / abort between steps (non-negotiable 2) —
                # see _run_z_focus_amplitude.  Checked in the inner X sweep too:
                # that sweep is itself a long motion loop, so a pause must land
                # within one X step, not one whole Z step.  The park supervises
                # compliance + slow control while held.
                self._park_while_paused(bias)
                if self._abort_event.is_set():
                    break

                charges: list[float] = []
                for x in xs:
                    self._park_while_paused(bias)
                    if self._abort_event.is_set():
                        break
                    dev.motor.move_to(float(x), cfg.y_mm, float(z))
                    dev.motor.wait_until_ready()
                    time.sleep(cfg.settle_time_s)

                    pt_charges = []
                    for _ in range(max(cfg.n_averages, 1)):
                        t2, v2 = dev.scope.read_channel(2)
                        res = analyse_waveform(t2, v2, **self._dev.analysis_kwargs)
                        pt_charges.append(res.charge_pC)
                    charges.append(float(np.mean(pt_charges)))

                if len(charges) < 2 or self._abort_event.is_set():
                    break

                # Edge sharpness = peak absolute spatial gradient
                charge_arr = np.array(charges)
                dx = cfg.x_edge_step_mm
                gradient = np.abs(np.diff(charge_arr) / dx)
                sharpness = float(np.max(gradient))

                results.append((float(z), sharpness))
                self._save_z_focus(float(z), sharpness)
                logger.debug(
                    "Z-focus (edge): z=%.3f mm  sharpness=%.4f pC/mm", z, sharpness
                )
                # Report sharpness as the "amplitude" value so the GUI plot works
                if on_point:
                    on_point(float(z), sharpness)
                # Law 8 / honest cockpit: real progress (and therefore a real
                # ETA) per Z step — the loop knows its length.
                if self.on_progress:
                    self.on_progress(i + 1, total)

                # Environmental interlock (DECISIONS 2026-07-12 §2) — evaluated
                # once per Z step (the unit of work); this loop reads the scope
                # directly and never went through _acquire_core, so it USED to
                # run with NO temperature/humidity interlock at all.
                self._apply_slow_control_policy(self._slow_control_read_all(), bias)
                if self._abort_event.is_set():
                    break

            dev.waveform_generator.output_off()

            if results and not self._abort_event.is_set():
                best_z = max(results, key=lambda p: p[1])[0]
                logger.info("Z-focus best z = %.3f mm (edge mode)", best_z)
                if on_done:
                    on_done(best_z)

            self._settle_terminal_state()
        except Exception as exc:
            logger.exception("Z-focus edge scan error")
            # on_error BEFORE the settle (see _settle_error_state).
            self._fire_error(str(exc))
            self._settle_error_state()
        finally:
            try:
                dev.waveform_generator.output_off()
            except Exception:
                pass
            self._motor_stop_safe()
            self._end_run()
            if self.on_finished:
                self.on_finished()

    def _run_voltage_scan(self, cfg: "VoltageScanConfig", bias: BiasChannel) -> None:
        """Background thread: IV + charge vs. bias sweep."""
        dev = self._dev
        # Compute step sign from start/stop so the user only needs to supply
        # the magnitude of v_step_V (negative values are also accepted).
        raw_step = abs(cfg.v_step_V)
        if raw_step == 0:
            raw_step = 10.0
        direction = 1 if cfg.v_stop_V >= cfg.v_start_V else -1
        signed_step = direction * raw_step
        voltages = list(np.arange(
            cfg.v_start_V,
            cfg.v_stop_V + signed_step / 2,
            signed_step,
        ))
        total = len(voltages)
        logger.info("Voltage scan started: %d steps", total)

        try:
            self._begin_run("voltage_scan", cfg)
            dev.motor.move_to(cfg.x_mm, cfg.y_mm, cfg.z_mm)
            dev.motor.wait_until_ready()
            dev.waveform_generator.output_on()
            time.sleep(0.05)

            for idx, v in enumerate(voltages):
                # Cooperative pause / abort between steps (non-negotiable 2).
                # Parking BEFORE the next ramp is the honest pause semantic for
                # an HV sweep: the supply holds the last commanded voltage (same
                # "HV held at setpoint" rule as the plan executor's pause and the
                # slow-control safe-hold) and no new voltage is commanded until
                # the operator resumes.  abort() sets _pause_event, so an abort
                # from PAUSED unblocks here, breaks, and falls through to the
                # ramp-to-0 + output-off fail-safe below.  The park supervises
                # compliance + slow control while held (the supply is still at
                # the last set point) — see _park_while_paused.
                self._park_while_paused(bias)
                if self._abort_event.is_set():
                    break

                bias.ramp_to(
                    float(v),
                    step_V=abs(cfg.ramp_step_V),
                    delay_s=cfg.ramp_delay_s,
                )
                # ramp_to is a blocking driver loop with no abort check inside
                # (making it abort-aware is a devices/ follow-up).  Without this
                # check an Abort pressed mid-ramp still dwelled, acquired and
                # only broke on the NEXT iteration — a second of CONTINUED HV
                # INCREASE after the operator hit stop.  The fail-safe finally
                # below ramps to 0 V + opens the output.
                if self._abort_event.is_set():
                    break
                time.sleep(cfg.hold_delay_s)

                reading = bias.read()
                # HARDWARE fault BEFORE compliance (the IV sweep evaluates its own
                # BiasReading — it does not go through _check_compliance).  A
                # latched trip / an output the module dropped behind our back is a
                # fail-safe abort: without this the sweep kept stepping the
                # setpoint and recording IV points into HDF5 with the HV OFF —
                # and, because a trip collapses the current to ~0, the compliance
                # test below saw nothing wrong.  See _bias_hw_fault.
                if self._bias_fault_abort(
                    bias, reading, context=f" at {reading.voltage_V:.1f} V"
                ):
                    break

                # Compliance trip → abort immediately and ramp down
                if reading.compliant:
                    logger.warning(
                        "Compliance hit at %.1f V (I=%.3e A) — aborting voltage scan",
                        reading.voltage_V, reading.current_A,
                    )
                    # A trip IS an abort (mirrors _check_compliance): without the
                    # abort event _settle_terminal_state below saw a "clean" exit
                    # and transitioned FINISHED — the GUI then painted the green
                    # "Scan finished" banner over a compliance trip.
                    self._abort_event.set()
                    self._fire_error(
                        f"Compliance trip at {reading.voltage_V:.1f} V — "
                        f"I = {reading.current_A*1e6:.2f} µA.\n"
                        "Bias ramped back to 0 V."
                    )
                    break

                charges = []
                for _ in range(max(cfg.n_averages, 1)):
                    t2, v2 = dev.scope.read_channel(2)
                    res = analyse_waveform(t2, v2, **self._dev.analysis_kwargs)
                    charges.append(res.charge_pC)
                mean_chg = float(np.mean(charges))

                self._save_voltage(reading.voltage_V, mean_chg, reading.current_A)
                if self.on_vscan_point:
                    self.on_vscan_point(reading.voltage_V, mean_chg, reading.current_A)
                if self.on_progress:
                    self.on_progress(idx + 1, total)

                # Environmental interlock (DECISIONS 2026-07-12 §2), AFTER the
                # point is saved so an excursion never costs data already taken.
                # This loop reads the scope directly and never went through
                # _acquire_core, so an IV sweep USED to drive HV to the setpoint
                # with NO temperature/humidity interlock: an ALARM could not
                # ramp HV down.  WARN -> safe-hold (HV held); ALARM -> fail-safe
                # abort (HV to 0 V, output off).
                self._apply_slow_control_policy(self._slow_control_read_all(), bias)
                if self._abort_event.is_set():
                    break

            # Ramp back to 0 V
            bias.ramp_to(0.0, step_V=20.0, delay_s=0.05)
            bias.output_off()

            self._settle_terminal_state()
        except Exception as exc:
            logger.exception("Voltage scan error")
            # on_error BEFORE the settle (see _settle_error_state).
            self._fire_error(str(exc))
            self._settle_error_state()
        finally:
            # Isolated best-effort blocks: a wavegen fault must not skip the
            # HV ramp-down, and a failed ramp must not skip output-off (same
            # layering as _bias_failsafe / the M1 emergency-off fix).
            try:
                dev.waveform_generator.output_off()
            except Exception:
                pass
            try:
                bias.ramp_to(0.0, step_V=20.0, delay_s=0.05)
            except Exception:
                pass
            try:
                bias.output_off()
            except Exception:
                pass
            self._motor_stop_safe()
            self._end_run()
            if self.on_finished:
                self.on_finished()

    # ------------------------------------------------------------------ #
    # Plan executor (runs in background thread)                           #
    # ------------------------------------------------------------------ #

    def _run_plan(
        self, plan: ScanPlan, steps: list, bias: BiasChannel, gate: DangerGate
    ) -> None:
        """Execute a compiled :class:`ScanPlan` on the worker thread.

        Modeled on :meth:`_run`: cooperative pause/abort between every step, the
        same terminal-state resolution, and a fail-safe ``finally``.  Danger
        steps are gated through *gate* — HV ramp per ``BiasStep``, stage motion
        once at run level (see :meth:`_move_action`) — and a denied confirmation
        is treated as a clean user abort.  On resume from a pause the last
        commanded HV set point is re-asserted (:meth:`_reassert_bias`) because
        the compiled ``BiasStep`` list is deduped and would otherwise skip the
        re-ramp.

        Documented deviation from _run (safety-driven): because a plan *drives*
        HV, the ``finally`` additionally leaves HV safe (ramp to 0 + output off)
        whenever the run contained a ``BiasStep`` — mirroring the HV-active
        :meth:`_run_voltage_scan`, not the HV-passive :meth:`_run`.
        """
        self._bias_read_failures = 0
        self._reassert_pending = False
        has_bias_step = False
        last_result: ScanResult | None = None
        last_bias_target: float | None = None
        # Ramp shaping of the last commanded BiasStep, re-applied on resume so a
        # shaped ramp stays shaped across a pause (None = driver default shape).
        last_bias_step_V: float | None = None
        last_bias_delay_s: float | None = None
        move_confirmed = False
        acq_index = -1
        saved = 0

        try:
            # steps are compiled once in start_plan and handed in — no recompile.
            has_bias_step = any(isinstance(s, BiasStep) for s in steps)
            total_saves = sum(1 for s in steps if isinstance(s, SaveStep))
            logger.info("Plan started: %d steps (%d save point(s))",
                        len(steps), total_saves)
            self._begin_run("recipe_plan", plan)

            for step in steps:
                # -- cooperative pause / resume-with-HV-reassert / abort ------
                # The park supervises the parked run (a plan pause HOLDS HV at
                # the last set point) — see _park_while_paused.
                self._park_while_paused(bias)
                if self._abort_event.is_set():
                    break
                if self._reassert_pending:
                    self._reassert_pending = False
                    self._reassert_bias(bias, last_bias_target,
                                        last_bias_step_V, last_bias_delay_s)

                # -- explicit dispatch (fail closed on anything unknown) ------
                if isinstance(step, MoveStep):
                    # One authoritative motion confirm per run (not per point).
                    if not move_confirmed:
                        if not gate.confirm(self._move_action(steps)):
                            self._deny_abort(
                                bias, has_bias_step,
                                "Stage motion not confirmed — plan aborted.")
                            break
                        move_confirmed = True
                    self._command_move(step)

                elif isinstance(step, BiasStep):
                    if not self._hv_armed:            # defense in depth
                        self._deny_abort(
                            bias, has_bias_step,
                            "HV not armed — refusing bias ramp mid-plan.")
                        break
                    action = DangerAction(
                        kind="hv_ramp",
                        summary=f"Ramp CH{bias.channel} to {step.target_V:g} V",
                        detail={"channel": bias.channel, "target_V": step.target_V},
                    )
                    if not gate.confirm(action):
                        self._deny_abort(
                            bias, has_bias_step,
                            f"HV ramp to {step.target_V:g} V not confirmed — "
                            "plan aborted.")
                        break
                    self._ramp_bias(bias, step.target_V,
                                    step.ramp_step_V, step.ramp_delay_s)
                    last_bias_target = step.target_V
                    last_bias_step_V = step.ramp_step_V
                    last_bias_delay_s = step.ramp_delay_s

                elif isinstance(step, AcquireStep):
                    pos = self._dev.motor.get_position()
                    acq_index += 1
                    point = ScanPoint(x_mm=pos.x_mm, y_mm=pos.y_mm,
                                      z_mm=pos.z_mm, index=acq_index)
                    last_result = self._acquire_core(point, step.n_averages, bias)
                    if self._check_compliance(bias, context=f" at acquire {acq_index}"):
                        break

                elif isinstance(step, SaveStep):
                    # SAVE_POINT persists the most recent acquire; a save with
                    # nothing acquired is a no-op (validator already WARNs).
                    if last_result is not None:
                        self._writer.save_point(last_result)
                        saved += 1
                        if self.on_point_done:
                            self.on_point_done(last_result)
                        if self.on_progress:
                            self.on_progress(saved, total_saves)

                elif isinstance(step, WaitStep):
                    self._abortable_sleep(step.seconds)

                elif isinstance(step, ManualPauseStep):
                    # Block for a human action; resumes via the existing
                    # resume().  Surface the prompt so the operator knows what to
                    # do (on_progress carries no message).
                    self._pause_event.clear()
                    self._reassert_pending = True
                    if self._sm.can(AppState.PAUSED):
                        self._sm.transition(AppState.PAUSED)
                    if self.on_manual_pause:
                        self.on_manual_pause(step.prompt)

                elif isinstance(step, ReadSlowControlStep):
                    # Sample the slow-control sensors AND enforce the excursion
                    # policy (WARN -> safe-hold pause, ALARM -> fail-safe abort).
                    readings = self._slow_control_read_all()
                    self._apply_slow_control_policy(readings, bias)

                else:  # pragma: no cover - Step is a closed union
                    raise ValueError(f"unhandled plan step: {type(step).__name__}")

            # -- terminal state (ONE shared, race-safe implementation) --------
            # A plan whose last executable step is a ManualPauseStep exits the
            # loop in PAUSED with everything acquired/saved; PAUSED has no
            # FINISHED edge, so the helper promotes through RUNNING (and
            # can()-guards every edge against a GUI pause/resume race).
            self._settle_terminal_state()

        except Exception as exc:
            logger.exception("Plan error")
            # on_error FIRST (same rule as the classic loops): a state settle
            # that loses a race with a GUI pause/resume must never swallow the
            # operator's only view of the original fault.
            self._fire_error(str(exc))
            # PAUSED cannot transition straight to ERROR (a ManualPauseStep can
            # leave us there); _settle_error_state promotes through RUNNING,
            # can()-guards every edge and swallows a lost race, so a terminal
            # state is always reached and the error transition never re-raises.
            self._settle_error_state()
        finally:
            self._hv_armed = False        # arm is per-run; never sticky
            # Fail-safe rule 5 ('stop motion'): halt any in-flight stage move on
            # EVERY exit path.  A fault DURING a move (e.g. wait_until_ready
            # raising) would otherwise let the stage keep driving to target.
            # Isolated best-effort (see _motor_stop_safe) so a dead motor link
            # can neither mask the original error nor skip the HV/wavegen
            # fail-safe below; a no-op on a clean finish.
            self._motor_stop_safe()
            try:
                self._dev.waveform_generator.output_off()
            except Exception:
                logger.warning("Waveform-generator output_off failed", exc_info=True)
            if has_bias_step:
                # This run energized HV — leave it safe on EVERY exit path.
                self._bias_failsafe(bias)
            self._end_run()
            if self.on_finished:
                self.on_finished()

    # ------------------------------------------------------------------ #
    # Plan-executor helpers (shared / pure where possible)                #
    # ------------------------------------------------------------------ #

    def _command_move(self, step: MoveStep) -> None:
        """Command a plan ``MoveStep``, honoring None = "do not command".

        ``move_to`` needs absolute x/y/z, but a ``MoveStep`` leaves undriven
        axes ``None``.  We read the CURRENT position and substitute it for every
        None axis — **never 0.0** (that would drive an undriven axis to the
        hard-stop edge; the M2.2 BLOCKER regression).  Then wait for motion to
        finish.
        """
        cur = self._dev.motor.get_position()
        x = cur.x_mm if step.x_mm is None else step.x_mm
        y = cur.y_mm if step.y_mm is None else step.y_mm
        z = cur.z_mm if step.z_mm is None else step.z_mm
        self._dev.motor.move_to(x, y, z)
        self._dev.motor.wait_until_ready()

    def _move_action(self, steps: list) -> DangerAction:
        """Build the ONE run-level stage-motion confirmation.

        Design decision: the executor asks for a SINGLE motion confirmation
        before the first move of the run, not one per ``MoveStep``.  A raster is
        thousands of moves; per-move dialogs are unusable, and every individual
        move is already bounded by the motor's software limits
        (``SoftwareLimits.check`` runs inside ``move_to``).  So the operator
        authorizes "the stage will move within this envelope" once, and the
        driver limits protect each step.  The summary carries the real per-axis
        travel envelope so the operator sees where the stage will go.
        """
        n_moves = 0
        acc: dict[str, list[float]] = {"x_mm": [], "y_mm": [], "z_mm": []}
        for s in steps:
            if isinstance(s, MoveStep):
                n_moves += 1
                for name, val in (("x_mm", s.x_mm), ("y_mm", s.y_mm), ("z_mm", s.z_mm)):
                    if val is not None:
                        acc[name].append(val)
        env: dict[str, tuple[float, float] | None] = {"x_mm": None, "y_mm": None, "z_mm": None}
        parts: list[str] = []
        for name in ("x_mm", "y_mm", "z_mm"):
            vals = acc[name]
            if vals:
                env[name] = (min(vals), max(vals))
                parts.append(f"{name[0].upper()} {min(vals):g}..{max(vals):g} mm")
        span = "; ".join(parts) if parts else "current position"
        return DangerAction(
            kind="move",
            summary=f"Move stage within [{span}] ({n_moves} move(s))",
            detail={"envelope": env, "n_moves": n_moves},
        )

    def _ramp_bias(
        self,
        bias: BiasChannel,
        target_V: float,
        ramp_step_V: float | None = None,
        ramp_delay_s: float | None = None,
    ) -> None:
        """Ramp *bias* to *target_V*, honouring per-step ramp shaping when set.

        Both shaping fields None (absent) is byte-for-byte the historic
        ``bias.ramp_to(target_V)`` — the driver's default ramp shape.  When
        either is provided the ramp is shaped (``step_V`` as a magnitude,
        ``delay_s`` as the per-step dwell); the other keeps its ``ramp_to``
        default.  HV never steps unshaped when shaping is requested — ``ramp_to``
        always steps by ``step_V``, never a single unshaped jump.
        """
        if ramp_step_V is None and ramp_delay_s is None:
            bias.ramp_to(target_V)
            return
        # Defense in depth (the validator already rejects these at start_plan):
        # a non-positive step_V would make the driver's ramp loop forever, and a
        # negative delay would raise in time.sleep — in either case drop the bad
        # kwarg and fall back to the driver's safe default rather than forward a
        # hazardous value.  The HV is still ramped (never a single unshaped jump).
        kwargs: dict = {}
        if ramp_step_V is not None:
            step = abs(float(ramp_step_V))
            if step > 0.0:
                kwargs["step_V"] = step
        if ramp_delay_s is not None:
            delay = float(ramp_delay_s)
            if delay >= 0.0:
                kwargs["delay_s"] = delay
        bias.ramp_to(target_V, **kwargs)

    def _reassert_bias(
        self,
        bias: BiasChannel,
        target_V: float | None,
        ramp_step_V: float | None = None,
        ramp_delay_s: float | None = None,
    ) -> None:
        """Re-establish the last commanded HV set point after a pause→resume.

        ``compile_plan`` dedups BiasSteps, so resuming "from step N" would skip
        the re-ramp and keep acquiring at a bias the executor only *assumes* is
        still applied (TECH_DEBT RISK, M2.2).  We never trust the deduped list:
        on resume we re-read the supply (surfacing a dead link) and re-ramp to
        the last commanded target, re-applying its ramp shaping so a shaped ramp
        stays shaped across the pause.  No-op when nothing was commanded yet or
        HV is not armed.  A failing re-ramp propagates → the run fails safe
        (ERROR + HV-safe ``finally``).
        """
        if target_V is None or not self._hv_armed:
            return
        logger.info("Resume: re-asserting HV to last commanded %.3g V", target_V)
        try:
            bias.read()
        except Exception:
            logger.warning("Bias re-read on resume failed", exc_info=True)
        self._ramp_bias(bias, target_V, ramp_step_V, ramp_delay_s)

    def _deny_abort(self, bias: BiasChannel, has_bias_step: bool, msg: str) -> None:
        """Treat a refused danger confirmation as a clean user abort.

        Sets the abort event and surfaces *msg* via ``on_error``; if this run
        energized HV, runs the bias fail-safe so a denied ramp never leaves the
        supply hot.  The caller then ``break``s and the terminal block resolves
        ABORTED.
        """
        logger.info("Danger confirmation denied: %s", msg)
        self._abort_event.set()
        self._fire_error(msg)
        if has_bias_step:
            self._bias_failsafe(bias)

    @staticmethod
    def _status_word_hint(reading) -> str:
        """`` (status word 0x00A1)`` when the raw word is known, else ``''``."""
        word = getattr(reading, "status_word", None)
        if isinstance(word, int) and not isinstance(word, bool):
            return f" (status word 0x{word:04X})"
        return ""

    @staticmethod
    def _driver_believes_output_on(bias: BiasChannel) -> bool:
        """What the DRIVER thinks the output state is — local flag, no hardware I/O.

        Read the *believed* state, never the switch-ON action.  The energize
        action is ``BiasChannel.enable_output`` (formerly the footgun
        ``output_on`` — a method that is always truthy and one missing ``()``
        from turning HV on; that name no longer exists, so a stale read now
        raises AttributeError instead of silently reading "always on").  The
        driver's per-channel belief is ``output_is_on_ch``, a pure local-state
        read on every backend.

        A backend that cannot answer gives us no belief to contradict, so this
        reports ``False``: no belief, no fault claim, never a spurious abort.
        """
        try:
            return bool(bias.driver.output_is_on_ch(bias.channel))
        except Exception:
            return False

    def _bias_hw_fault(self, bias: BiasChannel, reading) -> str | None:
        """Decode a HARDWARE fault out of a :class:`BiasReading` — else ``None``.

        The iseg driver decodes the module's channel-status word into ``tripped``
        / ``output_on_hw`` (raw word kept on ``status_word``); *reacting* to it is
        the controller's job, and this is that half.  Two faults, both meaning
        "the HV is not doing what was asked":

        * ``tripped is True`` — the module latched a protective fault
          (over-current trip, arc error, emergency off).  Safety rule 5: never
          continue after a safety-critical hardware error.
        * ``output_on_hw is False`` while the DRIVER still believes the channel
          is ON — the output went away behind our back (trip, inhibit, front
          panel).  Acquiring on would silently record UNBIASED data as if biased.

        Why this must be checked *before* ``compliant`` (Mary, review of c269e93):
        on a real current trip the module switches the channel off ITSELF, so the
        measured current collapses to ~0 and ``compliant`` computes to False — no
        compliance breach.  A compliance-only guard therefore sees a perfectly
        healthy sensor and the scan keeps acquiring and writing points with the HV
        OFF, recorded in HDF5 as if biased.  Physically worthless data, silently.

        **Tri-state discipline — ``is True`` / ``is False``, never truthiness.**
        Both flags are ``None`` = UNKNOWN whenever the backend cannot read a
        status word (simulated supplies, Keithley/e4control, or a failed
        ``:READ:CHAN:STAT?`` on the iseg itself).  ``if not reading.tripped``
        would turn "I don't know" into a confident "not tripped" — exactly the
        trap that hid the trip in the first place.  UNKNOWN is neither healthy nor
        a fault: it must not be read as safe, and it must not abort a run either
        (every non-status-reporting backend would become unusable).  It stays
        UNKNOWN, and this returns ``None``.
        """
        if getattr(reading, "tripped", None) is True:
            return ("Bias supply reports a LATCHED TRIP"
                    f"{self._status_word_hint(reading)} — the HV is not doing "
                    "what was asked")
        if (getattr(reading, "output_on_hw", None) is False
                and self._driver_believes_output_on(bias)):
            return ("Bias output is OFF at the hardware while the driver believes "
                    f"it is ON{self._status_word_hint(reading)} — the channel "
                    "switched off behind the scan")
        return None

    def _bias_fault_abort(
        self, bias: BiasChannel, reading, context: str = ""
    ) -> bool:
        """Abort + fail-safe if *reading* carries a hardware fault; else ``False``.

        The single reaction point for :meth:`_bias_hw_fault`, shared by every loop
        that evaluates a ``BiasReading``.  Sets the abort event (so the run's
        terminal state resolves **ABORTED**, never FINISHED — same discipline as
        the compliance-break path), surfaces the fault through ``on_error``, and
        leaves HV safe (ramp to 0 V + output off).  Data already taken is kept and
        the writer is still flushed/closed by ``_end_run``.
        """
        fault = self._bias_hw_fault(bias, reading)
        if fault is None:
            return False
        logger.error("%s%s — aborting the run (fail-safe)", fault, context)
        self._abort_event.set()
        self._fire_error(
            f"{fault}{context}.\n"
            "Scan ABORTED — bias ramped to 0 V and the output opened.\n"
            "Data taken before the fault is preserved."
        )
        self._bias_failsafe(bias)
        return True

    def _check_compliance(self, bias: BiasChannel, context: str = "") -> bool:
        """Post-acquire bias hardware-fault / compliance / readability guard.

        Shared by every run loop (``_run``, ``_run_plan``, and the paused-run park
        watchdog :meth:`_supervise_parked_run`), so all of them inherit all three
        guards from ONE implementation.  Returns ``True`` when the run must STOP —
        the caller ``break``s; the abort event is already set and the supply is
        already ramped down.  Returns ``False`` to continue.

        Order matters:

        1. **Hardware fault** (:meth:`_bias_hw_fault`) — a latched trip, or an
           output the hardware says is OFF while the driver believes it is ON.
           Checked FIRST because a real trip opens the channel inside the module:
           the current then falls to ~0 and the compliance test below sees nothing
           wrong (see :meth:`_bias_hw_fault`).
        2. **Compliance** — the DUT is drawing the compliance limit.
        3. **Readability** — :class:`DeviceError` after 3 consecutive unreadable
           reads (compliance protection is then unavailable, so the run fails safe
           rather than cook a sensor blind).  A single failing read is tolerated as
           a transient glitch; the counter resets on any good read.
        """
        if not bias.connected:
            return False
        try:
            reading = bias.read()
        except Exception as exc:
            self._bias_read_failures += 1
            logger.warning("Bias read failed during scan (%d/3): %s",
                           self._bias_read_failures, exc)
            if self._bias_read_failures >= 3:
                raise DeviceError(
                    "Bias supply unreadable for 3 consecutive points — "
                    "compliance protection unavailable, scan aborted."
                ) from exc
            return False
        self._bias_read_failures = 0
        if self._bias_fault_abort(bias, reading, context):
            return True
        if not reading.compliant:
            return False
        logger.warning("Compliance hit during scan%s — aborting", context)
        self._abort_event.set()
        self._fire_error(
            f"Bias compliance trip{context} "
            f"({reading.voltage_V:.1f} V, I={reading.current_A*1e6:.2f} µA).\n"
            "Scan aborted. Bias ramped to 0 V."
        )
        self._bias_failsafe(bias)
        return True

    def _bias_failsafe(self, bias: BiasChannel) -> None:
        """Ramp bias to 0 V then open the output — best-effort, SEPARATE tries.

        The output-off is the safety-critical step after a trip / deny / abort
        and must run even if the ramp-down raises, so the two are independently
        guarded (the same discipline as the original inline compliance block).
        """
        try:
            bias.ramp_to(0.0, step_V=20.0, delay_s=0.05)
        except Exception:
            logger.warning("Fail-safe bias ramp-down failed", exc_info=True)
        try:
            bias.output_off()
        except Exception:
            logger.warning("Fail-safe bias output-off failed", exc_info=True)

    def _motor_stop_safe(self) -> None:
        """Best-effort halt of all stage axes; never raises.

        Fail-safe rule 5 ('stop motion'): on a fault- or abort-driven exit an
        in-flight move must be halted.  Isolated in its own try/except (the same
        discipline as :meth:`_bias_failsafe`) so a dead motor link can neither
        mask the original error nor skip the bias fail-safe.  ``stop()`` is
        documented safe-to-call-at-any-time, so this is a harmless no-op on a
        clean finish or when the stage is already idle.
        """
        try:
            self._dev.motor.stop()
        except Exception:
            logger.warning("Fail-safe motor stop failed", exc_info=True)

    def _abortable_sleep(self, seconds: float) -> None:
        """Sleep up to *seconds*, in <=0.1 s slices, returning early on abort."""
        deadline = time.monotonic() + max(0.0, float(seconds))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0 or self._abort_event.is_set():
                return
            time.sleep(min(0.1, remaining))

    def _acquire_point(self, point: ScanPoint, cfg: ScanConfig, bias: BiasChannel) -> ScanResult:
        dev = self._dev

        # 1. Move
        dev.motor.move_to(point.x_mm, point.y_mm, point.z_mm)
        dev.motor.wait_until_ready()

        # 2. Settle
        time.sleep(cfg.settle_time_s)

        # 3+. Camera + averaged waveform acquisition (shared with the plan
        #     executor — see _acquire_core).
        return self._acquire_core(point, max(cfg.n_averages, 1), bias)

    def _acquire_core(
        self, point: ScanPoint, n_averages: int, bias: BiasChannel
    ) -> ScanResult:
        """Camera frame + averaged waveform acquisition at the CURRENT position.

        Factored out of :meth:`_acquire_point` so the classic scan loop and the
        plan executor share ONE acquisition body.  The **caller owns move +
        settle** (the plan does them as separate ``MoveStep`` / ``WaitStep``);
        this does the camera grab, the ``n_averages`` acquire/average loop, the
        per-point bias/slow-control context, the charge calibration, and builds
        the :class:`ScanResult`.
        """
        dev = self._dev
        n = max(int(n_averages), 1)

        # 3. Camera frame
        try:
            frame = dev.camera.get_frame()
        except Exception:
            frame = None

        # 4. Enable laser trigger, acquire, disable
        dev.waveform_generator.output_on()
        time.sleep(0.01)  # let oscilloscope arm

        ref_readings = []
        dut_results: list[WaveformResult] = []

        for _ in range(n):
            ref = dev.intensity_monitor.read()
            ref_readings.append(ref)

            time_axis, dut_wfm = dev.scope.read_channel(2)
            dut_res = analyse_waveform(time_axis, dut_wfm, **self._dev.analysis_kwargs)
            dut_results.append(dut_res)

        dev.waveform_generator.output_off()

        # 5. Average
        ref_amp  = float(np.mean([r.amplitude_V for r in ref_readings]))
        ref_chg  = float(np.mean([r.charge_pC   for r in ref_readings]))
        dut_amp  = float(np.mean([r.amplitude_V for r in dut_results]))
        dut_chg  = float(np.mean([r.charge_pC   for r in dut_results]))
        baseline = float(np.mean([r.baseline_rms_V for r in dut_results]))

        dut_chg_norm = normalise(dut_chg, ref_chg)

        # Average drift time (None if no valid measurements)
        drift_vals  = [r.drift_time_s  for r in dut_results if r.drift_time_s  is not None]
        rise_vals   = [r.rise_time_s   for r in dut_results if r.rise_time_s   is not None]
        cfd_vals    = [r.cfd_time_s    for r in dut_results if r.cfd_time_s    is not None]
        onset_vals  = [r.onset_time_s  for r in dut_results if r.onset_time_s  is not None]
        drift_time_s: float | None = float(np.mean(drift_vals))  if drift_vals  else None
        rise_time_s:  float | None = float(np.mean(rise_vals))   if rise_vals   else None
        cfd_time_s:   float | None = float(np.mean(cfd_vals))    if cfd_vals    else None
        onset_time_s: float | None = float(np.mean(onset_vals))  if onset_vals  else None

        last_ref = ref_readings[-1]
        last_dut = dut_results[-1]

        # Measured per-point context (not recomputable offline) — best-effort.
        bias_v = bias_i = None
        try:
            br = bias.read()
            bias_v, bias_i = float(br.voltage_V), float(br.current_A)
        except Exception:
            pass
        # One slow-control read serves BOTH the per-point snapshot (values in the
        # ScanResult) and the excursion policy (WARN safe-hold / ALARM fail-safe),
        # so a drifting simulated sensor can't disagree between the two.
        sc_readings = self._slow_control_read_all()
        sc_snapshot = self._snapshot_values(sc_readings)
        self._apply_slow_control_policy(sc_readings, bias)

        # Absolute-charge calibration (no-op until a calibration is configured).
        dut_chg_cal, chg_units = self._apply_charge_calibration(dut_chg)

        return ScanResult(
            point=point,
            timestamp=time.time(),
            ref_amplitude_V=ref_amp,
            ref_charge_pC=ref_chg,
            dut_amplitude_V=dut_amp,
            dut_charge_pC=dut_chg,
            dut_charge_norm=dut_chg_norm,
            baseline_rms_V=baseline,
            drift_time_s=drift_time_s,
            rise_time_s=rise_time_s,
            cfd_time_s=cfd_time_s,
            onset_time_s=onset_time_s,
            camera_frame=frame,
            ref_waveform=last_ref.waveform_V,
            dut_waveform=last_dut.waveform_V,
            time_axis=last_dut.time_s,
            bias_voltage_V=bias_v,
            bias_current_A=bias_i,
            slow_control=sc_snapshot,
            dut_charge_cal=dut_chg_cal,
            charge_units=chg_units,
        )

    def _slow_control_read_all(self) -> dict:
        """One snapshot of every slow-control channel, keyed by name.

        Returns ``{name: SlowControlReading}`` (each reading carries an evaluated
        :class:`~devices.slow_control_base.AlarmStatus`), or ``{}`` if the manager
        is absent or the read fails wholesale — a slow-control read must never
        crash the scan loop, only feed the excursion policy.
        """
        try:
            return self._dev.slow_control.read_all()
        except Exception:
            logger.warning("Slow-control read_all failed", exc_info=True)
            return {}

    def _snapshot_values(self, readings: dict) -> dict | None:
        """Reduce readings to ``{name: value}`` for the ScanResult, or None."""
        snap: dict[str, float] = {}
        for name, reading in readings.items():
            val = getattr(reading, "value", reading)
            try:
                snap[name] = float(val)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        return snap or None

    def _read_slow_control_snapshot(self) -> dict | None:
        """Back-compat wrapper: values-only snapshot (no policy).  Kept so any
        external caller keeps working; the run loops use ``_slow_control_read_all``
        + ``_apply_slow_control_policy`` so a single read feeds both."""
        return self._snapshot_values(self._slow_control_read_all())

    # ------------------------------------------------------------------ #
    # Slow-control excursion policy (DECISIONS 2026-07-12)                 #
    #                                                                      #
    #   WARN or UNAVAILABLE/stale -> SAFE-HOLD PAUSE (motion stopped, HV   #
    #     HELD at setpoint, run -> PAUSED, operator prompt via the         #
    #     manual-pause seam; operator Resumes or Aborts).                  #
    #   ALARM -> FULL FAIL-SAFE ABORT (HV ramp-down, motion stop, writer   #
    #     flushed via _end_run; on_error carries channel/value/threshold). #
    #   Once per excursion: a per-channel latch suppresses a re-pause on   #
    #     an ongoing WARN after the operator acks, until it reads OK again.#
    # ------------------------------------------------------------------ #

    _WARN_STATUSES = frozenset({AlarmStatus.WARN_LOW, AlarmStatus.WARN_HIGH})
    _ALARM_STATUSES = frozenset({AlarmStatus.ALARM_LOW, AlarmStatus.ALARM_HIGH})

    def _apply_slow_control_policy(self, readings: dict, bias: BiasChannel) -> None:
        """Enforce the WARN/ALARM excursion policy on a slow-control snapshot.

        Called on the worker thread from the shared acquisition body
        (:meth:`_acquire_core`) and from a plan ``READ_SLOW_CONTROL`` step, so it
        protects both the classic scan loop and the plan executor.  ALARM has
        priority over WARN.  No-op when nothing is configured / already aborting.
        """
        if not readings or self._abort_event.is_set():
            return

        thresholds = {
            getattr(ch, "name", None): getattr(ch, "thresholds", None)
            for ch in self._safe_slow_channels()
        }

        alarms: list[tuple] = []
        warns: list[tuple] = []
        for name, reading in readings.items():
            status = getattr(reading, "status", None)
            if status is AlarmStatus.OK:
                self._sc_latched.discard(name)   # excursion resolved
                continue
            if status in self._ALARM_STATUSES:
                alarms.append((name, reading, status, thresholds.get(name)))
            elif status in self._WARN_STATUSES or status is AlarmStatus.UNAVAILABLE:
                if name not in self._sc_latched:
                    warns.append((name, reading, status, thresholds.get(name)))

        if alarms:
            self._slow_control_alarm_abort(alarms, bias)
            return
        if warns:
            # Latch every new excursion first (so a persisting WARN never
            # re-pauses after ack), then safe-hold once if we're still RUNNING.
            for name, *_ in warns:
                self._sc_latched.add(name)
            self._slow_control_warn_hold(warns)

    def _slow_control_warn_hold(self, warns: list[tuple]) -> None:
        """Safe-hold PAUSE: motion stopped, HV HELD at setpoint, operator prompt.

        Only enters the hold from RUNNING — if the run is already PAUSED (another
        held excursion) or terminal, the channels are already latched and we must
        not stack a second prompt.
        """
        reason = ("Slow-control safe-hold — "
                  + "; ".join(self._sc_reading_desc(*w) for w in warns)
                  + ". Motion stopped, HV held at setpoint. Resume when safe, "
                    "or Abort.")
        logger.warning("%s", reason)
        if self._sm.state is not AppState.RUNNING:
            return
        # Motion stopped (a no-op between steps); HV is HELD — we do NOT ramp it
        # down on a WARN, only ALARM does that.
        self._motor_stop_safe()
        self._pause_event.clear()
        self._reassert_pending = True     # plan re-asserts the held HV on resume
        if self._sm.can(AppState.PAUSED):
            self._sm.transition(AppState.PAUSED)
        if self.on_manual_pause:
            self.on_manual_pause(reason)

    def _slow_control_alarm_abort(self, alarms: list[tuple], bias: BiasChannel) -> None:
        """Full fail-safe ABORT: HV ramp-down, motion stop, writer flushed.

        Mirrors a compliance trip / denied confirmation: set the abort event,
        halt motion, ramp HV to 0 + open the output (an ALARM de-energizes HV
        regardless of whether the run itself drove it), and surface the reason.
        The writer is flushed by ``_end_run`` on the loop's fail-safe exit.
        """
        reason = ("Slow-control ALARM — scan aborted (fail-safe): "
                  + "; ".join(self._sc_reading_desc(*a) for a in alarms)
                  + ". HV ramped to 0 V, motion stopped.")
        logger.error("%s", reason)
        self._abort_event.set()
        self._pause_event.set()           # unblock if a prior hold parked us
        self._motor_stop_safe()
        if bias is not None and getattr(bias, "connected", False):
            self._bias_failsafe(bias)     # ramp to 0 V + output off
        self._fire_error(reason)

    def _safe_slow_channels(self) -> list:
        """The slow-control channel objects (for threshold lookup), or []."""
        try:
            return list(self._dev.slow_control.channels)
        except Exception:
            return []

    def _sc_reading_desc(self, name, reading, status, thresholds) -> str:
        """One human clause carrying channel + value + crossed threshold + unit."""
        unit = (getattr(reading, "unit", "") or "").strip()
        unit_sfx = f" {unit}" if unit else ""
        if status is AlarmStatus.UNAVAILABLE:
            return f"{name} sensor unavailable/stale"
        value = getattr(reading, "value", float("nan"))
        thr = self._crossed_threshold(status, thresholds)
        band = "warn" if status in self._WARN_STATUSES else "alarm"
        side = "low" if status in (AlarmStatus.WARN_LOW, AlarmStatus.ALARM_LOW) else "high"
        thr_txt = "" if thr is None else f" {thr:g}{unit_sfx}"
        return (f"{name} = {value:g}{unit_sfx} crossed {band}_{side}{thr_txt}")

    @staticmethod
    def _crossed_threshold(status, thresholds) -> float | None:
        """The configured threshold value the *status* crossed, or None."""
        if thresholds is None:
            return None
        attr = {
            AlarmStatus.WARN_LOW:  "warn_low",
            AlarmStatus.WARN_HIGH: "warn_high",
            AlarmStatus.ALARM_LOW: "alarm_low",
            AlarmStatus.ALARM_HIGH: "alarm_high",
        }.get(status)
        if attr is None:
            return None
        val = getattr(thresholds, attr, None)
        try:
            return None if val is None else float(val)
        except (TypeError, ValueError):
            return None

    def _apply_charge_calibration(self, dut_charge_pC: float):
        """Map raw integrated charge to a calibrated value + units.

        Returns (calibrated_value, units) or (None, None) when no calibration is
        configured.  The calibration object lives on the DeviceManager (set up
        from the ``charge_calibration`` config block); absent until Phase 3 wiring.
        """
        cal = getattr(self._dev, "charge_calibration", None)
        if cal is None:
            return None, None
        try:
            return cal.apply(dut_charge_pC)
        except Exception:
            return None, None
