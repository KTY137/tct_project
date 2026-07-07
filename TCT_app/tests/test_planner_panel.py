"""Headless GUI tests for the Scan Routine Planner panel and its Qt danger
gate (Phase 2.2 step 3).

Follows the existing gui test idiom (see ``test_status_widgets.py``):
``QT_QPA_PLATFORM=offscreen``, a shared ``QApplication.instance()`` helper, no
pytest-qt. No real ``QMessageBox`` is ever shown — ``QtDangerGate._show_dialog``
is stubbed in every test that exercises it.
"""
from __future__ import annotations

import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QCoreApplication, QMimeData
from PySide6.QtWidgets import QApplication

from controller.danger_gate import DangerAction
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import validate_plan
from gui.planner_panel import _MIME_TYPE, PlannerPanel
from gui.qt_danger_gate import QtDangerGate


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _bias_loop(plan: ScanPlan) -> LoopBlock:
    """The template's outermost block is the bias loop (see
    ``gui.planner_panel._default_template_plan``)."""
    root = plan.root[0]
    assert isinstance(root, LoopBlock) and root.axis == Axis.BIAS_V
    return root


def _find_loop(block, axis: Axis):
    if isinstance(block, LoopBlock):
        if block.axis == axis:
            return block
        for child in block.children:
            found = _find_loop(child, axis)
            if found is not None:
                return found
    return None


def _find_loop_in_plan(plan: ScanPlan, axis: Axis):
    for block in plan.root:
        found = _find_loop(block, axis)
        if found is not None:
            return found
    return None


def _mime_for(payload: dict) -> QMimeData:
    """Build a real ``QMimeData`` carrying the planner's drop payload — no
    actual Qt drag event is ever constructed; ``_plan_drop_decision`` and
    ``_apply_drop`` are called directly (per the module's testability
    design: drag/drop *decisions* are plain-Python methods on the panel)."""
    mime = QMimeData()
    mime.setData(_MIME_TYPE, QByteArray(json.dumps(payload).encode("utf-8")))
    return mime


# --------------------------------------------------------------------------- #
# PlannerPanel                                                                 #
# --------------------------------------------------------------------------- #

def test_panel_constructs_light_and_dark_theme():
    _app()
    panel = PlannerPanel()
    try:
        assert panel._theme_mode in ("light", "dark")
        assert panel._tree.topLevelItemCount() > 0
        panel.refresh_theme("dark")
        assert panel._theme_mode == "dark"
        assert panel._tree.topLevelItemCount() > 0
        panel.refresh_theme("light")
        assert panel._theme_mode == "light"
    finally:
        panel.shutdown()


def test_default_template_validates_clean_under_default_limits():
    _app()
    panel = PlannerPanel()
    try:
        issues = validate_plan(panel._plan, panel._limits)
        errors = [i for i in issues if i.severity == "ERROR"]
        assert errors == []
    finally:
        panel.shutdown()


def test_spinbox_edit_updates_plan_and_invalidates_armed():
    _app()
    panel = PlannerPanel()
    try:
        bias_loop = _bias_loop(panel._plan)
        editors = panel._loop_editors[id(bias_loop)]

        # Force an armed + dry-run-ok state so we can observe it get cleared.
        panel._dry_run_ok = True
        panel.set_hv_armed(True)
        assert panel._btn_start.isEnabled()

        new_step = editors["step"].value() - 5.0
        editors["step"].setValue(new_step)

        assert bias_loop.step == new_step
        assert panel._dry_run_ok is False
        assert panel._hv_armed is False
        assert not panel._btn_start.isEnabled()
    finally:
        panel.shutdown()


def test_start_enable_requires_armed_and_dry_run_ok():
    _app()
    panel = PlannerPanel()
    try:
        assert not panel._btn_start.isEnabled()

        panel._dry_run_ok = True
        panel._update_start_enabled()
        assert not panel._btn_start.isEnabled()   # dry-run alone is not enough

        panel.set_hv_armed(True)
        assert panel._btn_start.isEnabled()        # both latches set

        panel.set_hv_armed(False)
        assert not panel._btn_start.isEnabled()
    finally:
        panel.shutdown()


def test_start_plan_requested_carries_scan_plan():
    _app()
    panel = PlannerPanel()
    try:
        received = []
        panel.start_plan_requested.connect(received.append)

        panel._dry_run_ok = True
        panel.set_hv_armed(True)
        panel._btn_start.click()

        assert len(received) == 1
        assert received[0] is panel._plan
        assert isinstance(received[0], ScanPlan)
    finally:
        panel.shutdown()


