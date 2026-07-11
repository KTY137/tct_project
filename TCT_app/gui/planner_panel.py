"""Scan Routine Planner — the "Recipe Tree" panel (Phase 2.2 step 3).

Renders a :class:`~controller.scan_plan.ScanPlan` as an editable tree
(loops rail-coloured per axis, action leaves, decorative guard/danger rows)
plus a "Before you run" safety card (live estimate + validation + the
Validate / Dry Run / Arm HV / Start latch chain).

Pure GUI: this module never talks to hardware and never imports a device
backend. It only knows the three pure planner modules
(``controller.scan_plan``, ``controller.scan_plan_validator``,
``controller.plan_estimate``) plus ``controller.scan_plan_validator.PlanLimits``.
Wiring ``start_plan_requested``/``arm_hv_requested`` to a real
``ScanController`` (and bridging its plain-callback progress/error hooks back
onto this panel's slots via a Qt signal — see the module docstring note below)
is ``tct_gui.py``'s job, not this panel's.

Safety latch (mirrors the design-preview HTML in
``artifacts_claude/scan_planner_preview_claude.html``): **any** edit to the
plan invalidates a prior Dry Run / Arm — Start only re-enables after a fresh
Dry Run (``dry_run_ok``) *and* an externally-confirmed HV arm
(``set_hv_armed(True)``), true "per-run" latches, never assumed from a
previous run.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import (
    QByteArray, QObject, Qt, QMimeData, QSettings, QThread, QTimer, Signal, Slot,
)
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from controller.plan_estimate import PlanEstimate, estimate_plan
from controller.scan_plan import (
    ActionBlock, ActionType, Axis, LoopBlock, STAGE_AXES, ScanBlock, ScanPlan,
)
from controller.scan_plan_validator import PlanIssue, PlanLimits, validate_plan
from gui.status_bus import notify
from gui.status_widgets import StatusChip, flash_button, set_button_icon
from gui.style import DARK, LIGHT, axis_color, repolish

# --------------------------------------------------------------------------- #
# Drag & drop wire format                                                     #
# --------------------------------------------------------------------------- #
#
# One custom MIME type carries both drop kinds as a small JSON payload:
#   {"op": "new",  "block": {...ScanBlock.to_dict()...}}   -- from the palette
#   {"op": "move", "path": [child indices from plan.root]} -- tree-internal drag
#
# The tree NEVER lets Qt's own internal item-move machinery touch
# QTreeWidgetItems directly (that would orphan the setItemWidget() row
# widgets) -- every accepted drop instead goes: decode -> mutate the
# ScanPlan -> rebuild the tree from the plan.  Item `UserRole` data carries
# the live block object (existing v1 behaviour); `UserRole + 1` carries that
# item's path (child indices from root) so drops can be resolved without
# reconstructing paths from tree geometry.  Decorative rows (preflight/
# guard/danger/settle) carry neither and are therefore never draggable and
# never a valid drop target.
_MIME_TYPE = "application/x-tct-plan-block"
_ROLE_BLOCK = Qt.ItemDataRole.UserRole
_ROLE_PATH = Qt.ItemDataRole.UserRole + 1
_UNDO_CAP = 20


def _split_path(path: list[int]) -> tuple[list[int] | None, int]:
    """Split a block path into ``(parent_path, index)``; ``parent_path`` is
    ``None`` when the block lives directly in ``plan.root``."""
    if len(path) == 1:
        return None, path[0]
    return list(path[:-1]), path[-1]


def _block_at_path(root: list, path: list[int]):
    block = root[path[0]]
    for idx in path[1:]:
        block = block.children[idx]
    return block


def _list_for_parent(root: list, parent_path: list[int] | None) -> list:
    """The concrete list a block lives/will-live in: ``root`` itself when
    ``parent_path`` is ``None``, else that ancestor loop's ``children``."""
    if parent_path is None:
        return root
    return _block_at_path(root, parent_path).children


def _new_loop_defaults(axis: Axis) -> LoopBlock:
    """Sensible start/stop/step defaults for a freshly dropped loop block."""
    if axis == Axis.STAGE_Z:
        return LoopBlock(axis=axis, start=-2.0, stop=2.0, step=0.1)
    if axis == Axis.BIAS_V:
        return LoopBlock(axis=axis, start=0.0, stop=-100.0, step=-20.0)
    return LoopBlock(axis=axis, start=-1.0, stop=1.0, step=0.1)


def _new_action_defaults(action: ActionType) -> ActionBlock:
    """Sensible params defaults for a freshly dropped action block."""
    if action == ActionType.ACQUIRE_WAVEFORM:
        return ActionBlock(action=action, params={"n_averages": 64})
    if action == ActionType.WAIT:
        return ActionBlock(action=action, params={"seconds": 1.0})
    return ActionBlock(action=action, params={})


# --------------------------------------------------------------------------- #
# Axis presentation                                                            #
# --------------------------------------------------------------------------- #

_AXIS_UI_KEY: dict[Axis, str] = {
    Axis.STAGE_X: "x", Axis.STAGE_Y: "y", Axis.STAGE_Z: "z", Axis.BIAS_V: "bias",
}
_AXIS_LABEL: dict[Axis, str] = {
    Axis.STAGE_X: "stage x", Axis.STAGE_Y: "stage y", Axis.STAGE_Z: "stage z",
    Axis.BIAS_V: "bias",
}
_ACTION_UI: dict[ActionType, tuple[str, str]] = {
    ActionType.ACQUIRE_WAVEFORM: ("◠", "Acquire waveform"),
    ActionType.SAVE_POINT: ("▤", "Save point"),
    ActionType.WAIT: ("⏱", "Wait"),
    ActionType.MANUAL_PAUSE: ("✋", "Manual pause"),
    ActionType.READ_SLOW_CONTROL: ("\U0001f321", "Read slow control"),
}


def _axis_ui_key(axis: Axis) -> str:
    return _AXIS_UI_KEY.get(axis, "bias")


