"""
Scan Sequencer panel — the operator face of the unattended overnight routine
queue (feature_requests_v5 §7; design mock ``artifacts_claude/v5/planner.html``
§"Scan Sequencer").

This is a **pure view + composition glue** widget.  It owns NO run logic: the
event-driven :class:`~gui.sequence_coordinator.SequenceCoordinator` (Noah-A4)
drives the whole night off ``ScanCoordinator`` terminals and parks hardware safe
between entries; this panel only

* edits the *source* queue (add / remove / reorder / save / load saved routines),
* renders each queue entry's live state as a :class:`~gui.status_widgets.StatusChip`
  off the coordinator's ``entry_state_changed`` signal,
* re-derives the ONE combined :class:`~controller.arm_envelope.ArmedEnvelope`
  over the whole queue on **every** queue edit and renders its ``summary`` over a
  reused :class:`~gui.arm_latch.ArmLatch` (the ratified two-step hold-3s gesture),
* Executes → :meth:`SequenceCoordinator.arm_and_start`, and Aborts →
  :meth:`SequenceCoordinator.abort_sequence` (always live while the queue runs).

Safety seams that DON'T live here (they are wired in ``tct_gui`` off the
coordinator's ``sequence_active`` signal, so they survive a soft-reload and stay
at the composition root):

* the manual HV / motion danger panels are locked while a sequence runs, and
* the run-control coordinator's modal error/warn message boxes are rerouted to
  the non-blocking status bus so an overnight run can never wedge on a dialog.

The union :class:`~controller.arm_envelope.ArmedEnvelopeGate` is PRIVATE to the
coordinator (Mary req 1): this panel receives ONLY the ``(envelope, gate)`` pair
from :meth:`SequenceCoordinator.build_gate` and uses just the envelope's
``summary`` for display — it never stores or re-wires the gate, and manual panels
stay on the app's own ``QtDangerGate``.

Every colour resolves from ``gui.style`` tokens (zero inline hex — the guard test
``tests/test_no_inline_hex_gui.py`` has per-value teeth now); the one cached
colour (the danger-red HV span in the envelope text, and the muted caption ink)
is re-resolved in :meth:`refresh_theme` after a light/dark switch.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from controller.arm_envelope import ArmedEnvelope
from controller.scan_plan import ScanPlan
from controller.sequencer import (
    EntryState, SequenceEntry, load_sequence_yaml, save_sequence_yaml,
)
from gui.arm_latch import ArmLatch
from gui.panel_kit import panel_header
from gui.status_bus import notify
from gui.status_widgets import StatusChip
from gui.style import SPACE_MD, SPACE_SM, palette

if TYPE_CHECKING:  # pragma: no cover - typing only; injected at runtime
    from gui.sequence_coordinator import SequenceCoordinator


# Entry-state → (chip label, chip visual state).  Ladder per
# docs/design/state_color_census.md conventions (law 1 "quiet nominal"):
#   PENDING / SKIPPED / CANCELLED / DONE  -> neutral (a DONE routine is quiet
#     grey, NEVER green — green is spent sparingly and never means "fine");
#   PREFLIGHT -> info (a brief informational active check);
#   RUNNING   -> busy (the one ACTIVE/accent state);
#   FAILED    -> crit (the halt culprit — the only red row).
_ENTRY_CHIP: dict[str, tuple[str, str]] = {
    EntryState.PENDING.value:   ("PENDING", "neutral"),
    EntryState.PREFLIGHT.value: ("PREFLIGHT", "info"),
    EntryState.RUNNING.value:   ("RUNNING", "busy"),
    EntryState.DONE.value:      ("DONE", "neutral"),
    EntryState.FAILED.value:    ("FAILED", "crit"),
    EntryState.SKIPPED.value:   ("SKIPPED", "neutral"),
    EntryState.CANCELLED.value: ("CANCELLED", "neutral"),
}

# The HV run inside ``ArmedEnvelope.summary`` ("... HV <min>..<max> V ...").
# Best-effort: if a summary ever formats HV differently the text still renders
# (unwrapped) — the numbers are always present regardless of the span.
_HV_RE = re.compile(r"(HV\s-?\d+(?:\.\d+)?\.\.-?\d+(?:\.\d+)?\s*V)")

_COL_ROUTINE = 0
_COL_SOURCE = 1
_COL_STATE = 2


class SequencerPanel(QWidget):
    """Operator surface for the unattended Scan Sequencer (see the module docstring)."""

    def __init__(
        self,
        coordinator: "SequenceCoordinator",
        *,
        channel_provider: Callable[[], int] | None = None,
        theme_mode: str = "light",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        # Resolves the bias-supply channel the combined HV envelope is attributed
        # to (build_gate).  tct_gui injects the real primary channel; default 0
        # (the single-primary / simulation case).
        self._channel_provider: Callable[[], int] = channel_provider or (lambda: 0)
        self._theme_mode = str(theme_mode)
        # The SOURCE queue (name / plan snapshot / provenance).  The coordinator
        # keeps its OWN deep-copied entries + live states; this list is only what
        # the operator is assembling.  SequenceEntry is reused so save/load go
        # straight through controller.sequencer's persistence functions.
        self._entries: list[SequenceEntry] = []
        self._env: Optional[ArmedEnvelope] = None
        self._active = False
        self._done = 0
        self._total = 0

        self._build_ui()

        # Connect the coordinator's signals BEFORE any load() — the coordinator
        # emits every row at load, so a late connection would miss the first
        # PENDING paint (SequenceCoordinator docstring / A4 handoff).
        coordinator.entry_state_changed.connect(self._on_entry_state_changed)
        coordinator.sequence_progress.connect(self._on_progress)
        coordinator.sequence_finished.connect(self._on_finished)
        coordinator.sequence_error.connect(self._on_error)
        coordinator.sequence_active.connect(self._on_active)

        self.refresh_theme(self._theme_mode)
        self._sync_coordinator()

    # ------------------------------------------------------------------ #
    # UI construction                                                    #
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        root.setSpacing(SPACE_MD)

        # Header: title + live status chip + the two primary actions.  Add is a
        # quiet/ghost action; Abort is the red-OUTLINE danger control (law 5 —
        # kept always visible, enabled only while a sequence runs).
        self._chip_status = StatusChip("Idle", "neutral", min_width=96)
        self._chip_status.setToolTip("Sequencer run state")
        self._btn_add = QPushButton("＋ Add routine")
        self._btn_add.setProperty("state", "ghost")
        self._btn_add.setToolTip("Add a saved routine (.yaml) to the queue")
        self._btn_add.clicked.connect(self._on_add)
        self._btn_abort = QPushButton("■ Abort sequence")
        self._btn_abort.setProperty("state", "crit")   # outline-red danger token
        self._btn_abort.setToolTip(
            "Cancel the running queue, abort the live run, and park hardware safe")
        self._btn_abort.clicked.connect(self._on_abort)
        root.addWidget(panel_header(
            "TCT Control · Sequencer", "Scan Sequencer",
            trailing=[self._chip_status, self._btn_add, self._btn_abort],
            theme_mode=self._theme_mode,
        ))

        self._desc = QLabel(
            "A queue of saved routines that runs unattended — the overnight "
            "workflow. Between entries the sequencer parks hardware safe; the "
            "first non-clean outcome halts the night (fail-closed).")
        self._desc.setWordWrap(True)
        root.addWidget(self._desc)

        # Queue table — one row per routine (index · name / source / state chip).
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Routine", "Source", "State"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(_COL_ROUTINE, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_COL_SOURCE, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(_COL_STATE, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._refresh_controls)
        root.addWidget(self._table, 1)

        # Secondary toolbar: reorder / remove / persist the queue.
        tool_row = QHBoxLayout()
        tool_row.setSpacing(SPACE_SM)
        self._btn_remove = QPushButton("Remove")
        self._btn_remove.clicked.connect(self._remove_selected)
        # Bound methods, never lambdas — a self-capturing closure on a child
        # button's signal is held strongly by Qt's connection storage and makes
        # this panel immortal (tests/test_no_immortal_panels.py).
        self._btn_up = QPushButton("↑ Up")
        self._btn_up.clicked.connect(self._move_selected_up)
        self._btn_down = QPushButton("↓ Down")
        self._btn_down.clicked.connect(self._move_selected_down)
        self._btn_save = QPushButton("Save queue…")
        self._btn_save.clicked.connect(self._on_save)
        self._btn_load = QPushButton("Load queue…")
        self._btn_load.clicked.connect(self._on_load)
        for b in (self._btn_remove, self._btn_up, self._btn_down):
            tool_row.addWidget(b)
        tool_row.addStretch(1)
        tool_row.addWidget(self._btn_save)
        tool_row.addWidget(self._btn_load)
        root.addLayout(tool_row)

        # Combined-envelope block: the ONE ArmedEnvelope summary rendered over the
        # reused two-step Arm latch (hold-3s).  Execute → arm_and_start.
        self._latch = ArmLatch(theme_mode=self._theme_mode, parent=self)
        self._latch.execute_requested.connect(self._on_execute)
        root.addWidget(self._latch)

        self._progress_lbl = QLabel("Progress · 0/0 entries complete")
        self._outcome_lbl = QLabel("Last sequence outcome · —")
        root.addWidget(self._progress_lbl)
        root.addWidget(self._outcome_lbl)

    # ------------------------------------------------------------------ #
    # Queue editing (source list → coordinator.load → envelope re-derive) #
    # ------------------------------------------------------------------ #
    def _sync_coordinator(self) -> None:
        """Push the source queue into the coordinator and re-derive the envelope.

        Called after EVERY queue edit.  A pending Arm gesture is invalidated
        first (an edit must never leave a stale arm authorizing an old envelope),
        the table is rebuilt so row indices line up with the coordinator's about-
        to-be-emitted per-entry states, then ``load`` (deep-copies the plans) and
        ``build_gate`` re-derive the single combined envelope from scratch — a
        stale summary is structurally impossible.
        """
        self._latch.disarm("invalidated")
        self._rebuild_table()
        self._coordinator.load(
            [(e.name, e.plan) for e in self._entries],
            source_paths=[e.source_path for e in self._entries],
        )
        self._refresh_envelope()
        self._refresh_controls()

    def _rebuild_table(self) -> None:
        self._table.setRowCount(0)
        for i, e in enumerate(self._entries):
            self._table.insertRow(i)
            name_item = QTableWidgetItem(f"{i + 1} · {e.name}")
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(i, _COL_ROUTINE, name_item)
            src = Path(e.source_path).name if e.source_path else "—"
            src_item = QTableWidgetItem(src)
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            src_item.setToolTip(e.source_path or "in-memory routine")
            self._table.setItem(i, _COL_SOURCE, src_item)
            self._table.setCellWidget(i, _COL_STATE, StatusChip("PENDING", "neutral"))

    def _refresh_envelope(self) -> None:
        """Re-derive the ONE combined envelope over the loaded queue and render
        its summary over the latch (empty queue → clear + not-ready)."""
        if not self._entries:
            self._env = None
            self._latch.set_envelope_text("")
            return
        try:
            env, _gate = self._coordinator.build_gate(int(self._channel_provider()))
        except Exception as exc:  # empty/failed derivation — fail-closed to not-ready
            self._env = None
            self._latch.set_envelope_text("")
            notify(f"Cannot derive sequence envelope: {exc}", "warn")
            return
        self._env = env
        self._latch.set_envelope_text(self._envelope_html(env))

    def _refresh_controls(self) -> None:
        active = self._active
        has_entries = bool(self._entries)
        has_sel = self._table.currentRow() >= 0
        self._btn_add.setEnabled(not active)
        self._btn_remove.setEnabled(not active and has_sel)
        self._btn_up.setEnabled(not active and has_sel)
        self._btn_down.setEnabled(not active and has_sel)
        self._btn_save.setEnabled(not active and has_entries)
        self._btn_load.setEnabled(not active)
        self._btn_abort.setEnabled(active)
        # The latch is fully inert while a sequence runs (its Abort is the live
        # stop, never this widget); otherwise ready iff a valid envelope exists.
        self._latch.set_running(active)
        if not active:
            if has_entries and self._env is not None:
                self._latch.set_ready(True)
            else:
                self._latch.set_ready(
                    False, "Add at least one routine to arm the sequence.")

    # ------------------------------------------------------------------ #
    # Add / remove / reorder                                             #
    # ------------------------------------------------------------------ #
    @Slot()
    def _on_add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Add routine", "", "Scan routines (*.yaml *.yml);;All files (*)")
        if path:
            self._add_routine_from(path)

    def _add_routine_from(self, path: str) -> None:
        """Load a saved routine and append it (name = file stem).  A malformed
        routine is surfaced and never silently added."""
        try:
            plan = ScanPlan.load_yaml(path)
        except Exception as exc:
            notify(f"Could not load routine '{Path(path).name}': {exc}", "error")
            return
        self._entries.append(
            SequenceEntry(name=Path(path).stem, plan=plan, source_path=str(path)))
        self._sync_coordinator()

    @Slot()
    def _remove_selected(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._entries) and not self._active:
            del self._entries[row]
            self._sync_coordinator()

    def _move_selected(self, delta: int) -> None:
        row = self._table.currentRow()
        new = row + delta
        if self._active or row < 0 or not (0 <= new < len(self._entries)):
            return
        self._entries[row], self._entries[new] = self._entries[new], self._entries[row]
        self._sync_coordinator()
        self._table.setCurrentCell(new, _COL_ROUTINE)

    @Slot()
    def _move_selected_up(self) -> None:
        self._move_selected(-1)

    @Slot()
    def _move_selected_down(self) -> None:
        self._move_selected(+1)

    # ------------------------------------------------------------------ #
    # Save / load the whole queue                                        #
    # ------------------------------------------------------------------ #
    @Slot()
    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save sequence", "", "Sequence files (*.yaml *.yml);;All files (*)")
        if path:
            self._save_queue_to(path)

    def _save_queue_to(self, path: str) -> None:
        try:
            save_sequence_yaml(path, self._entries)
        except Exception as exc:
            notify(f"Could not save sequence: {exc}", "error")
            return
        notify(f"Sequence saved to {Path(path).name}", "info")

    @Slot()
    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load sequence", "", "Sequence files (*.yaml *.yml);;All files (*)")
        if path:
            self._load_queue_from(path)

    def _load_queue_from(self, path: str) -> None:
        """Replace the queue from a saved sequence file.

        Fail-closed: ``load_sequence_yaml`` raises (naming the bad entry) on any
        malformed document rather than yielding a silently shortened queue, so on
        error the CURRENT queue is left untouched and the reason is surfaced.
        """
        try:
            entries = load_sequence_yaml(path)
        except Exception as exc:
            notify(f"Could not load sequence '{Path(path).name}': {exc}", "error")
            return
        self._entries = entries
        self._sync_coordinator()

    # ------------------------------------------------------------------ #
    # Arm / abort                                                        #
    # ------------------------------------------------------------------ #
    @Slot()
    def _on_execute(self) -> None:
        """The armed latch's Execute → arm + drive the whole queue."""
        try:
            self._coordinator.arm_and_start()
        except Exception as exc:
            notify(f"Cannot start sequence: {exc}", "error")

    @Slot()
    def _on_abort(self) -> None:
        """Operator panic: cancel the queue, abort the live run, park safe."""
        self._coordinator.abort_sequence()

    # ------------------------------------------------------------------ #
    # Coordinator signal handlers (GUI thread — already marshalled)       #
    # ------------------------------------------------------------------ #
    @Slot(int, str, str)
    def _on_entry_state_changed(self, row: int, state_value: str, message: str) -> None:
        if not (0 <= row < self._table.rowCount()):
            return
        chip = self._table.cellWidget(row, _COL_STATE)
        if not isinstance(chip, StatusChip):
            return
        label, visual = _ENTRY_CHIP.get(state_value, (state_value.upper(), "neutral"))
        chip.set_status(label, visual, tooltip=message or None)

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self._done, self._total = done, total
        self._progress_lbl.setText(f"Progress · {done}/{total} entries complete")
        if self._active:
            self._chip_status.set_status(f"Running · {done}/{total}", "busy")

    @Slot(str)
    def _on_finished(self, word: str) -> None:
        self._outcome_lbl.setText(f"Last sequence outcome · {word}")

    @Slot(str)
    def _on_error(self, reason: str) -> None:
        # The coordinator failed closed (an engine call raised); the paired
        # sequence_finished("error") + sequence_active(False) still fire.
        notify(f"Sequence halted: {reason}", "error")

    @Slot(bool)
    def _on_active(self, active: bool) -> None:
        self._active = bool(active)
        if self._active:
            self._chip_status.set_status(
                f"Running · {self._done}/{self._total}", "busy")
        else:
            self._chip_status.set_status("Idle", "neutral")
        self._refresh_controls()

    # ------------------------------------------------------------------ #
    # Envelope text / theming / teardown                                 #
    # ------------------------------------------------------------------ #
    def _envelope_html(self, env: ArmedEnvelope) -> str:
        """Render ``env.summary`` (which already names every routine + max HV +
        travel) as rich text, colouring the HV run with the danger token — the
        only red in the well (law 2: HV is the sole red)."""
        danger = palette(self._theme_mode)["danger"]
        text = html.escape(env.summary)
        return _HV_RE.sub(
            lambda m: f'<span style="color:{danger}; font-weight:600">'
                      f'{m.group(1)}</span>',
            text,
        )

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve the cached colours (envelope HV span, muted captions) and
        forward to the latch after a light/dark switch — registered in
        ``tct_gui._toggle_theme``."""
        if mode:
            self._theme_mode = str(mode)
        p = palette(self._theme_mode)
        muted = p["muted"]
        for lbl in (self._desc, self._progress_lbl, self._outcome_lbl):
            lbl.setStyleSheet(f"color: {muted};")
        self._latch.refresh_theme(self._theme_mode)
        if self._env is not None:
            self._latch.set_envelope_text(self._envelope_html(self._env))

    def shutdown(self) -> None:
        """Stop the latch's owned timers before teardown (panel ``shutdown()``
        idiom).  Idempotent."""
        self._latch.shutdown()