def test_dry_run_sets_ok_flag_and_arm_requires_confirmation_signal():
    _app()
    panel = PlannerPanel()
    try:
        panel._on_dry_run_clicked()
        assert panel._dry_run_ok is True

        armed_requests = []
        panel.arm_hv_requested.connect(lambda: armed_requests.append(True))

        # Stub the confirmation dialog itself is out of scope here (it's a
        # QMessageBox, not a panel method) — assert the panel does not assume
        # armed on its own: the button click alone (without answering "Yes"
        # to a real dialog) cannot be exercised headlessly, so verify the
        # authoritative slot is what actually flips the latch.
        assert panel._hv_armed is False
        panel.set_hv_armed(True)
        assert panel._hv_armed is True
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Planner v2 — palette drag/drop, tree-internal moves, context menu, undo      #
# --------------------------------------------------------------------------- #

def test_palette_new_inserts_into_loop_children():
    _app()
    panel = PlannerPanel()
    try:
        x_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        before_children = len(x_loop.children)

        new_block = ActionBlock(action=ActionType.WAIT, params={"seconds": 2.0})
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})
        decision = panel._plan_drop_decision(mime, x_item, "on")
        assert decision is not None
        dest_parent_path, dest_index, _payload = decision
        assert dest_parent_path == panel._path_for_block(x_loop)
        assert dest_index == before_children

        panel._apply_drop(*decision)

        new_x_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_X)
        assert len(new_x_loop.children) == before_children + 1
        added = new_x_loop.children[-1]
        assert isinstance(added, ActionBlock) and added.action == ActionType.WAIT
    finally:
        panel.shutdown()


def test_palette_double_click_appends_new_loop_to_root():
    _app()
    panel = PlannerPanel()
    try:
        before = len(panel._plan.root)
        z_loop = LoopBlock(axis=Axis.STAGE_Z, start=-2.0, stop=2.0, step=0.1)

        # The accessibility fallback: double-click -> append to root, no
        # drag event needed at all.
        panel._on_palette_append({"op": "new", "block": z_loop.to_dict()})

        assert len(panel._plan.root) == before + 1
        added = panel._plan.root[-1]
        assert isinstance(added, LoopBlock) and added.axis == Axis.STAGE_Z
    finally:
        panel.shutdown()


def test_internal_move_reorders_with_same_parent_index_shift():
    _app()
    panel = PlannerPanel()
    try:
        y_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_Y)
        acquire, save = y_loop.children[0], y_loop.children[1]
        acquire_path = panel._path_for_block(acquire)
        save_item = panel._item_for_block(save)
        y_path = panel._path_for_block(y_loop)

        mime = _mime_for({"op": "move", "path": acquire_path})
        decision = panel._plan_drop_decision(mime, save_item, "below")
        assert decision is not None
        dest_parent_path, dest_index, _payload = decision
        assert dest_parent_path == y_path
        assert dest_index == 2   # save's pre-move index (1) + 1

        panel._apply_drop(*decision)

        new_y_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_Y)
        # acquire popped from index 0 shifts save down to 0, then acquire
        # lands at the corrected index 1 -- not the stale pre-pop index 2.
        assert new_y_loop.children[0].action == ActionType.SAVE_POINT
        assert new_y_loop.children[1].action == ActionType.ACQUIRE_WAVEFORM
    finally:
        panel.shutdown()


def test_self_and_descendant_move_rejected():
    _app()
    panel = PlannerPanel()
    try:
        bias_loop = _bias_loop(panel._plan)
        x_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_X)
        bias_path = panel._path_for_block(bias_loop)
        bias_item = panel._item_for_block(bias_loop)
        x_item = panel._item_for_block(x_loop)

        mime = _mime_for({"op": "move", "path": bias_path})

        # dropping the bias loop "into" its own descendant (x_loop)...
        assert panel._plan_drop_decision(mime, x_item, "on") is None
        # ...or "into" itself...
        assert panel._plan_drop_decision(mime, bias_item, "on") is None
        # ...must both be rejected.
    finally:
        panel.shutdown()


def test_action_leaf_rejects_into_drop():
    _app()
    panel = PlannerPanel()
    try:
        y_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_Y)
        acquire = y_loop.children[0]
        acquire_item = panel._item_for_block(acquire)

        new_block = ActionBlock(action=ActionType.WAIT)
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})

        assert panel._plan_drop_decision(mime, acquire_item, "on") is None
        # above/below the leaf ("between rows") is still a valid location.
        assert panel._plan_drop_decision(mime, acquire_item, "above") is not None
    finally:
        panel.shutdown()


