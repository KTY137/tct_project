"""``SequencerQueueViewModel`` — the read-only queue/run mirror + source-queue
data model half of the Scan Sequencer split (``docs/design/u1_staging.md`` §5;
QML-migration beat U1.3).

Sibling of :class:`gui.run_state_viewmodel.RunStateViewModel` and
:class:`gui.scope_viewmodel.ScopeViewModel`.  The Scan Sequencer is the only U1
panel that holds a live :class:`~gui.sequence_coordinator.SequenceCoordinator`
and command callables, so its port splits in two (u1_staging §5.1):

* everything *mirror-shaped* — the queue table's per-row live state, run
  progress/outcome, the combined-envelope summary — plus the *source-queue data
  model* (queue editing arms nothing; it is data, not command) lives HERE, in a
  read-only view-model that holds NO coordinator, NO gate, NO ``park_safe`` and
  NO run-control callable;
* everything *command-shaped* — arm/execute, abort, the ``ArmLatch`` ceremony,
  the private :class:`~controller.arm_envelope.ArmedEnvelopeGate`, the manual-
  danger lock wiring — stays on the retained command/safety host
  (:class:`gui.sequencer_panel.SequencerPanel`).

The single most important property of this class (safety-critical, encoded as a
test): it exposes **NO** callable that starts/pauses/stops/aborts/arms anything
and holds **NO** reference to a coordinator / state-machine / gate through which
QML could reach one.  It is *fed* on the GUI thread by the host (which connects
the coordinator's terminal signals to the ``on_*`` methods here); it cannot
*reach* anything.  That structural read/command boundary is what encodes
hardware-safety rule 2 — the same law ``RunStateViewModel`` carries, replicated
per the S2 standing-law manifest row (Ruling Q3).

Queue editing is data, not command (u1_staging §5.2)
----------------------------------------------------
``add_routine`` / ``remove`` / ``move`` / ``save`` / ``load`` mutate the SOURCE
queue only — they arm nothing.  The *enforcing* gate for "no edit while a run is
live" is the coordinator's own ``load()``-refuses-while-active (host side); the
VM additionally refuses edits while ``active`` is mirrored True (a cheap
no-op-and-log guard, never the sole enforcement).  A fail-closed queue-I/O error
is surfaced via the :attr:`load_error` signal — the VM imports no ``notify`` and
knows nothing about the status bus; the host connects ``load_error`` to it.

Threading: mutated on the GUI thread only.  Owns no thread, no timer, no lock,
no device handle — identical discipline to ``RunStateViewModel``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Property, QObject, Signal

from controller.scan_plan import ScanPlan
from controller.sequencer import (
    EntryState, SequenceEntry, load_sequence_yaml, save_sequence_yaml,
)

logger = logging.getLogger(__name__)


# Entry-state value → (chip label, chip visual token).  The semantic ladder per
# docs/design/state_color_census.md (law 1 "quiet nominal"): PENDING / SKIPPED /
# CANCELLED / DONE are neutral (a DONE routine is quiet grey, NEVER green — green
# is spent sparingly and never means "fine"); PREFLIGHT is a brief info state;
# RUNNING is the one busy/accent state; FAILED is the only crit (the halt
# culprit).  Token NAMES only — semantics, not paint; the host resolves them to
# colours.  (Moved here verbatim from the panel per u1_staging §5.2.)
_ENTRY_CHIP: dict[str, tuple[str, str]] = {
    EntryState.PENDING.value:   ("PENDING", "neutral"),
    EntryState.PREFLIGHT.value: ("PREFLIGHT", "info"),
    EntryState.RUNNING.value:   ("RUNNING", "busy"),
    EntryState.DONE.value:      ("DONE", "neutral"),
    EntryState.FAILED.value:    ("FAILED", "crit"),
    EntryState.SKIPPED.value:   ("SKIPPED", "neutral"),
    EntryState.CANCELLED.value: ("CANCELLED", "neutral"),
}

# The chip a freshly-queued (or reloaded) row shows before any live-state feed.
_PENDING_CHIP: tuple[str, str, str] = (
    _ENTRY_CHIP[EntryState.PENDING.value][0],
    _ENTRY_CHIP[EntryState.PENDING.value][1],
    "",
)


class SequencerQueueViewModel(QObject):
    """Read-only queue/run mirror + source-queue data model (see module docstring)."""

    # One NOTIFY for every property read (the RunStateViewModel/ScopeViewModel
    # house pattern).  ``queue_changed`` is the host's cue that the SOURCE queue
    # changed and the coordinator must be re-loaded + the envelope re-derived.
    # ``load_error`` surfaces a fail-closed queue-I/O failure (the host connects
    # it to the non-blocking status bus — the VM never imports ``notify``).
    changed = Signal()
    queue_changed = Signal()
    load_error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # SOURCE queue — name / plan snapshot / provenance.  The coordinator keeps
        # its OWN deep-copied entries with live states; this list is only what the
        # operator is assembling (the exact role the panel's old ``_entries`` had).
        self._entries: List[SequenceEntry] = []
        # Per-row DISPLAY chip (label, visual, message), parallel to ``_entries``
        # — the live-state mirror, fed by ``on_entry_state`` from the coordinator.
        self._rows: List[Tuple[str, str, str]] = []
        # Run mirror.
        self._active = False
        self._done = 0
        self._total = 0
        self._outcome_word = ""
        self._last_error = ""
        # Envelope mirror — the plain summary STRING, FED by the host after its
        # ``build_gate`` (the VM never sees the gate or the coordinator).
        self._envelope_summary = ""

    # ------------------------------------------------------------------ #
    # Source-queue editing (DATA, not command — arms nothing)             #
    # ------------------------------------------------------------------ #
    def add_routine(self, path: str) -> bool:
        """Append a saved routine (name = file stem).  Fail-closed: a malformed
        routine surfaces via :attr:`load_error` and is NEVER silently added.
        No-op (logged) while a run is active."""
        if self._active:
            logger.info("sequencer: ignoring add_routine while a sequence is active")
            return False
        try:
            plan = ScanPlan.load_yaml(path)
        except Exception as exc:
            self.load_error.emit(
                f"Could not load routine '{Path(path).name}': {exc}")
            return False
        self._entries.append(
            SequenceEntry(name=Path(path).stem, plan=plan, source_path=str(path)))
        self._after_queue_edit()
        return True

    def remove(self, row: int) -> bool:
        """Remove the entry at *row*.  No-op while active or on a bad index."""
        if self._active:
            logger.info("sequencer: ignoring remove while a sequence is active")
            return False
        if not (0 <= row < len(self._entries)):
            return False
        del self._entries[row]
        self._after_queue_edit()
        return True

    def move(self, row: int, delta: int) -> bool:
        """Swap the entry at *row* with its neighbour ``row + delta``.  No-op
        while active or when either index is out of range."""
        if self._active:
            logger.info("sequencer: ignoring move while a sequence is active")
            return False
        new = row + delta
        if row < 0 or not (0 <= new < len(self._entries)):
            return False
        self._entries[row], self._entries[new] = (
            self._entries[new], self._entries[row])
        self._after_queue_edit()
        return True

    def save(self, path: str) -> bool:
        """Persist the whole queue.  A write failure surfaces via
        :attr:`load_error`; the queue itself is unaffected."""
        try:
            save_sequence_yaml(path, self._entries)
        except Exception as exc:
            self.load_error.emit(f"Could not save sequence: {exc}")
            return False
        return True

    def load(self, path: str) -> bool:
        """Replace the queue from a saved sequence file.

        Fail-closed: ``load_sequence_yaml`` raises (naming the bad entry) on any
        malformed document rather than yielding a silently shortened queue, so on
        error the CURRENT queue is left UNTOUCHED and the reason is surfaced via
        :attr:`load_error`.  No-op (logged) while a run is active."""
        if self._active:
            logger.info("sequencer: ignoring load while a sequence is active")
            return False
        try:
            entries = load_sequence_yaml(path)
        except Exception as exc:
            self.load_error.emit(
                f"Could not load sequence '{Path(path).name}': {exc}")
            return False
        self._entries = entries
        self._after_queue_edit()
        return True

    def _after_queue_edit(self) -> None:
        """Reset the per-row chips to all-PENDING, then cue the host to re-sync
        the coordinator (``queue_changed``) and readers to repaint (``changed``)."""
        self._rows = [_PENDING_CHIP for _ in self._entries]
        self.queue_changed.emit()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # Feed surface (plain methods; the HOST connects coordinator signals  #
    # to these — u1_staging §5.3.  Never a @Slot the VM connects itself.) #
    # ------------------------------------------------------------------ #
    def on_entry_state(self, row: int, state_value: str, message: str) -> None:
        """``SequenceCoordinator.entry_state_changed`` — one row's live state."""
        self._sync_rows_len()
        if 0 <= row < len(self._rows):
            label, visual = _ENTRY_CHIP.get(
                state_value, (state_value.upper(), "neutral"))
            self._rows[row] = (label, visual, message)
            self.changed.emit()

    def on_progress(self, done, total) -> None:
        """``SequenceCoordinator.sequence_progress`` — terminal entries / total."""
        self._done = int(done)
        self._total = int(total)
        self.changed.emit()

    def on_finished(self, word: str) -> None:
        """``SequenceCoordinator.sequence_finished`` — the outcome word."""
        self._outcome_word = str(word)
        self.changed.emit()

    def on_error(self, reason: str) -> None:
        """``SequenceCoordinator.sequence_error`` — the fail-closed reason."""
        self._last_error = str(reason)
        self.changed.emit()

    def on_active(self, flag) -> None:
        """``SequenceCoordinator.sequence_active`` — True at arm, False at every
        terminal.  Mirror only: the panel keeps its OWN ``_active`` flag for
        control gating (the deliberate one-boolean duplication, u1_staging §5.4)."""
        self._active = bool(flag)
        self.changed.emit()

    def set_envelope_summary(self, text: str) -> None:
        """Host feed: the combined-envelope summary (empty string = no valid
        envelope).  The VM never derives it — the host builds the gate and passes
        only ``env.summary`` (never the gate, never the coordinator)."""
        self._envelope_summary = str(text)
        self.changed.emit()

    def _sync_rows_len(self) -> None:
        """Keep the per-row chip list the same length as the source queue — an
        ``entry_state`` feed may arrive right after a direct queue mutation."""
        n = len(self._entries)
        if len(self._rows) < n:
            self._rows.extend(_PENDING_CHIP for _ in range(n - len(self._rows)))
        elif len(self._rows) > n:
            del self._rows[n:]

    # ------------------------------------------------------------------ #
    # Host-facing read accessors — the panel re-syncs the coordinator     #
    # from these (plain data; never a callable into the run stack).       #
    # ------------------------------------------------------------------ #
    @property
    def named_plans(self) -> List[Tuple[str, ScanPlan]]:
        """``(name, plan)`` pairs — what the host hands ``coordinator.load``."""
        return [(e.name, e.plan) for e in self._entries]

    @property
    def source_paths(self) -> List[Optional[str]]:
        """Per-entry provenance path, aligned with :attr:`named_plans`."""
        return [e.source_path for e in self._entries]

    @property
    def rows(self) -> List[Tuple[str, str, str]]:
        """Per-row ``(label, visual_token, message)`` — the queue-table mirror.
        A plain list for U1; the QML port (U4/U5) re-exposes it as a list model."""
        return list(self._rows)

    # ------------------------------------------------------------------ #
    # QML-facing read-only scalar properties (the run/envelope mirror)    #
    # ------------------------------------------------------------------ #
    @Property(int, notify=changed)
    def count(self) -> int:
        return len(self._entries)

    @Property(bool, notify=changed)
    def active(self) -> bool:
        return self._active

    @Property(int, notify=changed)
    def done(self) -> int:
        return self._done

    @Property(int, notify=changed)
    def total(self) -> int:
        return self._total

    @Property(str, notify=changed)
    def progressText(self) -> str:
        return f"{self._done}/{self._total}"

    @Property(str, notify=changed)
    def outcomeWord(self) -> str:
        return self._outcome_word

    @Property(str, notify=changed)
    def lastError(self) -> str:
        return self._last_error

    @Property(str, notify=changed)
    def envelopeSummary(self) -> str:
        return self._envelope_summary
