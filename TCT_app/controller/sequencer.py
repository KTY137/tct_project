"""
Scan-sequencer queue engine + persistence — pure, headless STATE only.

A :class:`SequenceRunner` is the state machine for an *unattended queue of saved
routines* (feature_requests_v5 §7; envelope semantics ratified 2026-07-13 as
option (a): ONE combined :class:`~controller.arm_envelope.ArmedEnvelope` over the
whole queue, with the executor re-validating every step at run time).  This
module owns ONLY the queue state — which entry is next, how a preflight veto or a
bad run outcome halts the night, what a mid-queue cancel does.  It contains:

* NO Qt — the Qt-side ``SequenceCoordinator`` (later beat, Noah) drives this off
  ``ScanCoordinator`` signals and renders the per-entry rows.
* NO threads — the runner never blocks; the coordinator owns the run loop and
  calls :meth:`SequenceRunner.next_entry` / :meth:`~SequenceRunner.record_outcome`
  between plan executions.
* NO device access — the engine never runs a plan, never touches HV or motion.
  ``ScanController.park_safe`` (A3) parks hardware safe *between* entries; that is
  the caller's job, not the engine's.

Fail-closed by construction
---------------------------
There is deliberately **NO continue-on-failure option in v1**.  An unattended
overnight queue must never keep energizing HV after an anomaly, so the FIRST
non-clean outcome (anything the executor reports other than ``"finished"`` —
``"error"`` / ``"aborted"`` / the ``"unknown"`` crash sentinel / any unexpected
word), the FIRST preflight veto, **or a preflight hook that raises** HALTS the
queue: the culprit entry is marked FAILED and every remaining PENDING entry
becomes SKIPPED.  A human decides what to do next morning — the machine does not
plough on into the next routine.  Likewise a malformed persisted entry raises
rather than yielding a silently shortened queue.

The armed envelope is derived over the INLINE plan snapshot each
:class:`SequenceEntry` carries (never a live re-read of the source YAML), so a
later edit of the source file can never widen what a running queue was
authorized to command.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml

from controller.scan_plan import ScanPlan

# Persisted-file schema version (see save/load below).
SEQUENCE_FILE_VERSION = 1

# The RECORDED run-outcome vocabulary — MUST match data/hdf5_writer.py
# VALID_OUTCOMES so the coordinator can hand the same word it wrote into the HDF5
# file straight to record_outcome().  "finished" is the only outcome that
# ADVANCES the queue; every other word HALTS it (see record_outcome).  This set
# is no longer a gate — record_outcome accepts ANY string and fails closed — it
# only distinguishes a standard bad-run word from an unexpected one in the log.
_VALID_OUTCOMES: frozenset[str] = frozenset({"finished", "aborted", "error"})


class EntryState(str, Enum):
    """Lifecycle of one queued routine.

    Non-terminal: PENDING (waiting), PREFLIGHT (hook running), RUNNING (executor
    driving it).  Terminal: DONE (clean finish), FAILED (bad outcome or preflight
    veto — the halt culprit), SKIPPED (a later entry the halt never reached),
    CANCELLED (operator aborted the sequence).
    """
    PENDING = "pending"
    PREFLIGHT = "preflight"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


#: Entry states from which nothing more will happen for that entry.
_TERMINAL: frozenset[EntryState] = frozenset({
    EntryState.DONE, EntryState.FAILED, EntryState.SKIPPED, EntryState.CANCELLED,
})
#: Non-terminal "in-flight" states — at most one entry may hold either.
_ACTIVE: frozenset[EntryState] = frozenset({
    EntryState.PREFLIGHT, EntryState.RUNNING,
})


@dataclass
class SequenceEntry:
    """One queued routine + its live state.

    ``plan`` is an INLINE SNAPSHOT of the :class:`ScanPlan` (not a path that gets
    re-read at run time): the combined arm envelope is derived over this snapshot,
    so editing the source YAML after the queue is armed can never widen the
    authorized envelope.  ``source_path`` is provenance only — where the routine
    was loaded from, for the operator's benefit; it is never dereferenced by the
    engine.
    """
    name: str
    plan: ScanPlan
    source_path: str | None = None
    state: EntryState = EntryState.PENDING
    message: str = ""


# --------------------------------------------------------------------------- #
# Preflight seam (interface only)                                             #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PreflightResult:
    """Verdict of a per-entry preflight check.  ``ok=False`` HALTS the queue."""
    ok: bool
    message: str = ""


@runtime_checkable
class PreflightHook(Protocol):
    """A per-entry check run just before an entry goes RUNNING.

    The camera-metrology re-focus/re-centre correction implements this in a LATER
    wave; here it is the interface only.  A hook must be pure w.r.t. queue state —
    it inspects the entry and returns a :class:`PreflightResult`; it never mutates
    entry state (the runner does that from the verdict).
    """

    def run(self, entry: SequenceEntry) -> PreflightResult: ...


class NullPreflight:
    """The default preflight: every entry passes.  No hardware, no side effects."""

    def run(self, entry: SequenceEntry) -> PreflightResult:  # noqa: D401 - trivial
        return PreflightResult(ok=True)


# --------------------------------------------------------------------------- #
# The queue engine                                                            #
# --------------------------------------------------------------------------- #

class SequenceRunner:
    """Pure state machine for an unattended routine queue.

    Drive loop (owned by the coordinator, NOT here)::

        while (entry := runner.next_entry()) is not None:
            park_safe()                 # A3: between-entry hardware park
            outcome = run_plan(entry.plan)   # coordinator drives the executor
            runner.record_outcome(outcome)   # HDF5 outcome word verbatim

    A preflight veto or any non-``"finished"`` outcome HALTS the queue (see the
    module docstring): there is no continue-on-failure.  Every state change
    appends a timestamped human line to :attr:`log` so the coordinator/GUI (and a
    post-mortem) can see exactly how the night unfolded.
    """

    def __init__(self, entries, preflight: PreflightHook | None = None) -> None:
        self.entries: list[SequenceEntry] = list(entries)
        self._preflight: PreflightHook = preflight or NullPreflight()
        self.log: list[str] = []
        self._append_log(f"sequence created with {len(self.entries)} entr"
                          f"{'y' if len(self.entries) == 1 else 'ies'}")

    # -- advance -----------------------------------------------------------
    def next_entry(self) -> SequenceEntry | None:
        """Advance to the next PENDING entry, running its preflight hook.

        Returns the entry (now RUNNING) when its preflight passes.  Returns
        ``None`` when the queue is exhausted OR when a preflight veto halted it.
        A preflight veto marks the entry FAILED with the hook's message and
        SKIPS every remaining PENDING entry (fail-closed halt).  A preflight hook
        that *raises* is treated identically to a veto: the engine owns the
        outcome, marking the entry FAILED with the exception text and halting the
        queue — it never relies on the coordinator to catch the exception (which
        would otherwise strand the entry in PREFLIGHT and wedge the queue).

        Raises :class:`RuntimeError` if an entry is still PREFLIGHT/RUNNING — the
        caller must :meth:`record_outcome` before advancing, so two entries can
        never be RUNNING (and energizing HV) at once.
        """
        active = self._active_entry()
        if active is not None:
            raise RuntimeError(
                f"cannot advance: entry {active.name!r} is still "
                f"{active.state.value}; record its outcome first"
            )

        entry = self._first_pending()
        if entry is None:
            return None

        self._set_state(entry, EntryState.PREFLIGHT)
        try:
            result = self._preflight.run(entry)
        except Exception as exc:
            # A hook that raises must not leave the entry stranded in PREFLIGHT
            # (the next next_entry() would then forever refuse to advance past
            # it).  Fail the culprit closed with the exception text and halt,
            # exactly as a veto verdict does — the engine, not the coordinator,
            # owns the outcome.
            self._set_state(entry, EntryState.FAILED, f"preflight error: {exc}")
            self._halt(EntryState.SKIPPED, "skipped: preflight halt")
            return None
        if not result.ok:
            self._set_state(entry, EntryState.FAILED,
                            result.message or "preflight rejected")
            self._halt(EntryState.SKIPPED, "skipped: preflight halt")
            return None

        self._set_state(entry, EntryState.RUNNING)
        return entry

    def record_outcome(self, outcome: str) -> None:
        """Record how the RUNNING entry's run ended.

        *outcome* is the HDF5 outcome word.  ONLY the literal ``"finished"``
        marks the entry DONE and clears the way for the next :meth:`next_entry`.
        EVERY other string — ``"aborted"`` / ``"error"``, the ``"unknown"``
        crash sentinel, or any unexpected word — marks the entry FAILED and HALTS
        the queue (remaining PENDING → SKIPPED); there is no continue-on-failure.
        The exact word is recorded in the entry message.

        This is deliberately fail-closed on ANY non-``"finished"`` word rather
        than raising on an unrecognized one: ``data/hdf5_writer.py`` legitimately
        persists ``"unknown"`` (its ``UNKNOWN_OUTCOME`` sentinel) when a run
        process dies without recording a clean outcome — and that crashed-run
        word is EXACTLY the outcome that most needs to halt an unattended
        overnight queue.  A raise here would escape the engine and could strand
        the sequence, so the most-dangerous outcome must never throw.

        Raises :class:`RuntimeError` if no entry is RUNNING — that is a caller
        sequencing bug (record_outcome before any next_entry), not a run outcome.
        """
        entry = self._running_entry()
        if entry is None:
            raise RuntimeError(
                "record_outcome called with no RUNNING entry"
            )

        if outcome == "finished":
            self._set_state(entry, EntryState.DONE)
            return
        # Any non-"finished" word halts the queue.  Record the exact word;
        # flag words outside the standard recorded vocabulary (VALID_OUTCOMES)
        # so a morning post-mortem can tell a real bad-run outcome from a caller
        # slip — both still halt.  ("unknown" is genuinely non-standard: see
        # hdf5_writer's UNKNOWN_OUTCOME, "Deliberately NOT one of VALID_OUTCOMES".)
        suffix = "" if outcome in _VALID_OUTCOMES else " (non-standard)"
        self._set_state(entry, EntryState.FAILED, f"run outcome: {outcome}{suffix}")
        self._halt(EntryState.SKIPPED, "skipped after halt")

    def cancel(self) -> None:
        """Operator aborted the sequence: cancel the running entry + all PENDING.

        The RUNNING/PREFLIGHT entry (if any) and every remaining PENDING entry
        become CANCELLED with message ``"sequence aborted"``.  Idempotent when
        called with nothing in flight — it simply cancels any remaining PENDING.
        Preserving already-DONE/FAILED entries is intentional: the data those
        runs took is untouched by a later cancel.
        """
        active = self._active_entry()
        if active is not None:
            self._set_state(active, EntryState.CANCELLED, "sequence aborted")
        for e in self.entries:
            if e.state is EntryState.PENDING:
                self._set_state(e, EntryState.CANCELLED, "sequence aborted")

    # -- observation -------------------------------------------------------
    @property
    def is_complete(self) -> bool:
        """True when no entry is PENDING/PREFLIGHT/RUNNING (all terminal)."""
        return all(e.state in _TERMINAL for e in self.entries)

    @property
    def progress(self) -> tuple[int, int]:
        """``(entries in a terminal state, total entries)``."""
        done = sum(1 for e in self.entries if e.state in _TERMINAL)
        return (done, len(self.entries))

    @property
    def current(self) -> SequenceEntry | None:
        """The in-flight (PREFLIGHT/RUNNING) entry, or ``None`` between entries."""
        return self._active_entry()

    # -- internals ---------------------------------------------------------
    def _first_pending(self) -> SequenceEntry | None:
        for e in self.entries:
            if e.state is EntryState.PENDING:
                return e
        return None

    def _running_entry(self) -> SequenceEntry | None:
        for e in self.entries:
            if e.state is EntryState.RUNNING:
                return e
        return None

    def _active_entry(self) -> SequenceEntry | None:
        for e in self.entries:
            if e.state in _ACTIVE:
                return e
        return None

    def _halt(self, terminal: EntryState, message: str) -> None:
        for e in self.entries:
            if e.state is EntryState.PENDING:
                self._set_state(e, terminal, message)

    def _set_state(self, entry: SequenceEntry, new: EntryState,
                   message: str = "") -> None:
        old = entry.state
        entry.state = new
        entry.message = message
        suffix = f" ({message})" if message else ""
        self._append_log(f"{entry.name}: {old.value} -> {new.value}{suffix}")

    def _append_log(self, text: str) -> None:
        self.log.append(f"[{time.time():.3f}] {text}")


# --------------------------------------------------------------------------- #
# Persistence — pure functions                                                #
# --------------------------------------------------------------------------- #

def save_sequence_yaml(path: str | Path, entries) -> None:
    """Serialize *entries* to *path* as ``{version, entries: [{name, source_path,
    plan}]}``.

    Each plan is stored INLINE via :meth:`ScanPlan.to_dict` — the saved queue is
    self-contained and independent of the source YAML files it was built from.
    Live state (PENDING/DONE/…) is deliberately NOT persisted: a loaded sequence
    is a fresh queue to run, every entry PENDING.
    """
    doc = {
        "version": SEQUENCE_FILE_VERSION,
        "entries": [
            {
                "name": e.name,
                "source_path": e.source_path,
                "plan": e.plan.to_dict(),
            }
            for e in entries
        ],
    }
    Path(path).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def load_sequence_yaml(path: str | Path) -> list[SequenceEntry]:
    """Load a sequence file into a list of PENDING :class:`SequenceEntry`.

    Fail-closed: a malformed top-level document, an unsupported version, or any
    malformed entry raises :class:`ValueError` **naming the entry index** — never
    a silently shortened queue.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("sequence file must be a mapping with an 'entries' list")

    version = raw.get("version", SEQUENCE_FILE_VERSION)
    if version != SEQUENCE_FILE_VERSION:
        raise ValueError(
            f"unsupported sequence file version {version!r}; "
            f"expected {SEQUENCE_FILE_VERSION}"
        )

    raw_entries = raw.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("sequence file 'entries' must be a list")

    entries: list[SequenceEntry] = []
    for i, item in enumerate(raw_entries):
        try:
            if not isinstance(item, dict):
                raise ValueError("entry must be a mapping")
            name = item.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("entry needs a non-empty 'name'")
            plan_dict = item.get("plan")
            if not isinstance(plan_dict, dict):
                raise ValueError("entry needs a 'plan' mapping")
            plan = ScanPlan.from_dict(plan_dict)
            source_path = item.get("source_path")
            if source_path is not None and not isinstance(source_path, str):
                raise ValueError("'source_path' must be a string or null")
            entries.append(
                SequenceEntry(name=name, plan=plan, source_path=source_path)
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(
                f"sequence entry [{i}] is malformed: {exc}"
            ) from exc
    return entries