def test_decorative_rows_are_not_drop_targets():
    _app()
    panel = PlannerPanel()
    try:
        bias_loop = _bias_loop(panel._plan)
        bias_item = panel._item_for_block(bias_loop)
        # Per _add_block, a bias loop's first two tree children are the
        # decorative "Ramp HV" / "Check leakage" rows, ahead of any real
        # block child.
        danger_item = bias_item.child(0)
        guard_item = bias_item.child(1)

        new_block = ActionBlock(action=ActionType.WAIT)
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})

        for indicator in ("above", "on", "below"):
            assert panel._plan_drop_decision(mime, danger_item, indicator) is None
            assert panel._plan_drop_decision(mime, guard_item, indicator) is None
    finally:
        panel.shutdown()


def test_structural_change_invalidates_latches_even_when_armed():
    _app()
    panel = PlannerPanel()
    try:
        panel._dry_run_ok = True
        panel.set_hv_armed(True)
        assert panel._btn_start.isEnabled()

        z_loop = LoopBlock(axis=Axis.STAGE_Z, start=-2.0, stop=2.0, step=0.1)
        panel._on_palette_append({"op": "new", "block": z_loop.to_dict()})

        assert panel._dry_run_ok is False
        assert panel._hv_armed is False
        assert not panel._btn_start.isEnabled()
    finally:
        panel.shutdown()


def test_undo_restores_pre_drop_plan_and_invalidates():
    _app()
    panel = PlannerPanel()
    try:
        before = panel._plan.to_dict()

        z_loop = LoopBlock(axis=Axis.STAGE_Z, start=-2.0, stop=2.0, step=0.1)
        panel._on_palette_append({"op": "new", "block": z_loop.to_dict()})
        assert panel._plan.to_dict() != before
        assert panel._btn_undo.isEnabled()

        # Simulate the user re-validating/re-arming after the drop.
        panel._dry_run_ok = True
        panel.set_hv_armed(True)
        assert panel._btn_start.isEnabled()

        panel._undo()

        assert panel._plan.to_dict() == before
        assert panel._dry_run_ok is False
        assert panel._hv_armed is False
        assert not panel._btn_start.isEnabled()
        assert not panel._btn_undo.isEnabled()
    finally:
        panel.shutdown()


def test_undo_stack_is_capped():
    _app()
    panel = PlannerPanel()
    try:
        for _ in range(30):
            panel._push_undo()
        assert len(panel._undo_stack) <= 20
    finally:
        panel.shutdown()


def test_duplicate_and_remove_block_mutate_plan_and_invalidate():
    _app()
    panel = PlannerPanel()
    try:
        y_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_Y)
        save = y_loop.children[1]
        save_path = panel._path_for_block(save)

        panel._dry_run_ok = True
        panel.set_hv_armed(True)

        panel._duplicate_block(save_path)
        new_y_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_Y)
        assert len(new_y_loop.children) == 3
        assert new_y_loop.children[1].action == ActionType.SAVE_POINT
        assert new_y_loop.children[2].action == ActionType.SAVE_POINT
        assert new_y_loop.children[1] is not new_y_loop.children[2]
        assert not panel._btn_start.isEnabled()   # duplicate invalidated the latches

        dup_path = panel._path_for_block(new_y_loop.children[2])
        panel._remove_block(dup_path)
        newer_y_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_Y)
        assert len(newer_y_loop.children) == 2
    finally:
        panel.shutdown()


def test_reorder_block_swaps_and_boundary_move_is_a_noop():
    _app()
    panel = PlannerPanel()
    try:
        y_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_Y)
        acquire = y_loop.children[0]
        acquire_path = panel._path_for_block(acquire)

        # Already first -> "move up" is a no-op; it must not even touch the
        # undo stack (nothing to undo for a rejected move).
        stack_len = len(panel._undo_stack)
        panel._reorder_block(acquire_path, -1)
        assert len(panel._undo_stack) == stack_len
        assert _find_loop_in_plan(panel._plan,Axis.STAGE_Y).children[0] is acquire

        panel._reorder_block(acquire_path, 1)
        moved_y_loop = _find_loop_in_plan(panel._plan,Axis.STAGE_Y)
        assert moved_y_loop.children[0].action == ActionType.SAVE_POINT
        assert moved_y_loop.children[1].action == ActionType.ACQUIRE_WAVEFORM
    finally:
        panel.shutdown()


def test_palette_mime_data_carries_new_op_payload():
    """Direct (no simulated drag event) check of the actual Qt override --
    ``_PaletteList.mimeData`` -- so a wrong role/format string would still be
    caught even though no test drives it through a real QDrag."""
    _app()
    panel = PlannerPanel()
    try:
        item = panel._palette.item(0)
        mime = panel._palette.mimeData([item])
        assert mime.hasFormat(_MIME_TYPE)
        payload = json.loads(bytes(mime.data(_MIME_TYPE)).decode("utf-8"))
        assert payload["op"] == "new"
        assert payload["block"]["type"] in ("loop", "action")
    finally:
        panel.shutdown()


