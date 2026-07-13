"""
Qt-side driver for the Scan Sequencer — the heart of the unattended overnight
routine queue (feature_requests_v5 §7; envelope option (a) ratified 2026-07-13).

``SequenceCoordinator`` is the GUI-thread controller that turns the pure,
headless :class:`~controller.sequencer.SequenceRunner` (queue STATE only) into a
live, event-driven run: it advances the queue off the
:class:`~gui.scan_coordinator.ScanCoordinator`'s plan-terminal signals, parks
hardware safe *between* entries via :meth:`ScanController.park_safe`, and drives
the whole night to completion or a fail-closed halt.  It owns NO threads and
NEVER blocks the Qt event loop: each entry's terminal signal drives the next
advance; :meth:`ScanCoordinator.execute_plan` spawns the worker and returns.

Composition, not logic (rule 5)
-------------------------------
This object is wired by the composition root (A5's panel + main-window wiring).
It holds the :class:`SequenceRunner` (pure engine), the shared
:class:`~controller.state_machine.StateMachine`, and a ``park_safe`` callable;
it talks to the acquisition stack ONLY through the ``ScanCoordinator`` seam
(``execute_plan`` / ``abort`` / ``plan_run_active`` + the ``plan_finished`` /
``plan_error`` signals).  Named physics stays in ``analysis/``; scan sequencing
semantics stay in ``controller/`` — this file is the widget-facing glue.

Mary's Track-A binding requirements (violating any is an auto-REQUEST-CHANGES)
-----------------------------------------------------------------------------
1. **The union :class:`ArmedEnvelopeGate` is PRIVATE.**  It is built in
   :meth:`build_gate`, stored in ``self._gate`` (no public ``gate`` attribute),
   and passed ONLY to :meth:`ScanCoordinator.execute_plan`.  It is NEVER wired
   into a manual panel — manual danger actions stay on the app's own
   ``QtDangerGate``.  The panel (A5) receives only the ``ArmedEnvelope`` +
   its ``summary`` to render over the Arm latch.
2. **Manual danger controls are disableable while a sequence runs.**  This
   object emits :attr:`sequence_active` — ``True`` at :meth:`arm_and_start`,
   ``False`` at every terminal (finish / halt / cancel / fail-closed).  A5 wires
   the manual HV / motion panels to it so they grey out for the duration of the
   unattended run and re-enable exactly once, when the sequence ends.
3. **Entries run DEEP-COPIED plan snapshots.**  :meth:`load` snapshots every
   plan via ``ScanPlan.from_dict(src.to_dict())`` so a later planner edit of the
   source object can never alias — and thus never widen — what the armed queue
   was authorized to command.  The combined envelope is derived over these
   snapshots too, so editing the source after arming cannot widen the envelope.

Abort → outcome mapping (how ``ScanCoordinator`` reports a run's end)
--------------------------------------------------------------------
``ScanCoordinator`` emits, per plan run, exactly one terminal this object
listens for (both are emitted AFTER the worker settled the state machine):

* ``plan_finished()`` — fired only when the run reached ``AppState.FINISHED``
  (a genuinely clean finish) → recorded outcome ``"finished"`` (DONE).
* ``plan_error(str)`` — fired for a fault (state ``ERROR``) AND for a
  deny/compliance abort (state ``ABORTED``); the state machine tells the two
  apart.  Mapped to ``"aborted"`` when the machine settled ``ABORTED``, else
  ``"error"``.  Both are non-``"finished"`` outcomes, so the engine FAILS the
  entry and HALTS the queue identically (fail-closed) — the word is the audit
  label only.  (An operator-initiated :meth:`abort_sequence` never routes
  through these slots: an operator abort fires no ``on_error`` and settles
  ``ABORTED``, surfacing only via ``plan_running(False)`` — which this object
  deliberately does not consume; the cancel is handled directly instead.)

``park_safe`` injection (why a Callable, not a controller reach)
----------------------------------------------------------------
``park_safe`` lives on :class:`ScanController`, which ``ScanCoordinator`` holds
privately (``_scanner``).  Reaching through that private attribute is fragile,
so the safe-park seam is an injected ``Callable[[], None]`` (default resolves
the controller's ``park_safe`` best-effort, else a logged no-op).  A5 wires
``park_safe=scan_controller.park_safe`` explicitly; tests inject a spy.  It is
called at the top of every advance (between entries and before finishing) and on
every teardown path.  It is fast in the normal case: the run's own fail-safe
already ramped HV to 0 and opened the output, so ``park_safe``'s ramp-to-0 hits
the driver's "output off → set register, return" fast path with no stepping.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from controller.arm_envelope import (
    ArmedEnvelope, ArmedEnvelopeGate, envelope_from_plans,
)
from controller.scan_plan import ScanPlan
from controller.sequencer import (
    EntryState, NullPreflight, PreflightHook, SequenceEntry, SequenceRunner,
    assert_sequencer_compatible,
)
from controller.state_machine import AppState, StateMachine

if TYPE_CHECKING:  # pragma: no cover - typing only; duck-typed at runtime
    from gui.scan_coordinator import ScanCoordinator

logger = logging.getLogger(__name__)


class SequenceCoordinator(QObject):
    """Event-driven driver for an unattended queue of saved scan routines.

    See the module docstring for the three Track-A binding requirements (private
    union gate, ``sequence_active`` manual-control gating, deep-copied
    snapshots), the abort→outcome mapping, and the ``park_safe`` injection
    rationale.

    Public control surface (the composition root connects panel signals here)::

        load(named_plans, *, source_paths=None)   build the deep-copied queue
        build_gate(channel) -> (ArmedEnvelope, ArmedEnvelopeGate)
        arm_and_start(gate=None)                   arm + drive the whole queue
        abort_sequence()                           operator panic → cancel + park

    Public signals (the composition root connects panel/dialog slots here)::

        entry_state_changed(int, str, str)   (row, EntryState value, message)
        sequence_progress(int, int)          (terminal entries, total)
        sequence_finished(str)               "finished"/"halted"/"cancelled"/"error"
        sequence_error(str)                  fail-closed reason (for a dialog)
        sequence_active(bool)                True at arm, False at every terminal
    """

    # (row, EntryState.value, message) — A5 updates the queue table row.
    entry_state_changed = Signal(int, str, str)
    # (entries in a terminal state, total entries).
    sequence_progress = Signal(int, int)
    # The single "the sequence is over" notification, with the outcome word.
    sequence_finished = Signal(str)
    # Fail-closed reason (an engine call raised); paired with a "error" finish.
    sequence_error = Signal(str)
    # True at arm_and_start, False at EVERY terminal — A5 gates manual danger
    # controls off this (req 2).  Emitted True exactly once per run and False
    # exactly once per run (never left dangling True after any failure path).
    sequence_active = Signal(bool)

    def __init__(
        self,
        scan_coordinator: "ScanCoordinator",
        state_machine: StateMachine,
        preflight: PreflightHook | None = None,
        park_safe: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._scan = scan_coordinator
        self._sm = state_machine
        self._preflight: PreflightHook = preflight or NullPreflight()
        self._park_safe: Callable[[], None] = self._resolve_park(park_safe)

        # Queue state (created in load()).
        self._entries: List[SequenceEntry] = []
        self._runner: Optional[SequenceRunner] = None
        # The union ArmedEnvelopeGate — PRIVATE (Mary req 1).  Never exposed via
        # a public attribute; passed ONLY to scan_coordinator.execute_plan.
        self._gate: Optional[ArmedEnvelopeGate] = None
        # Run flags.
        self._active = False           # a sequence is armed and driving
        self._entry_in_flight = False  # an entry's run is live (awaiting terminal)

        # Advance off the coordinator's post-settle plan terminals.  Both are
        # already marshalled onto the GUI thread by ScanCoordinator's bridge.
        self._scan.plan_finished.connect(self._on_plan_finished)
        self._scan.plan_error.connect(self._on_plan_error)

    # ------------------------------------------------------------------ #
    # Construction helpers                                                #
    # ------------------------------------------------------------------ #
    def _resolve_park(self, park_safe: Callable[[], None] | None) -> Callable[[], None]:
        """Prefer the injected callable; else best-effort the controller's
        ``park_safe``; else a logged no-op (a park seam must never be silently
        absent, but must also never crash the coordinator)."""
        if park_safe is not None:
            return park_safe
        scanner = getattr(self._scan, "_scanner", None)
        candidate = getattr(scanner, "park_safe", None)
        if callable(candidate):
            logger.debug("SequenceCoordinator: park_safe resolved from controller")
            return candidate

        def _noop_park() -> None:  # pragma: no cover - defensive fallback
            logger.warning(
                "SequenceCoordinator: no park_safe wired — between-entry park is "
                "a NO-OP; A5 must pass park_safe=scan_controller.park_safe")

        return _noop_park

    # ------------------------------------------------------------------ #
    # Load / arm                                                          #
    # ------------------------------------------------------------------ #
    def load(
        self,
        named_plans: Sequence[Tuple[str, ScanPlan]],
        *,
        source_paths: Sequence[Optional[str]] | None = None,
    ) -> None:
        """Build the queue from ``(name, plan)`` pairs — DEEP-COPIED snapshots.

        Refuses (``RuntimeError``) while a sequence is active: the armed queue is
        immutable for the duration of a run.  Each entry carries an independent
        ``ScanPlan.from_dict(plan.to_dict())`` snapshot (req 3), so later planner
        edits of the source objects can never alias the running queue.
        """
        if self._active:
            raise RuntimeError("cannot load a sequence while one is active")
        if source_paths is not None and len(source_paths) != len(named_plans):
            raise ValueError("source_paths length must match named_plans")

        # Fail-closed compatibility gate (Mary A5.2a) — run BEFORE building any
        # entry or touching self, so an unattended-incompatible plan (e.g. a
        # manual_pause) never shortens the queue, emits a row, or leaves the
        # coordinator half-loaded.  The raised reason (naming the routine) is
        # surfaced by the panel's fail-closed loader path (A5); the queue is not
        # silently dropped.
        for name, plan in named_plans:
            assert_sequencer_compatible(plan, name=str(name))

        entries: List[SequenceEntry] = []
        for i, (name, plan) in enumerate(named_plans):
            src = source_paths[i] if source_paths is not None else None
            snapshot = ScanPlan.from_dict(plan.to_dict())   # deep copy (req 3)
            entries.append(SequenceEntry(name=str(name), plan=snapshot,
                                         source_path=src))

        self._entries = entries
        self._runner = SequenceRunner(entries, preflight=self._preflight)
        self._gate = None
        self._entry_in_flight = False
        self._emit_all_rows()
        self._emit_progress()

    def build_gate(self, channel: int) -> Tuple[ArmedEnvelope, ArmedEnvelopeGate]:
        """Derive the ONE combined envelope over the loaded snapshots + its gate.

        Returns ``(envelope, gate)`` so A5 can render ``envelope.summary`` (which
        names every routine the single hold-3s authorizes) over the Arm latch.
        The gate is stored PRIVATELY (``self._gate``) and later handed ONLY to
        :meth:`ScanCoordinator.execute_plan`; A5 must not wire it anywhere else.

        ``channel`` is the resolved bias-supply channel index the HV envelope is
        attributed to.  Fail-closed: refuses when nothing is loaded (an empty
        queue can never be armed — ``envelope_from_plans`` also rejects it).
        """
        if self._runner is None or not self._entries:
            raise RuntimeError("no sequence loaded; call load() before build_gate()")
        plans = [e.plan for e in self._entries]
        names = [e.name for e in self._entries]
        env = envelope_from_plans(plans, int(channel), plan_names=names)
        gate = ArmedEnvelopeGate(env)
        self._gate = gate
        return env, gate

    def arm_and_start(self, gate: ArmedEnvelopeGate | None = None) -> None:
        """Arm the queue and drive it to completion (event-driven, non-blocking).

        Refuses if a plan run is already active (``scan_coordinator``) or a
        sequence is already active.  Emits ``sequence_active(True)`` FIRST (so A5
        greys out manual danger controls before the first entry arms HV), then
        starts the advance loop.  ``gate`` defaults to the one built by
        :meth:`build_gate`; passing it explicitly is equivalent.
        """
        if self._active:
            raise RuntimeError("a sequence is already active")
        if self._runner is None:
            raise RuntimeError("no sequence loaded; call load() first")
        if self._scan.plan_run_active:
            raise RuntimeError(
                "a plan run is already active; cannot start a sequence")
        if gate is not None:
            self._gate = gate
        if self._gate is None:
            raise RuntimeError(
                "no armed gate; call build_gate() before arm_and_start()")

        self._active = True
        self._entry_in_flight = False
        self.sequence_active.emit(True)   # req 2 — before any dangerous action
        self._start_next()

    # ------------------------------------------------------------------ #
    # Advance loop (GUI thread, event-driven off plan terminals)          #
    # ------------------------------------------------------------------ #
    def _start_next(self) -> None:
        """Park safe, then advance to the next entry — or finish the queue.

        The park at the top is the A3 between-entry safe assertion: it runs after
        the previous entry's outcome and before the next entry arms HV (and, when
        ``next_entry`` returns ``None``, it is the final park, so :meth:`_finish`
        does not re-park).
        """
        self._park()
        try:
            entry = self._runner.next_entry()   # type: ignore[union-attr]
        except Exception as exc:  # engine raised (e.g. a still-running entry)
            self._fail_closed(f"sequencer advance failed: {exc}")
            return

        if entry is None:            # queue exhausted OR a preflight veto halted
            self._finish()
            return

        # A preflight veto inside next_entry() marks the entry FAILED + SKIPs the
        # remainder and returns None (handled above), so a returned entry is
        # genuinely RUNNING and cleared to execute.
        self._recover_fsm_for_run()
        self._emit_all_rows()        # the entry is now RUNNING
        self._emit_progress()

        self._entry_in_flight = True
        try:
            self._scan.execute_plan(entry.plan, self._gate)
        except Exception as exc:     # execute_plan is meant to self-guard; belt+braces
            self._entry_in_flight = False
            self._record_and_advance("error")
            logger.warning("execute_plan raised: %s", exc)
            return
        # execute_plan self-guards refusals (state gate / start_plan raise) by
        # emitting a dialog and NOT setting plan_run_active — detect that here so
        # the queue halts fail-closed instead of hanging for a terminal that will
        # never come.
        if not self._scan.plan_run_active:
            self._entry_in_flight = False
            self._record_and_advance("error")

    def _recover_fsm_for_run(self) -> None:
        """Walk a terminal state back to READY so ``execute_plan`` can run.

        Between entries the machine sits in the previous entry's terminal
        (FINISHED / ERROR / ABORTED); ``execute_plan`` requires ``can(RUNNING)``,
        which only READY satisfies.  Every edge is ``can()``-guarded and a lost
        race (``ValueError``) is swallowed after re-reading — though between
        entries the worker has already exited, so no real race exists.  A no-op
        for the first entry (already READY).
        """
        if self._sm.can(AppState.RUNNING):
            return
        for target in (AppState.CONFIGURED, AppState.READY):
            try:
                if self._sm.can(target):
                    self._sm.transition(target)
            except ValueError:
                logger.debug("FSM recovery race → %s (state now %s)",
                             target.name, self._sm.state.name)

    @Slot()
    def _on_plan_finished(self) -> None:
        """A run reached FINISHED (clean) → record DONE and advance."""
        if not self._active or not self._entry_in_flight:
            return                      # stray / late signal (post-cancel etc.)
        self._entry_in_flight = False
        self._record_and_advance("finished")

    @Slot(str)
    def _on_plan_error(self, msg: str) -> None:
        """A run ended non-clean (fault → ERROR, or deny/compliance → ABORTED).

        Both halt the queue identically (fail-closed); the settled state machine
        supplies the audit word ("aborted" vs "error").  A benign settle race can
        label an aborted run "error" — cosmetic only, same halt.
        """
        if not self._active or not self._entry_in_flight:
            return
        self._entry_in_flight = False
        outcome = "aborted" if self._sm.state is AppState.ABORTED else "error"
        if msg:
            logger.info("sequence entry ended %s: %s", outcome, msg)
        self._record_and_advance(outcome)

    def _record_and_advance(self, outcome: str) -> None:
        """Record the run outcome into the engine, then advance the queue.

        Any engine raise (bad word / no-running-entry race) is caught → a
        fail-closed halt: never leave ``sequence_active`` dangling True.
        """
        try:
            self._runner.record_outcome(outcome)   # type: ignore[union-attr]
        except (ValueError, RuntimeError) as exc:
            self._fail_closed(f"record_outcome({outcome!r}) failed: {exc}")
            return
        self._emit_all_rows()
        self._emit_progress()
        self._start_next()

    def _finish(self) -> None:
        """The queue reached its end (all DONE, or halted with FAILED/SKIPPED).

        Already parked at the top of the final :meth:`_start_next`, so no re-park
        here.  Emits ``sequence_active(False)`` BEFORE ``sequence_finished`` (the
        pinned order across every terminal path) so the manual controls re-enable
        before A5 reacts to the completion word.
        """
        word = self._final_outcome_word()
        self._active = False
        self._entry_in_flight = False
        self._gate = None
        self._emit_all_rows()
        self._emit_progress()
        self.sequence_active.emit(False)
        self.sequence_finished.emit(word)

    def _final_outcome_word(self) -> str:
        """"finished" (all DONE) / "halted" (a FAILED culprit) / "cancelled"."""
        states = [e.state for e in self._entries]
        if any(s is EntryState.FAILED for s in states):
            return "halted"
        if any(s is EntryState.CANCELLED for s in states):
            return "cancelled"
        return "finished"

    # ------------------------------------------------------------------ #
    # Abort / fail-closed                                                 #
    # ------------------------------------------------------------------ #
    def abort_sequence(self) -> None:
        """Operator panic: cancel the queue, abort any live run, park, go idle.

        A no-op when no sequence is active (never touches hardware or a manual
        run — a manual operation may be running when no sequence is).  When
        active it cancels the engine (running + PENDING → CANCELLED), aborts the
        in-flight run's controller (fail-safe: HV→0, output off, motion stopped),
        parks belt-and-braces, and emits ``sequence_active(False)`` then
        ``sequence_finished("cancelled")``.  Idle-BETWEEN-entries (active, no run
        live) still cancels + parks + emits.
        """
        if not self._active:
            return
        run_live = self._entry_in_flight
        self._entry_in_flight = False
        if run_live:
            try:
                self._scan.abort()
            except Exception:
                logger.exception("scan_coordinator.abort() failed during abort_sequence")
        if self._runner is not None:
            try:
                self._runner.cancel()
            except Exception:
                logger.exception("runner.cancel() failed during abort_sequence")
        self._emit_all_rows()
        self._emit_progress()
        self._park()
        self._gate = None
        self._active = False
        self.sequence_active.emit(False)
        self.sequence_finished.emit("cancelled")

    def _fail_closed(self, reason: str) -> None:
        """An engine call raised: halt the night safe and surface the reason.

        Cancels the queue, aborts any live run, parks, and NEVER leaves
        ``sequence_active`` True.  Emits ``sequence_error(reason)`` (the why) then
        the standard ``sequence_active(False)`` + ``sequence_finished("error")``.
        """
        logger.error("SequenceCoordinator fail-closed: %s", reason)
        run_live = self._entry_in_flight
        self._entry_in_flight = False
        if run_live:
            try:
                self._scan.abort()
            except Exception:
                logger.exception("abort during fail-closed failed")
        if self._runner is not None:
            try:
                self._runner.cancel()
            except Exception:
                logger.exception("cancel during fail-closed failed")
        self._emit_all_rows()
        self._emit_progress()
        self._park()
        self._gate = None
        self.sequence_error.emit(reason)
        if self._active:
            self._active = False
            self.sequence_active.emit(False)
        self.sequence_finished.emit("error")

    # ------------------------------------------------------------------ #
    # Emission / park helpers                                             #
    # ------------------------------------------------------------------ #
    def _park(self) -> None:
        """Invoke the injected safe-park; never let it raise into the loop."""
        try:
            self._park_safe()
        except Exception:  # park_safe is documented never-raise; defend anyway
            logger.exception("park_safe raised during sequence teardown")

    def _emit_all_rows(self) -> None:
        if self._runner is None:
            return
        for i, e in enumerate(self._runner.entries):
            self.entry_state_changed.emit(i, e.state.value, e.message)

    def _emit_progress(self) -> None:
        if self._runner is None:
            return
        done, total = self._runner.progress
        self.sequence_progress.emit(done, total)

    # ------------------------------------------------------------------ #
    # Read-only observation (safe for A5 / tests; NEVER exposes the gate) #
    # ------------------------------------------------------------------ #
    @property
    def is_active(self) -> bool:
        """True while a sequence is armed and driving."""
        return self._active