def _rgba(hex_color: str, alpha: float) -> str:
    """Hex ``#rrggbb`` -> ``rgba(r,g,b,alpha)`` for translucent inline QSS."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _fmt_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.1f} min"
    return f"{minutes / 60.0:.1f} h"


def _fmt_duration_delta(delta_seconds: float) -> str:
    """Signed runtime delta for the drop delta-preview chip, e.g. ``+2.2 h``
    or ``-30 s``. Reuses :func:`_fmt_duration` for the magnitude so it stays
    visually consistent with the "Est. runtime" chip."""
    sign = "+" if delta_seconds >= 0 else "-"
    return f"{sign}{_fmt_duration(abs(delta_seconds))}"


def _fmt_data(num_bytes: int) -> str:
    mb = num_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def _fmt_travel(mm: float) -> str:
    if mm >= 1000:
        return f"{mm / 1000:.2f} m"
    return f"{mm:.0f} mm"


def _default_template_plan() -> ScanPlan:
    """Bias -> X -> Y (snake) raster, matching the design-preview default
    routine: ramp HV, then a snake XY map acquiring + saving at every point."""
    acquire = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={"n_averages": 64})
    save = ActionBlock(action=ActionType.SAVE_POINT, params={})
    y_loop = LoopBlock(
        axis=Axis.STAGE_Y, start=-1.0, stop=1.0, step=0.1,
        settle_s=0.05, snake=True, children=[acquire, save],
    )
    x_loop = LoopBlock(axis=Axis.STAGE_X, start=-1.0, stop=1.0, step=0.1,
                        children=[y_loop])
    bias_loop = LoopBlock(axis=Axis.BIAS_V, start=0.0, stop=-300.0, step=-50.0,
                           children=[x_loop])
    return ScanPlan(
        name="edge_tct_template",
        description="Edge-TCT CCE(V) map — bias -> x -> y snake (default template)",
        root=[bias_loop],
        safety={"require_hv_confirmation": True},
    )


class _PaletteList(QListWidget):
    """Draggable "Add blocks" palette: 4 loop templates + 5 action templates.

    Every entry's ``UserRole`` data is the drop payload itself
    (``{"op": "new", "block": {...}}``) so a palette drag and a tree-internal
    move share the exact same MIME format and the exact same drop-decision
    path on the receiving :class:`_RecipeTree`.
    """

    itemActivatedForAppend = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plannerPalette")
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.itemDoubleClicked.connect(self._on_double_clicked)

    def mimeTypes(self) -> list[str]:
        return [_MIME_TYPE]

    def mimeData(self, items):  # noqa: N802 - Qt override signature
        mime = QMimeData()
        item = items[0] if items else None
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(payload, dict):
            mime.setData(_MIME_TYPE, QByteArray(json.dumps(payload).encode("utf-8")))
        return mime

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(payload, dict):
            self.itemActivatedForAppend.emit(payload)


class _RecipeTree(QTreeWidget):
    """The Recipe Tree's ``QTreeWidget``, wired for drag & drop.

    All drag/drop *decisions* (is this a valid target? what does a drop here
    mean as a plan mutation?) live on :class:`PlannerPanel` as plain-Python
    methods so they are unit-testable without constructing real Qt drag
    events. This widget only turns Qt events into ``(item, indicator)`` pairs
    and asks the panel; on an accepted drop it hands the panel the decoded
    mutation and lets the panel rebuild the tree from the plan. It never lets
    Qt's own internal item-move machinery touch a ``QTreeWidgetItem`` (that
    would orphan the row's ``setItemWidget`` widget) — ``dropEvent`` never
    calls ``super().dropEvent()``.
    """

    def __init__(self, panel: "PlannerPanel", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panel = panel
        self.setObjectName("recipeTree")
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def mimeTypes(self) -> list[str]:
        return [_MIME_TYPE]

    def mimeData(self, items):  # noqa: N802 - Qt override signature
        mime = QMimeData()
        item = items[0] if items else None
        path = item.data(0, _ROLE_PATH) if item is not None else None
        if path is not None:
            payload = {"op": "move", "path": list(path)}
            mime.setData(_MIME_TYPE, QByteArray(json.dumps(payload).encode("utf-8")))
        return mime

    def _indicator_for_point(self, item: QTreeWidgetItem | None, point) -> str:
        """"above" / "on" / "below" a *real* row, else "viewport" (empty
        area — append to root). Computed from row geometry directly instead
        of Qt's ``dropIndicatorPosition()`` since ``dragMoveEvent`` below
        never calls the base implementation that would otherwise track it."""
        if item is None:
            return "viewport"
        rect = self.visualItemRect(item)
        if rect.height() <= 0:
            return "on"
        third = max(1.0, rect.height() / 3.0)
        y = point.y() - rect.top()
        if y < third:
            return "above"
        if y > rect.height() - third:
            return "below"
        return "on"

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_TYPE):
            self._panel._ghost_key = None   # fresh gesture: force a real recompute
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        point = event.position().toPoint()
        item = self.itemAt(point)
        if item is self._panel._ghost_item:
            # Hovering the ghost's OWN preview row: nothing about the
            # candidate slot changed (it can't be a drop target itself,
            # _mark_decorative-style — see PlannerPanel._place_ghost), so
            # keep accepting without touching/flickering the existing
            # preview instead of resolving geometry against a fake target.
            if self._panel._ghost_item is not None:
                event.acceptProposedAction()
            else:
                event.ignore()
            return
        indicator = self._indicator_for_point(item, point)
        decision = self._panel._preview_drag(event.mimeData(), item, indicator)
        if decision is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._panel._clear_drag_preview()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        point = event.position().toPoint()
        item = self.itemAt(point)
        if item is self._panel._ghost_item:
            # Released directly on the ghost row -- reuse the decision that
            # placed it rather than resolving geometry against a fake target.
            decision = self._panel._ghost_decision
        else:
            indicator = self._indicator_for_point(item, point)
            decision = self._panel._plan_drop_decision(event.mimeData(), item, indicator)
        self._panel._clear_drag_preview()
        if decision is None:
            event.ignore()
            return
        dest_parent_path, dest_index, payload = decision
        self._panel._apply_drop(dest_parent_path, dest_index, payload)
        event.acceptProposedAction()


class _EstimateWorker(QObject):
    """Runs a pure :class:`~controller.scan_plan.ScanPlan` cost estimate off the
    GUI thread.

    A huge plan's estimate walks every materialised leaf visit (hundreds of
    thousands to millions of them) — a multi-hundred-ms CPU walk.  Doing that in
    the panel's debounced recompute slot stalled the whole window: the founding
    breach of the three-layer law (compute must NEVER block the GUI thread; see
    ``docs/research/qml_hybrid_architecture.md`` §9, R6).  Requests arrive here
    as *queued* invocations carrying a monotonic ``seq`` so the panel can
    discard a stale result.  Pure compute: it touches no hardware and no
    QWidget — the plan crosses the thread boundary as a plain ``dict`` snapshot
    taken on the GUI thread, reconstructed here, so the live plan object the GUI
    thread keeps mutating is never shared.
    """

    done = Signal(int, object, str)   # seq, PlanEstimate|None, error

    @Slot(int, dict)
    def run_estimate(self, seq: int, plan_dict: dict) -> None:
        try:
            estimate = estimate_plan(ScanPlan.from_dict(plan_dict))
        except Exception as exc:   # reported to the GUI, never re-raised on the worker
            self.done.emit(seq, None, str(exc))
            return
        self.done.emit(seq, estimate, "")


class PlannerPanel(QWidget):
    """The Scan Routine Planner: Recipe Tree + "Before you run" safety card.

    Signals
    -------
    start_plan_requested(object)
        Emitted with the live :class:`~controller.scan_plan.ScanPlan` when the
        user presses Start. Only reachable when both latches are set (armed
        AND a fresh dry run passed) — see :meth:`_update_start_enabled`.
    arm_hv_requested()
        Emitted after the user confirms the local "Arm HV" dialog. The panel
        does NOT assume arming succeeded — call :meth:`set_hv_armed` back
        once the controller actually confirms it armed (or refused).
    abort_requested()
        Emitted when the user presses the panel's Abort button during a run.

    Public slots (safe to connect from a Qt-signal bridge only — see the
    module docstring: never call these directly from a worker thread)
    --------------------------------------------------------------------
    set_hv_armed(bool), set_limits(PlanLimits), set_running(bool),
    on_progress(int, int), on_finished(), on_error(str),
    set_position_from_motor(float, float, float) — stores the latest motor
    position (no hardware I/O) for the "Use current position" affordance;
    connect this to ``MotorPanel.set_as_scan_start`` in place of the retired
    ``ScanPanel.set_start_position``.
    set_focus_z(float) — stores the Scan Viewer's Z-focus best-Z result (no
    hardware I/O) for the "Use focus Z" affordance; connect this to
    ``ScanViewerPanel.best_z_apply_requested`` (design doc gap G4). Staging
    only, mirrors ``set_position_from_motor``: select a stage-Z loop row,
    then "Use focus Z" writes the stored value into that loop's start field.
    """

    start_plan_requested = Signal(object)
    arm_hv_requested = Signal()
    abort_requested = Signal()
    # GUI → estimate worker: (seq, plan_dict).  Cross-thread → Qt queues it, so
    # the worker's event queue preserves submission order (see _EstimateWorker).
    _submit_estimate = Signal(int, dict)

    _DEFAULT_LIMITS = PlanLimits(
        x_min_mm=-5.0, x_max_mm=5.0,
        y_min_mm=-5.0, y_max_mm=5.0,
        z_min_mm=-5.0, z_max_mm=5.0,
        voltage_range_V=3000.0, max_points=250_000,
    )

    def __init__(self, parent: QWidget | None = None,
                 limits: PlanLimits | None = None) -> None:
        super().__init__(parent)
        self._theme_mode = str(QSettings("TCT", "TCTSetup").value("theme", "light"))
        self._limits: PlanLimits = limits or self._DEFAULT_LIMITS
        self._plan: ScanPlan = _default_template_plan()
        self._hv_armed = False
        self._dry_run_ok = False
        self._running = False
        self._loop_editors: dict[int, dict[str, QDoubleSpinBox]] = {}
        self._issue_labels: list[QLabel] = []
        self._undo_stack: list[dict] = []
        # Latest motor position, received (no hardware I/O) via
        # set_position_from_motor -- staged for the "Use current position"
        # affordance, see the "Motor position -> loop start" section below.
        self._motor_pos: tuple[float, float, float] | None = None
        # Latest Z-focus best-Z result, received (no hardware I/O) via
        # set_focus_z -- staged for the "Use focus Z" affordance (G4), see
        # the same section below.
        self._focus_z: float | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._on_debounced_edit)

        # Drag-drop ghost/delta preview (never touches self._plan or the
        # undo stack -- see the "Drag & drop preview" section below).
        self._ghost_item: QTreeWidgetItem | None = None
        self._ghost_key: tuple | None = None
        self._ghost_decision: tuple | None = None
        self._pending_preview: tuple | None = None
        self._preview_debounce = QTimer(self)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.setInterval(150)
        self._preview_debounce.timeout.connect(self._on_preview_debounce_timeout)
        # ── Off-thread plan estimate ─────────────────────────────────────
        # A huge plan's cost estimate is a multi-hundred-ms leaf walk; running
        # it inline in the debounced recompute slot stalled the window (the
        # founding breach of the three-layer law — compute must never block the
        # GUI thread).  Plans above _estimate_async_threshold leaf visits run on
        # a persistent worker thread, delivered as a queued invocation carrying
        # a monotonic seq; smaller plans stay inline (no round-trip).  The
        # thread is parented to the long-lived QApplication (NOT this panel): a
        # soft config-reload deletes the panel tree via setCentralWidget(), and
        # a QThread destroyed as a child while still running is a hard Qt6 abort
        # (the MotorPanel crash class).  shutdown() stops it with a bounded
        # wait; it self-deletes on ``finished``.
        self._estimate_async_threshold = 50_000
        self._estimate_seq = 0                     # monotonic request id (generation)
        self._estimate_inflight = False            # a job is on the worker now
        self._estimate_inflight_key: str | None = None
        self._estimate_pending: tuple[int, str, dict] | None = None
        self._last_estimate: PlanEstimate | None = None
        self._last_estimate_key: str | None = None
        self._estimate_thread: QThread | None = QThread(QApplication.instance())
        self._estimate_worker: _EstimateWorker | None = _EstimateWorker()
        self._estimate_worker.moveToThread(self._estimate_thread)
        self._submit_estimate.connect(self._estimate_worker.run_estimate)
        self._estimate_worker.done.connect(self._on_estimate_done)
        self._estimate_thread.finished.connect(self._estimate_worker.deleteLater)
        self._estimate_thread.finished.connect(self._estimate_thread.deleteLater)
        self._estimate_thread.start()

        self._build_ui()
        self._rebuild_tree()
        self._rebuild_legend()
        self._recompute_estimate()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- top bar ----------------------------------------------------
        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        eyebrow = QLabel("TCT CONTROL · RECIPE")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Scan Routine Planner")
        title.setStyleSheet("font-size: 16px; font-weight: 640;")
        title_col.addWidget(eyebrow)
        title_col.addWidget(title)
        top.addLayout(title_col)
        top.addStretch(1)
        self._btn_save_routine = QPushButton("Save Routine…")
        set_button_icon(self._btn_save_routine, "mdi.content-save")
        self._btn_load_routine = QPushButton("Load Routine…")
        set_button_icon(self._btn_load_routine, "mdi.folder-open")
        top.addWidget(self._btn_save_routine)
        top.addWidget(self._btn_load_routine)
        root.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        # ---- "add blocks" palette -----------------------------------------
        body.addWidget(self._build_palette(), 0)

        # ---- recipe tree card --------------------------------------------
        tree_card = QFrame()
        tree_card.setObjectName("cardPane")
        tree_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tree_lay = QVBoxLayout(tree_card)
        tree_lay.setContentsMargins(0, 0, 0, 0)
        tree_lay.setSpacing(0)

        tree_hd = QHBoxLayout()
        tree_hd.setContentsMargins(14, 12, 14, 8)
        recipe_lbl = QLabel("Recipe")
        recipe_lbl.setStyleSheet("font-weight: 600;")
        sub_lbl = QLabel("edge-TCT · CCE(V) map · drag to reorder, right-click for more")
        sub_lbl.setObjectName("plannerLeafMeta")
        tree_hd.addWidget(recipe_lbl)
        tree_hd.addStretch(1)
        tree_hd.addWidget(sub_lbl)
        tree_lay.addLayout(tree_hd)

        # "Use current position" -- select an X/Y/Z loop below, then this
        # writes the last motor position (see set_position_from_motor) into
        # THAT loop's start field. A plan has no single "start position"
        # (only per-axis loops), so this replaces ScanPanel.set_start_position
        # as the target of MotorPanel.set_as_scan_start (design doc gap G3).
        #
        # "Use focus Z" mirrors the exact same pattern for the Scan Viewer's
        # Z-focus assist (design doc gap G4): select a stage-Z loop, then it
        # writes the last best-Z result (see set_focus_z) into THAT loop's
        # start field only -- never the motor, never a running plan.
        motor_row = QHBoxLayout()
        motor_row.setContentsMargins(14, 0, 14, 8)
        motor_row.setSpacing(8)
        self._lbl_motor_pos = QLabel("Motor position not received yet")
        self._lbl_motor_pos.setObjectName("plannerLeafMeta")
        motor_row.addWidget(self._lbl_motor_pos)
        self._lbl_focus_z = QLabel("Focus Z: --")
        self._lbl_focus_z.setObjectName("plannerLeafMeta")
        motor_row.addWidget(self._lbl_focus_z)
        motor_row.addStretch(1)
        self._btn_use_motor_pos = QPushButton("Use current position")
        set_button_icon(self._btn_use_motor_pos, "mdi.crosshairs-gps")
        self._btn_use_motor_pos.setToolTip(
            "Write the last motor position into the selected loop's start "
            "field (select an X/Y/Z loop below first)"
        )
        self._btn_use_motor_pos.setEnabled(False)
        motor_row.addWidget(self._btn_use_motor_pos)
        self._btn_use_focus_z = QPushButton("Use focus Z")
        set_button_icon(self._btn_use_focus_z, "mdi.target-variant")
        self._btn_use_focus_z.setToolTip(
            "Write the last Z-focus result into the selected stage-Z loop's "
            "start field (select a stage-Z loop below first)"
        )
        self._btn_use_focus_z.setEnabled(False)
        motor_row.addWidget(self._btn_use_focus_z)
        tree_lay.addLayout(motor_row)

        self._tree = _RecipeTree(self)
        self._tree.setColumnCount(1)
        self._tree.header().hide()
        self._tree.setIndentation(16)
        self._tree.setRootIsDecorated(True)
        # SingleSelection (not the v1 NoSelection) so Qt's standard drag
        # gesture has a selected index to hand to mimeData(); the native
        # selection tint is suppressed below since every row already carries
        # its own custom-styled setItemWidget() frame.
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tree.setStyleSheet(
            "QTreeWidget#recipeTree::item:selected { background: transparent; }"
        )
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        tree_lay.addWidget(self._tree, 1)

        legend_widget = QWidget()
        self._legend_row = QHBoxLayout(legend_widget)
        self._legend_row.setContentsMargins(14, 8, 14, 10)
        self._legend_row.setSpacing(14)
        tree_lay.addWidget(legend_widget)

        body.addWidget(tree_card, 2)

        # ---- "before you run" card ---------------------------------------
        aside = QFrame()
        aside.setObjectName("cardPane")
        aside.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        aside.setMaximumWidth(340)
        aside_lay = QVBoxLayout(aside)
        aside_lay.setContentsMargins(14, 12, 14, 14)
        aside_lay.setSpacing(10)

        hd = QLabel("BEFORE YOU RUN")
        hd.setObjectName("eyebrow")
        aside_lay.addWidget(hd)

        stats_form = QFormLayout()
        stats_form.setSpacing(6)
        self._chip_points = StatusChip("—", "neutral")
        self._chip_runtime = StatusChip("—", "neutral")
        self._chip_data = StatusChip("—", "neutral")
        self._chip_travel = StatusChip("—", "neutral")
        self._chip_hv = StatusChip("—", "neutral")
        stats_form.addRow("Total points:", self._chip_points)
        stats_form.addRow("Est. runtime:", self._chip_runtime)
        stats_form.addRow("Est. data:", self._chip_data)
        stats_form.addRow("Stage travel:", self._chip_travel)
        stats_form.addRow("HV range:", self._chip_hv)
        aside_lay.addLayout(stats_form)

        # Drop delta preview -- "Preview: 3,087 -> 9,261 pts . +2h 10m", only
        # visible while a valid drag candidate is hovering the tree; never
        # reflects a real mutation, see _render_delta_preview().
        self._chip_delta_preview = StatusChip("", "neutral")
        self._chip_delta_preview.setWordWrap(True)
        self._chip_delta_preview.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._chip_delta_preview.setVisible(False)
        aside_lay.addWidget(self._chip_delta_preview)

        self._issues_layout = QVBoxLayout()
        self._issues_layout.setSpacing(4)
        aside_lay.addLayout(self._issues_layout)

        self._chip_hv_status = StatusChip("HV disarmed — Start is locked", "warn")
        self._chip_hv_status.setWordWrap(True)
        aside_lay.addWidget(self._chip_hv_status)

        btn_grid = QGridLayout()
        btn_grid.setSpacing(8)
        self._btn_validate = QPushButton("Validate")
        self._btn_dry_run = QPushButton("Dry Run")
        self._btn_arm = QPushButton("⚡ Arm HV")
        self._btn_start = QPushButton("▶ Start")
        self._btn_start.setEnabled(False)
        btn_grid.addWidget(self._btn_validate, 0, 0)
        btn_grid.addWidget(self._btn_dry_run, 0, 1)
        btn_grid.addWidget(self._btn_arm, 1, 0, 1, 2)
        btn_grid.addWidget(self._btn_start, 2, 0, 1, 2)
        aside_lay.addLayout(btn_grid)

        self._btn_abort = QPushButton("⏹ Abort")
        self._btn_abort.setObjectName("dangerBtn")
        self._btn_abort.setEnabled(False)
        aside_lay.addWidget(self._btn_abort)

        aside_lay.addStretch(1)
        body.addWidget(aside, 0)

        # ---- wiring -------------------------------------------------------
        self._btn_validate.clicked.connect(self._on_validate_clicked)
        self._btn_dry_run.clicked.connect(self._on_dry_run_clicked)
        self._btn_arm.clicked.connect(self._on_arm_clicked)
        self._btn_start.clicked.connect(self._on_start_clicked)
        self._btn_abort.clicked.connect(self.abort_requested.emit)
        self._btn_save_routine.clicked.connect(self._on_save_routine)
        self._btn_load_routine.clicked.connect(self._on_load_routine)
        self._btn_use_motor_pos.clicked.connect(self._on_use_motor_position_clicked)
        self._btn_use_focus_z.clicked.connect(self._on_use_focus_z_clicked)

        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._undo_shortcut.activated.connect(self._undo)

        self.set_hv_armed(False)

    # ------------------------------------------------------------------ #
    # "Add blocks" palette                                                 #
    # ------------------------------------------------------------------ #

    def _build_palette(self) -> QFrame:
        card = QFrame()
        card.setObjectName("cardPane")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setMaximumWidth(200)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hd = QHBoxLayout()
        hd.setContentsMargins(12, 12, 12, 6)
        lbl = QLabel("Add blocks")
        lbl.setStyleSheet("font-weight: 600;")
        hd.addWidget(lbl)
        hd.addStretch(1)
        lay.addLayout(hd)

        self._btn_undo = QPushButton("Undo")
        set_button_icon(self._btn_undo, "mdi.undo")
        self._btn_undo.setEnabled(False)
        self._btn_undo.setToolTip("Undo the last structural change (Ctrl+Z)")
        self._btn_undo.clicked.connect(self._undo)
        undo_row = QHBoxLayout()
        undo_row.setContentsMargins(12, 0, 12, 6)
        undo_row.addWidget(self._btn_undo)
        lay.addLayout(undo_row)

        hint = QLabel("Drag into the recipe, or double-click to append")
        hint.setObjectName("plannerLeafMeta")
        hint.setWordWrap(True)
        hint.setContentsMargins(12, 0, 12, 6)
        lay.addWidget(hint)

        self._palette = _PaletteList()
        self._populate_palette()
        self._palette.itemActivatedForAppend.connect(self._on_palette_append)
        lay.addWidget(self._palette, 1)
        return card

    def _populate_palette(self) -> None:
        self._palette.clear()
        for axis in (Axis.BIAS_V, Axis.STAGE_X, Axis.STAGE_Y, Axis.STAGE_Z):
            loop = _new_loop_defaults(axis)
            color = axis_color(_axis_ui_key(axis), self._theme_mode)
            item = QListWidgetItem(f"LOOP · {_AXIS_LABEL[axis]}")
            item.setData(Qt.ItemDataRole.UserRole, {"op": "new", "block": loop.to_dict()})
            item.setForeground(QColor(color))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setToolTip(f"Drag to add a {_AXIS_LABEL[axis]} loop")
            self._palette.addItem(item)
        for action in (
            ActionType.ACQUIRE_WAVEFORM, ActionType.SAVE_POINT, ActionType.WAIT,
            ActionType.MANUAL_PAUSE, ActionType.READ_SLOW_CONTROL,
        ):
            block = _new_action_defaults(action)
            glyph, label = _ACTION_UI[action]
            item = QListWidgetItem(f"{glyph}  {label}")
            item.setData(Qt.ItemDataRole.UserRole, {"op": "new", "block": block.to_dict()})
            item.setToolTip(f"Drag to add a {label.lower()} action")
            self._palette.addItem(item)

    def _on_palette_append(self, payload: dict) -> None:
        """Accessibility fallback for the drag gesture: double-click a
        palette entry to append it to the plan root."""
        self._apply_drop(None, len(self._plan.root), payload)

    # ------------------------------------------------------------------ #
    # Recipe tree construction                                            #
    # ------------------------------------------------------------------ #

    def _rebuild_tree(self) -> None:
        collapsed_ids = self._snapshot_expansion()
        self._tree.clear()
        self._loop_editors.clear()
        preflight = QTreeWidgetItem(self._tree)
        preflight.setFlags(
            preflight.flags() & ~Qt.ItemFlag.ItemIsDragEnabled
            & ~Qt.ItemFlag.ItemIsSelectable
        )
        self._tree.setItemWidget(
            preflight, 0,
            self._make_guard_row("Preflight", "interlocks · laser safe · stage homed"),
        )
        for i, block in enumerate(self._plan.root):
            self._add_block(self._tree, block, [i])
        self._tree.expandAll()
        self._restore_expansion(collapsed_ids)
        # tree.clear() drops the selection -- re-evaluate (normally disables
        # until the user reselects a row in the rebuilt tree).
        self._update_use_position_enabled()

    def _snapshot_expansion(self) -> set[int]:
        """``id(block)`` of every currently-collapsed *real* node (default is
        expanded, so we only need to remember the exceptions). Keyed by
        object identity rather than tree path since a structural mutation
        (e.g. a move) can change a block's path while it is the SAME Python
        object -- identity survives the rebuild, a stale path would not."""
        collapsed: set[int] = set()

        def walk(item: QTreeWidgetItem) -> None:
            block = item.data(0, _ROLE_BLOCK)
            if block is not None and not item.isExpanded():
                collapsed.add(id(block))
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i))
        return collapsed

    def _restore_expansion(self, collapsed_ids: set[int]) -> None:
        if not collapsed_ids:
            return

        def walk(item: QTreeWidgetItem) -> None:
            block = item.data(0, _ROLE_BLOCK)
            if block is not None and id(block) in collapsed_ids:
                item.setExpanded(False)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i))

    def _item_for_block(self, block) -> QTreeWidgetItem | None:
        """Find the tree item carrying *block* by identity (used by drag/
        drop path lookups and tests alike)."""
        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, _ROLE_BLOCK) is block:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(self._tree.topLevelItemCount()):
            found = walk(self._tree.topLevelItem(i))
            if found is not None:
                return found
        return None

    def _path_for_block(self, block) -> list[int] | None:
        item = self._item_for_block(block)
        return item.data(0, _ROLE_PATH) if item is not None else None

    def _add_block(self, parent, block, path: list[int]) -> None:
        if isinstance(block, LoopBlock):
            item = QTreeWidgetItem(parent)
            item.setData(0, _ROLE_BLOCK, block)
            item.setData(0, _ROLE_PATH, list(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            self._tree.setItemWidget(item, 0, self._make_loop_row(block))
            if block.axis == Axis.BIAS_V:
                danger_item = QTreeWidgetItem(item)
                self._mark_decorative(danger_item)
                self._tree.setItemWidget(
                    danger_item, 0,
                    self._make_danger_row("Ramp HV", "to setpoint · 5 V steps · 100 ms"),
                )
                guard_item = QTreeWidgetItem(item)
                self._mark_decorative(guard_item)
                self._tree.setItemWidget(
                    guard_item, 0,
                    self._make_guard_row("Check leakage", "abort + ramp down if I > 2 µA"),
                )
            elif block.axis in STAGE_AXES and any(
                isinstance(c, ActionBlock) for c in block.children
            ):
                move_item = QTreeWidgetItem(item)
                self._mark_decorative(move_item)
                self._tree.setItemWidget(
                    move_item, 0, self._make_danger_row("Move stage", "→ (x, y, z)"),
                )
                settle_item = QTreeWidgetItem(item)
                self._mark_decorative(settle_item)
                self._tree.setItemWidget(
                    settle_item, 0, self._make_settle_row(block.settle_s),
                )
            for j, child in enumerate(block.children):
                self._add_block(item, child, path + [j])
        elif isinstance(block, ActionBlock):
            item = QTreeWidgetItem(parent)
            item.setData(0, _ROLE_BLOCK, block)
            item.setData(0, _ROLE_PATH, list(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            self._tree.setItemWidget(item, 0, self._make_action_leaf_row(block))

    @staticmethod
    def _mark_decorative(item: QTreeWidgetItem) -> None:
        """Decorative rows (guard/danger/settle/preflight) carry neither a
        block nor a path — they re-derive from the plan and are never
        draggable and never a valid drop target (see ``_plan_drop_decision``,
        which rejects any target item whose ``_ROLE_PATH`` is ``None``)."""
        item.setFlags(
            item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled
            & ~Qt.ItemFlag.ItemIsSelectable
        )

    # -- row widget factories -------------------------------------------

    def _make_value_spin(self, value: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setObjectName("plannerValueSpin")
        spin.setDecimals(decimals)
        spin.setRange(-1_000_000.0, 1_000_000.0)
        spin.setSingleStep(10 ** (-decimals))
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        spin.setFixedWidth(76)
        spin.setValue(float(value))
        return spin

    def _make_loop_row(self, loop: LoopBlock) -> QWidget:
        axis_key = _axis_ui_key(loop.axis)
        unit = "V" if loop.axis == Axis.BIAS_V else "mm"
        decimals = 1 if loop.axis == Axis.BIAS_V else 3
        color = axis_color(axis_key, self._theme_mode)

        frame = QFrame()
        frame.setObjectName("plannerLoopHead")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        frame.setStyleSheet(f"#plannerLoopHead {{ border-left: 3px solid {color}; }}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        tag = QLabel("LOOP")
        tag.setObjectName("plannerTag")
        tag.setStyleSheet(
            f"#plannerTag {{ color: {color}; background: {_rgba(color, 0.16)}; }}"
        )
        lay.addWidget(tag)

        name = QLabel(_AXIS_LABEL[loop.axis])
        name.setObjectName("plannerAxisName")
        name.setStyleSheet(f"#plannerAxisName {{ color: {color}; }}")
        lay.addWidget(name)

        count_pill = QLabel()
        count_pill.setObjectName("plannerCountPill")

        if loop.values is not None:
            # v1 skip: explicit ``values`` lists render read-only — only
            # start/stop/step ranges are live-editable in this version.
            vals_lbl = QLabel(f"{len(loop.values)} explicit values")
            vals_lbl.setObjectName("plannerLeafMeta")
            lay.addWidget(vals_lbl)
            lay.addStretch(1)
            lay.addWidget(count_pill)
            self._update_count_pill(count_pill, loop)
            return frame

        start_spin = self._make_value_spin(
            loop.start if loop.start is not None else 0.0, decimals)
        stop_spin = self._make_value_spin(
            loop.stop if loop.stop is not None else 0.0, decimals)
        step_spin = self._make_value_spin(
            loop.step if loop.step is not None else 0.0, decimals)

        lay.addWidget(start_spin)
        lay.addWidget(QLabel("→"))
        lay.addWidget(stop_spin)
        unit_lbl = QLabel(unit)
        unit_lbl.setObjectName("plannerLeafMeta")
        lay.addWidget(unit_lbl)
        step_cap = QLabel("step")
        step_cap.setObjectName("plannerLeafMeta")
        lay.addWidget(step_cap)
        lay.addWidget(step_spin)
        if loop.snake:
            snake_lbl = QLabel("snake")
            snake_lbl.setObjectName("plannerLeafMeta")
            lay.addWidget(snake_lbl)

        lay.addStretch(1)
        lay.addWidget(count_pill)

        self._loop_editors[id(loop)] = {
            "start": start_spin, "stop": stop_spin, "step": step_spin,
        }

        def _on_edit(_value=None, _loop=loop, _pill=count_pill,
                     _s=start_spin, _e=stop_spin, _st=step_spin) -> None:
            _loop.start = _s.value()
            _loop.stop = _e.value()
            _loop.step = _st.value()
            self._update_count_pill(_pill, _loop)
            self._on_plan_edited()

        # Connect AFTER the initial setValue() calls above so loading the
        # existing loop values never fires a spurious "plan edited" signal.
        start_spin.valueChanged.connect(_on_edit)
        stop_spin.valueChanged.connect(_on_edit)
        step_spin.valueChanged.connect(_on_edit)

        self._update_count_pill(count_pill, loop)
        return frame

    def _update_count_pill(self, pill: QLabel, loop: LoopBlock) -> None:
        color = axis_color(_axis_ui_key(loop.axis), self._theme_mode)
        try:
            n = len(loop.materialize())
            pill.setText(f"{n} steps" if loop.axis == Axis.BIAS_V else f"{n} pts")
        except (ValueError, TypeError):
            pill.setText("invalid")
            color = axis_color("hazard", self._theme_mode)
        pill.setStyleSheet(
            f"#plannerCountPill {{ color: {color}; background: {_rgba(color, 0.14)}; "
            f"border: 1px solid {_rgba(color, 0.34)}; }}"
        )

    def _make_leaf_frame(
        self, glyph: str, label: str, meta: str, *,
        frame_name: str = "plannerActionLeaf",
        label_name: str = "plannerLeafLabel",
        glyph_style: str | None = None,
        label_style: str | None = None,
        frame_style: str | None = None,
        trailing: QWidget | None = None,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName(frame_name)
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if frame_style:
            frame.setStyleSheet(frame_style)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(8, 3, 8, 3)
        lay.setSpacing(8)
        g = QLabel(glyph)
        g.setObjectName("plannerLeafGlyph")
        g.setFixedWidth(18)
        if glyph_style:
            g.setStyleSheet(glyph_style)
        l = QLabel(label)
        l.setObjectName(label_name)
        if label_style:
            l.setStyleSheet(label_style)
        m = QLabel(meta)
        m.setObjectName("plannerLeafMeta")
        lay.addWidget(g)
        lay.addWidget(l)
        lay.addStretch(1)
        lay.addWidget(m)
        if trailing is not None:
            lay.addWidget(trailing)
        return frame

    def _leaf_meta_text(self, action: ActionBlock) -> str:
        params = action.params or {}
        if action.action == ActionType.ACQUIRE_WAVEFORM:
            return f"{params.get('n_averages', '—')} avg"
        if action.action == ActionType.SAVE_POINT:
            return "→ HDF5"
        if action.action == ActionType.WAIT:
            return f"{params.get('seconds', 0)} s"
        if action.action == ActionType.MANUAL_PAUSE:
            return str(params.get("prompt") or params.get("message") or "")
        if action.action == ActionType.READ_SLOW_CONTROL:
            return "sensors"
        return ""

    def _make_action_leaf_row(self, action: ActionBlock) -> QWidget:
        glyph, label = _ACTION_UI.get(action.action, ("•", action.action.value))
        return self._make_leaf_frame(glyph, label, self._leaf_meta_text(action))

    def _make_settle_row(self, settle_s: float) -> QWidget:
        return self._make_leaf_frame("⏱", "Settle", f"{settle_s * 1000:.0f} ms")

    def _make_guard_row(self, label: str, meta: str) -> QWidget:
        p = DARK if self._theme_mode == "dark" else LIGHT
        good = p["good"]
        return self._make_leaf_frame(
            "\U0001f6e1", label, meta,
            frame_name="plannerGuard", label_name="plannerGuardLabel",
            glyph_style=f"color: {good};", label_style=f"color: {good};",
            frame_style=(
                f"#plannerGuard {{ border-left: 3px solid {good}; "
                f"background: {_rgba(good, 0.07)}; }}"
            ),
        )

    def _make_danger_row(self, label: str, meta: str) -> QWidget:
        color = axis_color("hazard", self._theme_mode)
        pill = QLabel("⚠ CONFIRM")
        pill.setObjectName("plannerConfirmPill")
        pill.setStyleSheet(
            f"#plannerConfirmPill {{ color: {color}; background: {_rgba(color, 0.15)}; "
            f"border: 1px solid {_rgba(color, 0.42)}; }}"
        )
        return self._make_leaf_frame(
            "⚡", label, meta,
            frame_name="plannerDanger", label_name="plannerDangerLabel",
            glyph_style=f"color: {color};", label_style=f"color: {color};",
            frame_style=(
                f"#plannerDanger {{ border-left: 3px solid {color}; "
                f"background: {_rgba(color, 0.08)}; }}"
            ),
            trailing=pill,
        )

    # ------------------------------------------------------------------ #
    # Motor position -> loop start ("Use current position")               #
    #                                                                      #
    # set_position_from_motor stores the last motor position emitted by   #
    # MotorPanel.set_as_scan_start (no hardware I/O -- it just receives   #
    # the value). A plan has no single "start position" like the retired  #
    # ScanPanel did -- only per-axis loops -- so the affordance is        #
    # per-loop: select an X/Y/Z loop row in the tree, then _btn_use_motor #
    # _pos writes THAT axis's stored coordinate into the loop's start     #
    # spinbox, through the exact same widget (and therefore the exact    #
    # same valueChanged -> plan-edit -> invalidate path) the user would   #
    # touch by hand -- see _make_loop_row's _on_edit closure.             #
    # ------------------------------------------------------------------ #

    def _on_tree_selection_changed(self) -> None:
        self._update_use_position_enabled()

    def _selected_axis_loop(self) -> LoopBlock | None:
        """The :class:`LoopBlock` behind the currently-selected tree row,
        if (and only if) it is a live-editable X/Y/Z stage loop -- the only
        kind this affordance can write into. Bias has no stage coordinate;
        an explicit ``values`` loop has no start field (v1 skip, see
        ``_make_loop_row``) and so never gets a ``_loop_editors`` entry."""
        item = self._tree.currentItem()
        if item is None:
            return None
        block = item.data(0, _ROLE_BLOCK)
        if (isinstance(block, LoopBlock) and block.axis in STAGE_AXES
                and id(block) in self._loop_editors):
            return block
        return None

    def _update_use_position_enabled(self) -> None:
        # Gated on not-running: the tree is disabled during a run, so the
        # programmatic spinbox write must be locked out with it.
        axis_loop = self._selected_axis_loop()
        self._btn_use_motor_pos.setEnabled(
            not self._running
            and self._motor_pos is not None
            and axis_loop is not None
        )
        # "Use focus Z" is narrower still: a Z-focus result only ever means
        # something for the stage-Z axis (X/Y loops have no focus concept).
        self._btn_use_focus_z.setEnabled(
            not self._running
            and self._focus_z is not None
            and axis_loop is not None
            and axis_loop.axis == Axis.STAGE_Z
        )

    def _on_use_motor_position_clicked(self) -> None:
        loop = self._selected_axis_loop()
        if loop is None or self._motor_pos is None:
            return
        x_mm, y_mm, z_mm = self._motor_pos
        value = {
            Axis.STAGE_X: x_mm, Axis.STAGE_Y: y_mm, Axis.STAGE_Z: z_mm,
        }[loop.axis]
        self._loop_editors[id(loop)]["start"].setValue(value)

    def _on_use_focus_z_clicked(self) -> None:
        loop = self._selected_axis_loop()
        if loop is None or loop.axis != Axis.STAGE_Z or self._focus_z is None:
            return
        # Write ONLY start, through the exact same widget (and therefore the
        # same valueChanged -> plan-edit -> invalidate path) "Use current
        # position" uses above. A fixed-Z 2D raster is a Z loop with
        # start == stop (see controller.scan_plan.LoopBlock.materialize --
        # a zero span always collapses to the single point `start`
        # regardless of step), so writing start alone is the honest minimal
        # action here too: the user still owns stop (and step), nothing new
        # is invented in the plan model.
        self._loop_editors[id(loop)]["start"].setValue(self._focus_z)

    @Slot(float, float, float)
    def set_position_from_motor(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        """Store the latest stage position (no hardware I/O -- this only
        receives what the caller already read). Connected from ``tct_gui``
        to ``MotorPanel.set_as_scan_start``, replacing the retired
        ``ScanPanel.set_start_position`` target (design doc gap G3: a plan
        has no single start position, only per-axis loops -- see the
        "Use current position" affordance above)."""
        self._motor_pos = (float(x_mm), float(y_mm), float(z_mm))
        self._lbl_motor_pos.setText(
            f"Motor @ x={x_mm:.3f}  y={y_mm:.3f}  z={z_mm:.3f} mm"
        )
        self._update_use_position_enabled()

    @Slot(float)
    def set_focus_z(self, z_mm: float) -> None:
        """Store the Scan Viewer's Z-focus best-Z result (no hardware I/O --
        this only receives a value already computed there). Connected from
        ``tct_gui`` to ``ScanViewerPanel.best_z_apply_requested`` (design doc
        gap G4). Staging only -- see the "Use focus Z" affordance above; the
        Planner tab is never auto-switched-to."""
        self._focus_z = float(z_mm)
        self._lbl_focus_z.setText(f"Focus Z: {self._focus_z:.3f} mm")
        self._update_use_position_enabled()
        notify("Focus Z staged in Planner", "info")

    def _rebuild_legend(self) -> None:
        while self._legend_row.count():
            taken = self._legend_row.takeAt(0)
            w = taken.widget()
            if w is not None:
                w.deleteLater()
        for axis_key, text in (
            ("bias", "Bias"), ("z", "Z"), ("x", "X"), ("y", "Y"),
            ("laser", "Laser"), ("delay", "Delay"), ("hazard", "Hazard"),
        ):
            color = axis_color(axis_key, self._theme_mode)
            pair = QWidget()
            pair_lay = QHBoxLayout(pair)
            pair_lay.setContentsMargins(0, 0, 0, 0)
            pair_lay.setSpacing(4)
            swatch = QLabel()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(f"background: {color}; border-radius: 3px;")
            label = QLabel(text)
            label.setObjectName("plannerLeafMeta")
            pair_lay.addWidget(swatch)
            pair_lay.addWidget(label)
            self._legend_row.addWidget(pair)
        self._legend_row.addStretch(1)

    # ------------------------------------------------------------------ #
    # Edit -> invalidate -> debounced re-estimate                          #
    # ------------------------------------------------------------------ #

    def _on_plan_edited(self) -> None:
        self._invalidate_run_state()
        self._debounce.start()

    def _on_debounced_edit(self) -> None:
        self._recompute_estimate()

    def _invalidate_run_state(self) -> None:
        """Any plan edit re-locks Start: a stale Dry Run / Arm must never
        carry over to a changed routine (per-run arm semantics)."""
        self._dry_run_ok = False
        self._btn_dry_run.setText("Dry Run")
        if self._hv_armed:
            self.set_hv_armed(False)
        else:
            self._chip_hv_status.set_status(
                "Plan changed — HV disarmed, Start locked", "warn"
            )
        self._update_start_enabled()

    def _after_structural_change(self) -> None:
        """Every structural mutation (drop/remove/duplicate/move/undo) goes
        through this SAME path: rebuild the tree from the (already-mutated)
        plan, then invalidate exactly like a numeric edit does — Start
        re-locks, a prior Arm is dropped, and the estimate is recomputed on
        the same debounce timer a spin-box edit uses."""
        self._rebuild_tree()
        self._on_plan_edited()

    # ------------------------------------------------------------------ #
    # Drag & drop — decode / validate / mutate                            #
    #                                                                      #
    # These are plain-Python methods (no Qt event objects) so tests can    #
    # exercise every drop rule directly: construct a QMimeData + call      #
    # _plan_drop_decision(mime, target_item_or_None, indicator_string).    #
    # ------------------------------------------------------------------ #

    def _decode_mime_payload(self, mime: QMimeData) -> dict | None:
        if mime is None or not mime.hasFormat(_MIME_TYPE):
            return None
        try:
            raw = bytes(mime.data(_MIME_TYPE)).decode("utf-8")
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _resolve_drop_location(
        self, target_path: list[int] | None, indicator: str,
    ) -> tuple[list[int] | None, int] | None:
        """``(dest_parent_path, dest_index)`` for dropping at *indicator*
        ("above"/"on"/"below"/"viewport") relative to *target_path*, or
        ``None`` if that location can never be a valid drop (an action leaf
        as an "into" target; nothing under the cursor with a non-viewport
        indicator)."""
        if target_path is None:
            if indicator == "viewport":
                return None, len(self._plan.root)
            return None
        block = _block_at_path(self._plan.root, target_path)
        if indicator == "on":
            if not isinstance(block, LoopBlock):
                return None   # actions are leaves — nothing drops "into" them
            return list(target_path), len(block.children)
        if indicator in ("above", "below"):
            parent_path, idx = _split_path(target_path)
            return parent_path, (idx if indicator == "above" else idx + 1)
        return None

    def _is_valid_move_target(
        self, source_path: list[int], dest_parent_path: list[int] | None,
    ) -> bool:
        """Reject dropping a node into itself or one of its own descendants."""
        if dest_parent_path is None:
            return True
        return list(dest_parent_path[: len(source_path)]) != list(source_path)

    def _plan_drop_decision(
        self, mime: QMimeData, target_item: QTreeWidgetItem | None, indicator: str,
    ) -> tuple[list[int] | None, int, dict] | None:
        """Return ``(dest_parent_path, dest_index, payload)`` if this drop is
        valid, else ``None``. The single source of truth for both the
        dragMoveEvent accept/reject highlight and the actual dropEvent
        mutation — and the primary entry point headless tests call directly."""
        payload = self._decode_mime_payload(mime)
        if payload is None:
            return None
        if target_item is not None and target_item.data(0, _ROLE_PATH) is None:
            return None   # decorative rows (and Preflight) are never a drop target
        target_path = target_item.data(0, _ROLE_PATH) if target_item is not None else None
        loc = self._resolve_drop_location(target_path, indicator)
        if loc is None:
            return None
        dest_parent_path, dest_index = loc
        op = payload.get("op")
        if op == "move":
            source_path = payload.get("path")
            if (not isinstance(source_path, list) or not source_path
                    or not all(isinstance(i, int) for i in source_path)):
                return None
            try:
                _block_at_path(self._plan.root, source_path)   # fail closed: bounds-check
            except (IndexError, AttributeError, TypeError, KeyError):
                return None
            if not self._is_valid_move_target(source_path, dest_parent_path):
                return None
        elif op == "new":
            block_dict = payload.get("block")
            if not isinstance(block_dict, dict):
                return None
            try:
                ScanBlock.from_dict(block_dict)   # fail closed: reject malformed blocks
            except (ValueError, KeyError, TypeError):
                return None
        else:
            return None
        return dest_parent_path, dest_index, payload

    @staticmethod
    def _move_block_on(
        root: list, source_path: list[int],
        dest_parent_path: list[int] | None, dest_index: int,
    ) -> None:
        """Remove the block at *source_path* from *root* and reinsert it at
        *dest_parent_path*/*dest_index*, correcting for the index shift when
        source and destination share the same parent list. Operates on any
        block-list root -- the live plan's (:meth:`_move_block`) or a
        throwaway candidate copy (:meth:`_compute_candidate_estimate`) --
        so the preview mutates a completely separate object graph."""
        src_parent_path, src_index = _split_path(source_path)
        src_list = _list_for_parent(root, src_parent_path)
        block = src_list.pop(src_index)
        dest_list = _list_for_parent(root, dest_parent_path)
        if dest_list is src_list and src_index < dest_index:
            dest_index -= 1
        dest_index = max(0, min(dest_index, len(dest_list)))
        dest_list.insert(dest_index, block)

    def _move_block(
        self, source_path: list[int],
        dest_parent_path: list[int] | None, dest_index: int,
    ) -> None:
        self._move_block_on(self._plan.root, source_path, dest_parent_path, dest_index)

    def _apply_drop(
        self, dest_parent_path: list[int] | None, dest_index: int, payload: dict,
    ) -> None:
        """Mutate the plan for an already-validated drop (from either the
        palette or a tree-internal move), then rebuild + invalidate."""
        self._push_undo()
        if payload.get("op") == "move":
            self._move_block(payload["path"], dest_parent_path, dest_index)
        else:
            block = ScanBlock.from_dict(payload["block"])
            dest_list = _list_for_parent(self._plan.root, dest_parent_path)
            dest_index = max(0, min(dest_index, len(dest_list)))
            dest_list.insert(dest_index, block)
        self._after_structural_change()

    # ------------------------------------------------------------------ #
    # Drag & drop — ghost + delta PREVIEW (dragMove only)                 #
    #                                                                      #
    # Builds on the exact same _plan_drop_decision() a real drop uses, so #
    # preview and actual drop can never disagree. Never mutates           #
    # self._plan, never touches the undo stack, never triggers a full     #
    # tree rebuild -- a single reusable ghost QTreeWidgetItem is          #
    # inserted/moved directly in the live tree, and the delta chip is     #
    # computed from a throwaway to_dict()/from_dict() plan copy.          #
    # ------------------------------------------------------------------ #

    def _preview_drag(
        self, mime: QMimeData, target_item: QTreeWidgetItem | None, indicator: str,
    ) -> tuple[list[int] | None, int, dict] | None:
        """Panel-side mirror of ``_RecipeTree.dragMoveEvent``'s decision +
        preview-update sequence: decide via :meth:`_plan_drop_decision`,
        then update the ghost/delta preview from that SAME decision. The
        primary entry point for headless tests (no real Qt drag event
        needed) and for ``dragMoveEvent`` itself."""
        decision = self._plan_drop_decision(mime, target_item, indicator)
        self._update_drag_preview(decision)
        return decision

    def _update_drag_preview(
        self, decision: tuple[list[int] | None, int, dict] | None,
    ) -> None:
        if decision is None:
            self._clear_drag_preview()
            return
        dest_parent_path, dest_index, payload = decision
        self._ghost_decision = decision
        key = (
            tuple(dest_parent_path) if dest_parent_path is not None else None,
            dest_index,
        )
        if key == self._ghost_key and self._ghost_item is not None:
            return   # same candidate slot as last hover -- throttle, no-op
        self._ghost_key = key
        self._place_ghost(dest_parent_path, dest_index, payload)
        self._schedule_delta_preview(dest_parent_path, dest_index, payload)

    def _clear_drag_preview(self) -> None:
        """Tear down BOTH preview artifacts. Called on drop (accepted or
        rejected), dragLeave, a fresh dragEnter, and ``shutdown()`` -- every
        exit path a drag gesture can take."""
        self._ghost_key = None
        self._ghost_decision = None
        self._remove_ghost_item()
        self._clear_delta_preview()

    # -- ghost row -----------------------------------------------------

    def _ghost_block_for_payload(self, payload: dict):
        """The block the ghost row should *look like*: a freshly parsed copy
        for a palette "new" drop, or the REAL (still plan-owned) block for a
        tree-internal "move" -- read-only rendering only, never wired to any
        edit signal, so referencing the live object cannot mutate it."""
        op = payload.get("op")
        try:
            if op == "new":
                return ScanBlock.from_dict(payload["block"])
            if op == "move":
                return _block_at_path(self._plan.root, payload["path"])
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            return None
        return None

    def _ghost_target(
        self, dest_parent_path: list[int] | None, dest_index: int,
    ) -> tuple[QTreeWidgetItem | None, int]:
        """``(parent_tree_item, child_index)`` for inserting the ghost at the
        tree position matching plan-index *dest_index* under
        *dest_parent_path* -- correcting for the decorative rows
        (Preflight at root; danger/guard/settle under a loop) that always
        sit ahead of a parent's real block children (see ``_add_block``)."""
        if dest_parent_path is None:
            return self._tree.invisibleRootItem(), dest_index + 1  # +1: Preflight
        try:
            parent_block = _block_at_path(self._plan.root, dest_parent_path)
        except (IndexError, AttributeError, TypeError, KeyError):
            return None, 0
        parent_item = self._item_for_block(parent_block)
        if parent_item is None:
            return None, 0
        prefix = 0
        for i in range(parent_item.childCount()):
            if parent_item.child(i).data(0, _ROLE_PATH) is None:
                prefix += 1
            else:
                break
        return parent_item, prefix + dest_index

    def _place_ghost(
        self, dest_parent_path: list[int] | None, dest_index: int, payload: dict,
    ) -> None:
        self._remove_ghost_item()
        block = self._ghost_block_for_payload(payload)
        if block is None:
            return
        parent_item, child_index = self._ghost_target(dest_parent_path, dest_index)
        if parent_item is None:
            return
        item = QTreeWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)   # never itself a drop target
        parent_item.insertChild(child_index, item)
        self._tree.setItemWidget(item, 0, self._make_ghost_row(block))
        item.setExpanded(True)
        self._ghost_item = item

    def _remove_ghost_item(self) -> None:
        if self._ghost_item is None:
            return
        item = self._ghost_item
        self._ghost_item = None
        self._tree.setItemWidget(item, 0, None)
        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
        else:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx >= 0:
                self._tree.takeTopLevelItem(idx)

    def _make_ghost_row(self, block) -> QWidget:
        """Read-only preview row: axis-coloured "LOOP <axis> <start> → <stop>"
        summary for a loop, the action's own glyph+label for an action leaf
        (for an internal move this reads the moved block's OWN live
        attributes -- see ``_ghost_block_for_payload``). Dashed translucent
        frame + a "will insert here" affordance mark it as not-yet-real."""
        if isinstance(block, LoopBlock):
            return self._make_ghost_loop_row(block)
        if isinstance(block, ActionBlock):
            return self._make_ghost_action_row(block)
        return self._make_leaf_frame("•", "block", "", frame_name="plannerGhostRow")

    def _make_ghost_loop_row(self, loop: LoopBlock) -> QFrame:
        axis_key = _axis_ui_key(loop.axis)
        color = axis_color(axis_key, self._theme_mode)
        unit = "V" if loop.axis == Axis.BIAS_V else "mm"
        if loop.values is not None:
            summary = f"{len(loop.values)} explicit values"
        else:
            start = loop.start if loop.start is not None else 0.0
            stop = loop.stop if loop.stop is not None else 0.0
            summary = f"{start:g} → {stop:g} {unit}"

        frame = QFrame()
        frame.setObjectName("plannerGhostRow")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        frame.setStyleSheet(
            f"#plannerGhostRow {{ border: 1px dashed {_rgba(color, 0.55)}; "
            f"border-left: 3px dashed {color}; background: {_rgba(color, 0.10)}; }}"
        )
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)
        tag = QLabel("LOOP")
        tag.setObjectName("plannerTag")
        tag.setStyleSheet(f"#plannerTag {{ color: {color}; background: {_rgba(color, 0.16)}; }}")
        lay.addWidget(tag)
        name = QLabel(f"{_AXIS_LABEL[loop.axis]}  {summary}")
        name.setObjectName("plannerGhostLabel")
        name.setStyleSheet(f"color: {color};")
        lay.addWidget(name)
        lay.addStretch(1)
        lay.addWidget(self._make_ghost_hint(color))
        return frame

    def _make_ghost_action_row(self, action: ActionBlock) -> QFrame:
        p = DARK if self._theme_mode == "dark" else LIGHT
        color = p["accent"]
        glyph, label = _ACTION_UI.get(action.action, ("•", action.action.value))
        return self._make_leaf_frame(
            glyph, label, self._leaf_meta_text(action),
            frame_name="plannerGhostRow", label_name="plannerGhostLabel",
            glyph_style=f"color: {color};", label_style=f"color: {color};",
            frame_style=(
                f"#plannerGhostRow {{ border: 1px dashed {_rgba(color, 0.55)}; "
                f"border-left: 3px dashed {color}; background: {_rgba(color, 0.10)}; }}"
            ),
            trailing=self._make_ghost_hint(color),
        )

    def _make_ghost_hint(self, color: str) -> QLabel:
        lbl = QLabel("↳ will insert here")
        lbl.setObjectName("plannerGhostHint")
        lbl.setStyleSheet(f"color: {color};")
        return lbl

    # -- delta preview ("Before you run" card) --------------------------

    def _schedule_delta_preview(
        self, dest_parent_path: list[int] | None, dest_index: int, payload: dict,
    ) -> None:
        self._pending_preview = (dest_parent_path, dest_index, payload)
        self._preview_debounce.start()

    def _on_preview_debounce_timeout(self) -> None:
        if self._pending_preview is None:
            return
        dest_parent_path, dest_index, payload = self._pending_preview
        estimate = self._compute_candidate_estimate(dest_parent_path, dest_index, payload)
        self._render_delta_preview(estimate)

    def _compute_candidate_estimate(
        self, dest_parent_path: list[int] | None, dest_index: int, payload: dict,
    ) -> PlanEstimate | None:
        """Build a throwaway candidate plan (``to_dict``/``from_dict`` copy +
        the would-be mutation) and estimate it. The real plan object and the
        undo stack are never touched -- this is a completely separate object
        graph from the very first line."""
        try:
            candidate = ScanPlan.from_dict(self._plan.to_dict())
            op = payload.get("op")
            if op == "move":
                self._move_block_on(candidate.root, payload["path"], dest_parent_path, dest_index)
            elif op == "new":
                block = ScanBlock.from_dict(payload["block"])
                dest_list = _list_for_parent(candidate.root, dest_parent_path)
                idx = max(0, min(dest_index, len(dest_list)))
                dest_list.insert(idx, block)
            else:
                return None
            return estimate_plan(candidate)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            return None

    def _render_delta_preview(self, candidate: PlanEstimate | None) -> None:
        if candidate is None:
            self._chip_delta_preview.setVisible(False)
            return
        base = self._safe_estimate()
        base_points = base.total_points if base is not None else 0
        base_runtime = base.est_runtime_s if base is not None else 0.0
        delta_runtime = candidate.est_runtime_s - base_runtime
        over_cap = candidate.total_leaf_visits > self._limits.max_points
        text = (
            f"Preview: {base_points:,} → {candidate.total_points:,} pts "
            f"· {_fmt_duration_delta(delta_runtime)}"
        )
        self._chip_delta_preview.set_status(text, "warn" if over_cap else "neutral")
        self._chip_delta_preview.setVisible(True)

    def _clear_delta_preview(self) -> None:
        self._pending_preview = None
        self._preview_debounce.stop()
        self._chip_delta_preview.setVisible(False)
        self._chip_delta_preview.set_status("", "neutral")

    # ------------------------------------------------------------------ #
    # Context menu — Remove / Duplicate / Move up / Move down             #
    # (the keyboard/accessibility alternative to drag)                    #
    # ------------------------------------------------------------------ #

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        path = item.data(0, _ROLE_PATH)
        if path is None:
            return   # decorative rows carry no context menu
        parent_path, idx = _split_path(path)
        siblings = _list_for_parent(self._plan.root, parent_path)

        menu = QMenu(self._tree)
        act_remove = menu.addAction("Remove")
        act_dup = menu.addAction("Duplicate")
        menu.addSeparator()
        act_up = menu.addAction("Move up")
        act_up.setEnabled(idx > 0)
        act_down = menu.addAction("Move down")
        act_down.setEnabled(idx < len(siblings) - 1)

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is act_remove:
            self._remove_block(path)
        elif chosen is act_dup:
            self._duplicate_block(path)
        elif chosen is act_up:
            self._reorder_block(path, -1)
        elif chosen is act_down:
            self._reorder_block(path, 1)

    def _remove_block(self, path: list[int]) -> None:
        self._push_undo()
        parent_path, idx = _split_path(path)
        _list_for_parent(self._plan.root, parent_path).pop(idx)
        self._after_structural_change()

    def _duplicate_block(self, path: list[int]) -> None:
        self._push_undo()
        parent_path, idx = _split_path(path)
        lst = _list_for_parent(self._plan.root, parent_path)
        clone = ScanBlock.from_dict(lst[idx].to_dict())
        lst.insert(idx + 1, clone)
        self._after_structural_change()

    def _reorder_block(self, path: list[int], delta: int) -> None:
        parent_path, idx = _split_path(path)
        lst = _list_for_parent(self._plan.root, parent_path)
        new_idx = idx + delta
        if not (0 <= new_idx < len(lst)):
            return
        self._push_undo()
        lst[idx], lst[new_idx] = lst[new_idx], lst[idx]
        self._after_structural_change()

    # ------------------------------------------------------------------ #
    # Undo — snapshot stack of plan.to_dict(), capped                     #
    # ------------------------------------------------------------------ #

    def _push_undo(self) -> None:
        self._undo_stack.append(self._plan.to_dict())
        if len(self._undo_stack) > _UNDO_CAP:
            self._undo_stack.pop(0)
        self._btn_undo.setEnabled(True)

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        snapshot = self._undo_stack.pop()
        self._plan = ScanPlan.from_dict(snapshot)
        self._btn_undo.setEnabled(bool(self._undo_stack))
        self._after_structural_change()

    def _recompute_estimate(self) -> None:
        key = self._estimate_key()
        if self._last_estimate_key == key and self._last_estimate is not None:
            self._render_estimate(self._last_estimate)
            return
        if self._estimate_should_run_async():
            self._queue_estimate(key)
            return
        estimate = self._safe_estimate()
        self._render_estimate(estimate)

    def _safe_estimate(self) -> PlanEstimate | None:
        key = self._estimate_key()
        if self._last_estimate_key == key:
            return self._last_estimate
        try:
            estimate = estimate_plan(self._plan)
        except (ValueError, TypeError):
            return None
        self._last_estimate = estimate
        self._last_estimate_key = key
        return estimate

    def _estimate_key(self) -> str:
        # Serialises the plan TREE (a handful of loop blocks), NOT the
        # materialised grid — cheap even for a million-point plan, so it stays
        # on the GUI thread.  Only the leaf walk in estimate_plan() is
        # expensive, and that is exactly what _queue_estimate ships off-thread.
        return json.dumps(self._plan.to_dict(), sort_keys=True, separators=(",", ":"))

    def _estimate_should_run_async(self) -> bool:
        try:
            return self._plan.total_leaf_visits() > self._estimate_async_threshold
        except (ValueError, TypeError):
            return False

    def _queue_estimate(self, key: str) -> None:
        """Ship the estimate for *key* to the worker, coalescing to latest.

        At most ONE job is ever in flight; a request that arrives while the
        worker is busy is stashed as the (single) pending request — a later
        edit overwrites it, so a burst of rapid edits can never queue
        unboundedly (latest wins)."""
        self._render_estimate_pending()
        self._estimate_seq += 1
        req = (self._estimate_seq, key, self._plan.to_dict())
        if self._estimate_inflight:
            self._estimate_pending = req
        else:
            self._submit_estimate_request(req)

    def _submit_estimate_request(self, req: tuple[int, str, dict]) -> None:
        seq, key, plan_dict = req
        self._estimate_inflight = True
        self._estimate_inflight_key = key
        # Cross-thread → Qt queues it; the worker computes and reports back on
        # this (GUI) thread via the queued ``done`` signal.
        self._submit_estimate.emit(seq, plan_dict)

    @Slot(int, object, str)
    def _on_estimate_done(self, seq: int, estimate: object, error: str) -> None:
        self._estimate_inflight = False
        # Generation guard: render only the newest request's result.  A seq
        # below the latest means a newer edit already superseded this one (its
        # plan is stale), so its late result must never clobber the fresher
        # pending estimate — the whole point of the monotonic seq.
        if seq == self._estimate_seq:
            key = self._estimate_inflight_key
            if error:
                self._last_estimate = None
                self._last_estimate_key = key
                self._render_estimate(None)
            else:
                est = estimate if isinstance(estimate, PlanEstimate) else None
                self._last_estimate = est
                self._last_estimate_key = key
                self._render_estimate(est)
        # Kick the coalesced latest-wins request that landed mid-flight.
        if self._estimate_pending is not None:
            req = self._estimate_pending
            self._estimate_pending = None
            self._submit_estimate_request(req)

    def _render_estimate_pending(self) -> None:
        self._chip_points.set_status("Estimating...", "busy")
        self._chip_runtime.set_status("...", "busy")
        self._chip_data.set_status("...", "busy")
        self._chip_travel.set_status("...", "busy")
        self._chip_hv.set_status("...", "busy")

    def _render_estimate(self, estimate: PlanEstimate | None) -> None:
        if estimate is None:
            for chip in (self._chip_points, self._chip_runtime, self._chip_data,
                         self._chip_travel, self._chip_hv):
                chip.set_status("—", "neutral")
            return
        over_cap = estimate.total_leaf_visits > self._limits.max_points
        self._chip_points.set_status(f"{estimate.total_points:,}", "crit" if over_cap else "good")
        self._chip_runtime.set_status(_fmt_duration(estimate.est_runtime_s), "neutral")
        over_data = estimate.est_data_bytes > 1536 * 1024 * 1024
        self._chip_data.set_status(_fmt_data(estimate.est_data_bytes), "warn" if over_data else "neutral")
        travel_total = sum(estimate.stage_travel_mm.values())
        self._chip_travel.set_status(_fmt_travel(travel_total), "neutral")
        lo, hi = estimate.hv_range_V
        no_bias = lo == 0.0 and hi == 0.0
        self._chip_hv.set_status(
            "0 V" if no_bias else f"{lo:g} … {hi:g} V",
            "neutral" if no_bias else "warn",
        )

    # ------------------------------------------------------------------ #
    # Validate / Dry Run / Arm / Start                                     #
    # ------------------------------------------------------------------ #

    def _on_validate_clicked(self) -> None:
        issues = validate_plan(self._plan, self._limits)
        self._render_issues(issues, kind="validate")

    def _on_dry_run_clicked(self) -> None:
        issues = validate_plan(self._plan, self._limits)
        self._render_issues(issues, kind="dryrun")
        self._dry_run_ok = not any(i.severity == "ERROR" for i in issues)
        self._btn_dry_run.setText("✓ Dry Run" if self._dry_run_ok else "Dry Run")
        self._recompute_estimate()
        self._update_start_enabled()

    def _on_arm_clicked(self) -> None:
        if self._hv_armed:
            return
        estimate = self._safe_estimate()
        lo, hi = estimate.hv_range_V if estimate is not None else (0.0, 0.0)
        text = (
            f"This authorizes the run to ramp bias to {hi:g} V / {lo:g} V.\n\n"
            "Nothing moves yet — the stage and HV energize only when you "
            "press Start, and every ramp still steps through the driver's "
            "software limits. Confirm you understand the hazard."
        )
        reply = QMessageBox.warning(
            self, "Arm high voltage", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.arm_hv_requested.emit()

    def _on_start_clicked(self) -> None:
        if not (self._hv_armed and self._dry_run_ok):
            return
        self.start_plan_requested.emit(self._plan)

    def _update_start_enabled(self) -> None:
        self._btn_start.setEnabled(
            (not self._running) and self._hv_armed and self._dry_run_ok
        )

    # ------------------------------------------------------------------ #
    # Issues list                                                          #
    # ------------------------------------------------------------------ #

    def _render_issues(self, issues: list[PlanIssue], *, kind: str) -> None:
        self._clear_issues_area()
        if not issues:
            text = {
                "validate": "Validation passed — limits, HV range, steps "
                             "and point budget OK.",
                "dryrun": "Dry run passed — walked the recipe without "
                          "hardware; limits, compliance and point budget OK.",
            }.get(kind, "OK.")
            self._add_issue_row(text, "good")
            return
        for issue in issues:
            state = "crit" if issue.severity == "ERROR" else "warn"
            self._add_issue_row(str(issue), state)

    def _add_issue_row(self, text: str, state: str) -> None:
        p = DARK if self._theme_mode == "dark" else LIGHT
        color = {"good": p["good"], "warn": p["warn"], "crit": p["crit"]}.get(state, p["muted"])
        label = QLabel(f"●  {text}")
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {color};")
        self._issues_layout.addWidget(label)
        self._issue_labels.append(label)

    def _clear_issues_area(self) -> None:
        for label in self._issue_labels:
            self._issues_layout.removeWidget(label)
            label.deleteLater()
        self._issue_labels.clear()

    # ------------------------------------------------------------------ #
    # Save / Load routine                                                  #
    # ------------------------------------------------------------------ #

    def _on_save_routine(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Scan Routine", "", "YAML (*.yaml *.yml)"
        )
        if not path:
            return
        try:
            self._plan.save_yaml(path)
            flash_button(self._btn_save_routine, "good", "Saved")
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _on_load_routine(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Scan Routine", "", "YAML (*.yaml *.yml)"
        )
        if not path:
            return
        try:
            plan = ScanPlan.load_yaml(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
            return
        self.set_plan(plan)
        flash_button(self._btn_load_routine, "good", "Loaded")

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def plan(self) -> ScanPlan:
        """Return the live plan object (mutated in place by tree edits)."""
        return self._plan

    def set_plan(self, plan: ScanPlan) -> None:
        """Replace the plan wholesale (e.g. after Load Routine) and re-lock
        Start until it is freshly dry-run + armed again."""
        self._plan = plan
        self._undo_stack.clear()
        self._btn_undo.setEnabled(False)
        self._rebuild_tree()
        self._invalidate_run_state()
        self._recompute_estimate()

    @Slot(bool)
    def set_hv_armed(self, armed: bool) -> None:
        """External truth for the HV-armed latch — call this from the
        controller's confirmation of ``arm_hv_requested``, never assume
        locally that a click succeeded."""
        self._hv_armed = bool(armed)
        if self._hv_armed:
            self._btn_arm.setText("✓ HV armed")
            self._btn_arm.setProperty("state", "good")
            self._chip_hv_status.set_status("HV armed — Start unlocked", "good")
        else:
            self._btn_arm.setText("⚡ Arm HV")
            self._btn_arm.setProperty("state", "")
            self._chip_hv_status.set_status("HV disarmed — Start is locked", "warn")
        repolish(self._btn_arm)
        self._update_start_enabled()

    @Slot(object)
    def set_limits(self, limits: PlanLimits) -> None:
        """Replace the pre-flight limits (e.g. once tct_gui reads the real
        devices.yaml software limits / HV range) and re-lock Start."""
        self._limits = limits
        self._invalidate_run_state()
        self._recompute_estimate()

    @Slot(bool)
    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        self._btn_validate.setEnabled(not running)
        self._btn_dry_run.setEnabled(not running)
        self._btn_arm.setEnabled(not running)
        self._btn_save_routine.setEnabled(not running)
        self._btn_load_routine.setEnabled(not running)
        self._tree.setEnabled(not running)
        self._btn_abort.setEnabled(running)
        self._update_use_position_enabled()
        if running:
            self._chip_hv_status.set_status("Running…", "busy")
        self._update_start_enabled()

    @Slot(int, int)
    def on_progress(self, done: int, total: int) -> None:
        state = "good" if total and done >= total else "busy"
        self._chip_points.set_status(f"{done}/{total} pts", state)

    @Slot()
    def on_finished(self) -> None:
        self.set_running(False)
        self._chip_hv_status.set_status("Run finished", "good")
        flash_button(self._btn_start, "good", "Done")
        self._recompute_estimate()

    @Slot(str)
    def on_error(self, message: str) -> None:
        self.set_running(False)
        self._add_issue_row(f"Run error: {message}", "crit")
        self._chip_hv_status.set_status("Run error — see issues below", "crit")

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve axis-rail colours after a light/dark theme switch (same
        pattern as ``MotorPanel.refresh_theme`` / ``BiasPanel.refresh_theme``).
        Structural colours (panel/border/muted/...) already repaint via the
        app-wide stylesheet reapplied by ``gui.style.apply_theme``; only the
        per-instance axis-rail colours baked in at row-construction time need
        an explicit rebuild."""
        if mode:
            self._theme_mode = str(mode)
        self._rebuild_tree()
        self._rebuild_legend()
        self._populate_palette()

    def shutdown(self) -> None:
        """Stop the debounce timers and the estimate worker before the panel is
        discarded (called from ``tct_gui._teardown_panels``, mirroring every
        other panel's ``shutdown()``). Also clears any in-flight drag
        ghost/delta preview so a panel torn down mid-drag never leaves a
        dangling tree-item reference or a stray pending timer callback.

        Bounded wait — a huge in-flight estimate is a CPU walk that ``quit()``
        cannot interrupt until it returns, so never wait unbounded on the GUI
        thread.  The worker thread is parented to QApplication and self-
        ``deleteLater``s on ``finished``, so an estimate still running when the
        3 s bound elapses finishes and cleans itself up rather than being
        destroyed as a child of this (soon-deleted) widget — the MotorPanel
        soft-reload crash class.  Idempotent."""
        self._debounce.stop()
        self._preview_debounce.stop()
        self._estimate_pending = None
        thread = self._estimate_thread
        self._estimate_thread = None
        self._estimate_worker = None
        if thread is not None:
            thread.quit()
            thread.wait(3000)
        self._clear_drag_preview()