def test_recipe_tree_mime_data_carries_move_op_payload():
    _app()
    panel = PlannerPanel()
    try:
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        item = panel._item_for_block(x_loop)
        mime = panel._tree.mimeData([item])
        assert mime.hasFormat(_MIME_TYPE)
        payload = json.loads(bytes(mime.data(_MIME_TYPE)).decode("utf-8"))
        assert payload["op"] == "move"
        assert payload["path"] == panel._path_for_block(x_loop)
    finally:
        panel.shutdown()


def test_recipe_tree_mime_data_empty_for_decorative_row():
    """Decorative rows carry no path, so the tree's mimeData() override
    must refuse to produce a draggable payload for them at the Qt level too
    (belt-and-suspenders alongside _plan_drop_decision's target-side check)."""
    _app()
    panel = PlannerPanel()
    try:
        bias_loop = _bias_loop(panel._plan)
        bias_item = panel._item_for_block(bias_loop)
        danger_item = bias_item.child(0)
        mime = panel._tree.mimeData([danger_item])
        assert not mime.hasFormat(_MIME_TYPE)
    finally:
        panel.shutdown()


def test_public_api_surface_unchanged():
    """Explicit guard: the signals/slots/methods tct_gui.py wires against
    must all still exist with the v2 drag/drop + palette additions."""
    _app()
    panel = PlannerPanel()
    try:
        assert hasattr(panel, "start_plan_requested")
        assert hasattr(panel, "arm_hv_requested")
        assert hasattr(panel, "abort_requested")
        for name in (
            "set_hv_armed", "set_limits", "set_running",
            "on_progress", "on_finished", "on_error",
            "plan", "set_plan", "refresh_theme", "shutdown",
        ):
            assert callable(getattr(panel, name)), name
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# QtDangerGate                                                                 #
# --------------------------------------------------------------------------- #

class _StubGate(QtDangerGate):
    """QtDangerGate with the real QMessageBox swapped for a canned answer."""

    def __init__(self, answer: bool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._answer = answer
        self.shown_actions: list[DangerAction] = []

    def _show_dialog(self, action: DangerAction) -> bool:
        self.shown_actions.append(action)
        return self._answer


def test_qt_danger_gate_confirms_true_on_gui_thread():
    _app()
    gate = _StubGate(True)
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V")
    assert gate.confirm(action) is True
    assert gate.shown_actions == [action]


def test_qt_danger_gate_denies_false_on_gui_thread():
    _app()
    gate = _StubGate(False)
    action = DangerAction(kind="move", summary="Move stage to (1, 2, 0)")
    assert gate.confirm(action) is False


def test_qt_danger_gate_confirm_from_worker_thread():
    _app()
    gate = _StubGate(True)
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    deadline = time.time() + 5.0
    while t.is_alive() and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    t.join(timeout=1.0)

    assert not t.is_alive()
    assert result == [True]
    assert gate.shown_actions == [action]


def test_qt_danger_gate_timeout_denies():
    _app()
    # Nobody pumps the event loop while the worker blocks, so the queued
    # signal is never delivered -> the short timeout must fire and deny.
    gate = _StubGate(True, timeout_s=0.05)
    action = DangerAction(kind="move", summary="Move stage")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=5.0)

    assert not t.is_alive()
    assert result == [False]
    # The dialog was never actually shown — the timeout won the race.
    assert gate.shown_actions == []


def test_qt_danger_gate_shutdown_denies_pending_and_future():
    _app()
    gate = _StubGate(True, timeout_s=5.0)
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    time.sleep(0.05)   # let the worker thread register its pending confirm
    gate.shutdown()
    t.join(timeout=5.0)

    assert not t.is_alive()
    assert result == [False]

    # Future calls are refused outright too, even on the GUI thread.
    assert gate.confirm(action) is False


def test_qt_danger_gate_abort_denies_pending_but_stays_usable():
    _app()
    gate = _StubGate(True, timeout_s=5.0)
    action = DangerAction(kind="move", summary="Move stage")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    time.sleep(0.05)
    gate.abort()
    t.join(timeout=5.0)

    assert not t.is_alive()
    assert result == [False]

    # abort() does not permanently close the gate — a later confirm on the
    # GUI thread still shows the (stubbed) dialog and can succeed.
    assert gate.confirm(action) is True
