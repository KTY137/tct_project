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

U1.3 split (``docs/design/u1_staging.md`` §5): the *mirror-shaped* half — the
source-queue data model, the per-row live-state chips, run progress/outcome and
the envelope **summary** — now lives in :class:`~gui.sequencer_viewmodel.\
SequencerQueueViewModel` (a read-only view-model that holds NO coordinator, NO
gate and NO run-control callable).  This panel is the **retained command/safety
host**: it keeps the live coordinator, the ``ArmLatch`` ceremony, the private
``ArmedEnvelopeGate`` plumbing, the always-live Abort, and its OWN ``_active``
flag for control gating (§5.4 — the deliberate one-boolean duplication).  The
host makes EVERY signal connection (§5.3): the coordinator's terminals FEED the
view-model; the panel repaints off the view-model's single ``changed`` NOTIFY;
control gating + the modal-safe notify path stay on the panel's OWN
``sequence_active`` / ``sequence_error`` edges, never routed through the VM.

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

Round-03 glass kit migration (wave beat, HAZARD PANEL — mirrors ``BiasPanel``'s
blanket stance, commit 074943f, not the content-consequence reasoning of
``IntensityPanel``/``LaserPanel``): the whole panel is now ONE ``GlassPane``
shelf (chrome head + queue table + toolbar + hazard-wrapped run control +
progress/outcome), and the shelf opts NOTHING into the panel-glass switch —
``register=False``, no other surface here registers either. The round-03 design
census (``docs/design/iterations/glasshell-cockpit/round-03/README.md`` §3)
names this panel's own row: "the Start control is the danger ceremony
(Arm→Execute), on a ``HazardSurface``" — the reused two-step :class:`ArmLatch`
(envelope text + Arm + Execute) is wrapped, as a PURE PARENT-FRAME WRAP, in an
opaque ``HazardSurface`` carrying the ``armed`` (motion-class) stripe — the
same stripe kind the census gives Motor Stage's homing/jog ceremony, since
arming here is itself a motion-class gesture; any HV a given routine's combined
envelope carries is already the inline danger-red span inside the latch text
(one red channel, the same rule bias's hero trio follows). The always-live
Abort control stays a plain header trailing widget, outside both the
HazardSurface and any ``ActionBar`` (a stop control never nests inside the
danger-state display it can silence — the bias pilot's kill-switch precedent —
and ``ActionBar``'s danger slot clobbers objectNames/escalation chrome).
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
from gui.arm_latch import ArmLatch
from gui.panel_kit import GlassPane, HazardSurface, panel_header
from gui.sequencer_viewmodel import SequencerQueueViewModel
from gui.status_bus import notify
from gui.status_widgets import StatusChip
from gui.style import SPACE_SM, palette

if TYPE_CHECKING:  # pragma: no cover - typing only; injected at runtime
    from gui.sequence_coordinator import SequenceCoordinator


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
        # The read-only queue/run mirror + SOURCE-queue data model (u1_staging
        # §5.2).  It holds the source queue this panel is assembling, the per-row
        # live-state chips, run progress/outcome and the envelope summary — but NO
        # coordinator, NO gate and NO run-control callable.  Panel-constructed in
        # U1 (§1.1); moves to the composition root at the sequencer's own port
        # stage.  ``self._entries`` (below) is a live view onto the VM's queue.
        self._vm = SequencerQueueViewModel(parent=self)
        self._env: Optional[ArmedEnvelope] = None
        # The panel's OWN control-gating flag (u1_staging §5.4): display state
        # reads the VM, but abort/latch enabled-ness keeps this pinned private
        # path (fed from the coordinator's sequence_active, NOT from vm.active).
        self._active = False

        self._build_ui()

        # ── Signal flow (u1_staging §5.3): the HOST makes EVERY connection. ──
        # The coordinator's terminals FEED the read-only mirror (VM); the
        # coordinator emits every row at load(), so these must connect BEFORE the
        # first _sync_coordinator() below (a late connection misses the initial
        # PENDING paint — SequenceCoordinator docstring / A4 handoff).
        coordinator.entry_state_changed.connect(self._vm.on_entry_state)
        coordinator.sequence_progress.connect(self._vm.on_progress)
        coordinator.sequence_finished.connect(self._vm.on_finished)
        coordinator.sequence_error.connect(self._vm.on_error)
        coordinator.sequence_active.connect(self._vm.on_active)
        # The panel repaints all display surfaces off the VM's single NOTIFY.
        self._vm.changed.connect(self._repaint)
        # A successful queue edit re-syncs the coordinator + re-derives the
        # envelope; a fail-closed queue-I/O error surfaces on the status bus.
        self._vm.queue_changed.connect(self._sync_coordinator)
        self._vm.load_error.connect(self._on_load_error)
        # Control gating + the (c)-pinned modal-safe notify path stay on the
        # panel's OWN sequence_active / sequence_error edges — NEVER via the VM.
        coordinator.sequence_active.connect(self._on_active)
        coordinator.sequence_error.connect(self._on_error)

        self.refresh_theme(self._theme_mode)
        self._sync_coordinator()

    # A live view onto the VM's source queue.  Kept as a property (not a copied
    # attribute) so it always reflects the VM — including after ``vm.load``
    # replaces the list — and so ``panel._entries.append(...)`` mutates the one
    # true queue (the panel/test harness idiom relies on both).
    @property
    def _entries(self):
        return self._vm._entries

    # ------------------------------------------------------------------ #
    # UI construction                                                    #
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── The one shelf (round-03 kit §2.1) ──────────────────────────
        # HAZARD PANEL — the same blanket ``register=False`` stance as the
        # bias pilot (074943f), not a content consequence like the
        # intensity/laser panels: this queue arms hardware motion (and, per
        # routine, HV) to run unattended all night, so nothing in this panel
        # may ever depend on a translucent tier. The shelf itself, and every
        # surface inside it, opts NOTHING into the panel-glass switch.
        shelf = GlassPane(register=False)
        self._shelf = shelf

        # Header: title + live status chip + the two primary actions.  Add is a
        # quiet/ghost action; Abort is the red-OUTLINE danger control (law 5 —
        # kept always visible, enabled only while a sequence runs).  Abort
        # stays a plain header trailing widget: NOT inside an ``ActionBar``
        # (the bias pilot's kill-switch lesson — ActionBar's danger slot
        # clobbers objectNames and escalation chrome) and NOT inside the
        # HazardSurface below (an always-live stop control never nests inside
        # the danger-state display it can silence — same precedent as the
        # bias pilot's Output-OFF kill switch, which also sits outside its
        # panel's HazardSurface).
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
        shelf.add_widget(panel_header(
            "TCT Control · Sequencer", "Scan Sequencer",
            trailing=[self._chip_status, self._btn_add, self._btn_abort],
            theme_mode=self._theme_mode,
        ))

        self._desc = QLabel(
            "A queue of saved routines that runs unattended — the overnight "
            "workflow. Between entries the sequencer parks hardware safe; the "
            "first non-clean outcome halts the night (fail-closed).")
        self._desc.setWordWrap(True)
        shelf.add_widget(self._desc)

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
        shelf.body.addWidget(self._table, 1)

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
        shelf.add_layout(tool_row)

        # ── Run-control hot zone, on the HazardSurface (round-03 kit §4.6) ──
        # "The stone in the glass room": the combined-envelope block — the ONE
        # ArmedEnvelope summary rendered over the reused two-step Arm latch
        # (hold-3s), Execute → arm_and_start — sits on an OPAQUE HazardSurface
        # (opaque `panel` at every tier) carrying a 4px `armed` (motion-class)
        # stripe + 45° hatch down its left edge — the round-03 design census
        # names this exact control ("the Start control is the danger ceremony
        # (Arm→Execute), on a HazardSurface", round-03/README.md §3) and gives
        # it the `armed` stripe, the same kind Motor Stage's homing/jog
        # ceremony carries, since arming is itself the motion-class gesture;
        # any HV a routine's combined envelope carries is already the inline
        # danger-red span inside the latch text (one red channel — the same
        # rule the bias hero trio follows). A PURE PARENT-FRAME WRAP (Loki
        # rider 5): the latch, its envelope text, its Arm/Execute buttons and
        # every bit of arm/execute logic are byte-identical, only the
        # container changed. The eyebrow supplies the redundant hazard WORD
        # channel (stripe colour + hatch texture + word survive greyscale /
        # a dead projector).
        self._latch = ArmLatch(theme_mode=self._theme_mode, parent=self)
        self._latch.execute_requested.connect(self._on_execute)
        self._hazard = HazardSurface(
            "Unattended run", stripe="armed", theme_mode=self._theme_mode)
        self._hazard.add_widget(self._latch)
        shelf.add_widget(self._hazard)

        self._progress_lbl = QLabel("Progress · 0/0 entries complete")
        self._outcome_lbl = QLabel("Last sequence outcome · —")
        shelf.add_widget(self._progress_lbl)
        shelf.add_widget(self._outcome_lbl)

        # The one shelf now holds the whole panel (head + queue + toolbar +
        # hazard-wrapped run control + progress/outcome); it grows with the
        # window so the table can too.
        root.addWidget(shelf, 1)

    # ------------------------------------------------------------------ #
    # Queue editing (VM source list → coordinator.load → envelope re-derive) #
    # ------------------------------------------------------------------ #
    def _sync_coordinator(self) -> None:
        """Push the VM's source queue into the coordinator and re-derive the envelope.

        Called after EVERY queue edit (via ``vm.queue_changed``).  A pending Arm
        gesture is invalidated first (an edit must never leave a stale arm
        authorizing an old envelope), the table is rebuilt so row indices line up
        with the coordinator's about-to-be-emitted per-entry states, then
        ``load`` (deep-copies the plans) and ``build_gate`` re-derive the single
        combined envelope from scratch — a stale summary is structurally
        impossible.  The freshly-built envelope's summary is fed back into the VM
        (§5.3); the gate itself never leaves this host.
        """
        self._latch.disarm("invalidated")
        self._rebuild_table()
        self._coordinator.load(
            self._vm.named_plans,
            source_paths=self._vm.source_paths,
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
        """Re-derive the ONE combined envelope over the loaded queue, render its
        summary over the latch, and feed the summary into the VM mirror (empty
        queue → clear + not-ready)."""
        if not self._entries:
            self._env = None
            self._vm.set_envelope_summary("")
            self._latch.set_envelope_text("")
            return
        try:
            env, _gate = self._coordinator.build_gate(int(self._channel_provider()))
        except Exception as exc:  # empty/failed derivation — fail-closed to not-ready
            self._env = None
            self._vm.set_envelope_summary("")
            self._latch.set_envelope_text("")
            notify(f"Cannot derive sequence envelope: {exc}", "warn")
            return
        self._env = env
        self._vm.set_envelope_summary(env.summary)
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

    def _repaint(self) -> None:
        """Repaint all DISPLAY surfaces off the VM mirror (u1_staging §5.3).

        Fired on the VM's single ``changed`` NOTIFY.  Control gating is NOT here
        — abort/latch enabled-ness stays on ``_on_active`` / ``_refresh_controls``
        off the panel's own ``sequence_active`` edge (§5.4).
        """
        vm = self._vm
        for row, (label, visual, message) in enumerate(vm.rows):
            if 0 <= row < self._table.rowCount():
                chip = self._table.cellWidget(row, _COL_STATE)
                if isinstance(chip, StatusChip):
                    chip.set_status(label, visual, tooltip=message or None)
        self._progress_lbl.setText(
            f"Progress · {vm.done}/{vm.total} entries complete")
        if vm.outcomeWord:
            self._outcome_lbl.setText(f"Last sequence outcome · {vm.outcomeWord}")
        if vm.active:
            self._chip_status.set_status(f"Running · {vm.done}/{vm.total}", "busy")
        else:
            self._chip_status.set_status("Idle", "neutral")

    # ------------------------------------------------------------------ #
    # Add / remove / reorder (thin delegates over the VM data model)      #
    # ------------------------------------------------------------------ #
    @Slot()
    def _on_add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Add routine", "", "Scan routines (*.yaml *.yml);;All files (*)")
        if path:
            self._add_routine_from(path)

    def _add_routine_from(self, path: str) -> None:
        """Append a saved routine via the VM (name = file stem).  A malformed
        routine is surfaced (``vm.load_error`` → status bus) and never silently
        added; a successful add fires ``vm.queue_changed`` → ``_sync_coordinator``."""
        self._vm.add_routine(path)

    @Slot()
    def _remove_selected(self) -> None:
        self._vm.remove(self._table.currentRow())

    def _move_selected(self, delta: int) -> None:
        row = self._table.currentRow()
        if self._vm.move(row, delta):
            self._table.setCurrentCell(row + delta, _COL_ROUTINE)

    @Slot()
    def _move_selected_up(self) -> None:
        self._move_selected(-1)

    @Slot()
    def _move_selected_down(self) -> None:
        self._move_selected(+1)

    # ------------------------------------------------------------------ #
    # Save / load the whole queue (thin delegates over the VM data model) #
    # ------------------------------------------------------------------ #
    @Slot()
    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save sequence", "", "Sequence files (*.yaml *.yml);;All files (*)")
        if path:
            self._save_queue_to(path)

    def _save_queue_to(self, path: str) -> None:
        if self._vm.save(path):
            notify(f"Sequence saved to {Path(path).name}", "info")

    @Slot()
    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load sequence", "", "Sequence files (*.yaml *.yml);;All files (*)")
        if path:
            self._load_queue_from(path)

    def _load_queue_from(self, path: str) -> None:
        """Replace the queue from a saved sequence file via the VM.

        Fail-closed: ``vm.load`` leaves the CURRENT queue untouched on any
        malformed document and surfaces the reason (``vm.load_error`` → status
        bus); a successful load fires ``vm.queue_changed`` → ``_sync_coordinator``.
        """
        self._vm.load(path)

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
    # Control gating + the modal-safe notify path stay on the panel's own #
    # edges (u1_staging §5.4); DISPLAY is repainted off the VM (_repaint). #
    # ------------------------------------------------------------------ #
    @Slot(str)
    def _on_load_error(self, message: str) -> None:
        # A fail-closed queue-I/O error from the VM (bad routine / bad sequence
        # file / failed save) — surfaced on the non-blocking status bus.
        notify(message, "error")

    @Slot(str)
    def _on_error(self, reason: str) -> None:
        # The coordinator failed closed (an engine call raised); the paired
        # sequence_finished("error") + sequence_active(False) still fire.
        notify(f"Sequence halted: {reason}", "error")

    @Slot(bool)
    def _on_active(self, active: bool) -> None:
        # Control gating only (§5.4): the panel keeps its OWN _active flag for
        # abort/latch enabled-ness.  The status chip / table / labels are
        # repainted by _repaint off the VM's mirror of this same signal.
        self._active = bool(active)
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
        """Re-resolve the cached colours (envelope HV span, muted captions,
        hazard surface stripe/hatch/fill) and forward to the latch after a
        light/dark switch — registered in ``tct_gui._toggle_theme``."""
        if mode:
            self._theme_mode = str(mode)
        p = palette(self._theme_mode)
        muted = p["muted"]
        for lbl in (self._desc, self._progress_lbl, self._outcome_lbl):
            lbl.setStyleSheet(f"color: {muted};")
        self._latch.refresh_theme(self._theme_mode)
        if self._env is not None:
            self._latch.set_envelope_text(self._envelope_html(self._env))
        # The HazardSurface caches its stripe/hatch colours + pins an opaque
        # instance fill per theme at construction, so a live light/dark switch
        # must re-resolve them (same idiom as BiasPanel.refresh_theme).
        self._hazard.refresh_theme(self._theme_mode)

    def shutdown(self) -> None:
        """Stop the latch's owned timers before teardown (panel ``shutdown()``
        idiom).  Idempotent."""
        self._latch.shutdown()
