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

import pytest
from PySide6.QtCore import QByteArray, QCoreApplication, QMimeData
from PySide6.QtWidgets import QApplication, QLabel

from controller.danger_gate import DangerAction
from controller.plan_estimate import estimate_plan
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan, ScanBlock
from controller.scan_plan_validator import PlanLimits, validate_plan
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


def _count_ghost_rows(panel: PlannerPanel) -> int:
    """Walk the whole tree and count rows whose item widget is the
    ``plannerGhostRow`` preview frame — used to prove a candidate change
    cleans up the old ghost slot instead of leaving a stray duplicate."""
    count = 0

    def walk(item) -> None:
        nonlocal count
        widget = panel._tree.itemWidget(item, 0)
        if widget is not None and widget.objectName() == "plannerGhostRow":
            count += 1
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(panel._tree.topLevelItemCount()):
        walk(panel._tree.topLevelItem(i))
    return count


def _ghost_labels(panel: PlannerPanel) -> list[str]:
    """Text of every ``QLabel`` inside the current ghost row's widget, for
    asserting the ghost renders the expected block summary."""
    assert panel._ghost_item is not None
    widget = panel._tree.itemWidget(panel._ghost_item, 0)
    assert widget is not None
    return [lbl.text() for lbl in widget.findChildren(QLabel)]


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
            "set_position_from_motor", "set_focus_z",
        ):
            assert callable(getattr(panel, name)), name
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Motor position -> loop start ("Use current position")                        #
#                                                                                #
# set_position_from_motor is the slot MotorPanel.set_as_scan_start(float,      #
# float, float) is wired to (in tct_gui, not tested here) in place of the      #
# retired ScanPanel.set_start_position — a plan has no single "start           #
# position", only per-axis loops, so the affordance writes into whichever      #
# X/Y/Z loop row is currently selected in the recipe tree.                     #
# --------------------------------------------------------------------------- #

def test_set_position_from_motor_stores_value_and_updates_label():
    _app()
    panel = PlannerPanel()
    try:
        assert panel._motor_pos is None
        assert not panel._btn_use_motor_pos.isEnabled()

        panel.set_position_from_motor(1.25, -2.5, 0.125)

        assert panel._motor_pos == (1.25, -2.5, 0.125)
        text = panel._lbl_motor_pos.text()
        assert "1.250" in text
        assert "-2.500" in text
        assert "0.125" in text
    finally:
        panel.shutdown()


def test_use_current_position_writes_x_loop_start_and_invalidates_latches():
    _app()
    panel = PlannerPanel()
    try:
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)

        panel.set_position_from_motor(3.5, -1.0, 0.0)
        panel._tree.setCurrentItem(x_item)
        assert panel._btn_use_motor_pos.isEnabled()

        # Force an armed + dry-run-ok state so we can observe it get
        # cleared, same as the plain spinbox-edit invalidation test.
        panel._dry_run_ok = True
        panel.set_hv_armed(True)
        assert panel._btn_start.isEnabled()

        panel._btn_use_motor_pos.click()

        assert x_loop.start == 3.5
        assert panel._dry_run_ok is False
        assert panel._hv_armed is False
        assert not panel._btn_start.isEnabled()
    finally:
        panel.shutdown()


def test_use_current_position_writes_z_loop_start():
    _app()
    panel = PlannerPanel()
    try:
        z_loop = LoopBlock(axis=Axis.STAGE_Z, start=-2.0, stop=2.0, step=0.1)
        panel._on_palette_append({"op": "new", "block": z_loop.to_dict()})
        new_z_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Z)
        z_item = panel._item_for_block(new_z_loop)

        panel.set_position_from_motor(1.0, 2.0, -4.75)
        panel._tree.setCurrentItem(z_item)
        assert panel._btn_use_motor_pos.isEnabled()

        panel._btn_use_motor_pos.click()

        assert new_z_loop.start == -4.75
    finally:
        panel.shutdown()


def test_use_current_position_disabled_before_position_and_for_non_axis_loop():
    _app()
    panel = PlannerPanel()
    try:
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        panel._tree.setCurrentItem(x_item)

        # A valid axis-loop selection alone is not enough -- no position
        # has arrived yet.
        assert panel._motor_pos is None
        assert not panel._btn_use_motor_pos.isEnabled()

        panel.set_position_from_motor(1.0, 2.0, 3.0)
        assert panel._btn_use_motor_pos.isEnabled()

        # Bias loop selected -> not an X/Y/Z axis loop -> disabled even
        # though a position has already arrived.
        bias_loop = _bias_loop(panel._plan)
        bias_item = panel._item_for_block(bias_loop)
        panel._tree.setCurrentItem(bias_item)
        assert not panel._btn_use_motor_pos.isEnabled()

        # An action leaf (not a loop at all) -> disabled too.
        y_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Y)
        acquire_item = panel._item_for_block(y_loop.children[0])
        panel._tree.setCurrentItem(acquire_item)
        assert not panel._btn_use_motor_pos.isEnabled()

        # Reselecting the X loop re-enables it.
        panel._tree.setCurrentItem(x_item)
        assert panel._btn_use_motor_pos.isEnabled()
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Z-focus -> loop start ("Use focus Z", G4)                                    #
#                                                                                #
# set_focus_z is the slot ScanViewerPanel.best_z_apply_requested(float) is     #
# wired to (in tct_gui, not tested here) — the "apply to planner Z" action    #
# ratified in docs/design/cockpit_style_overhaul.md. Mirrors                  #
# set_position_from_motor exactly, but the affordance only ever targets the   #
# stage-Z loop (a Z-focus result has no X/Y meaning).                         #
# --------------------------------------------------------------------------- #

def test_set_focus_z_stores_value_and_updates_label():
    _app()
    panel = PlannerPanel()
    try:
        assert panel._focus_z is None
        assert not panel._btn_use_focus_z.isEnabled()
        assert panel._lbl_focus_z.text() == "Focus Z: --"

        panel.set_focus_z(1.234)

        assert panel._focus_z == pytest.approx(1.234)
        assert "1.234" in panel._lbl_focus_z.text()
    finally:
        panel.shutdown()


def test_use_focus_z_writes_z_loop_start_and_invalidates_latches():
    _app()
    panel = PlannerPanel()
    try:
        z_loop = LoopBlock(axis=Axis.STAGE_Z, start=-2.0, stop=2.0, step=0.1)
        panel._on_palette_append({"op": "new", "block": z_loop.to_dict()})
        new_z_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Z)
        z_item = panel._item_for_block(new_z_loop)

        panel.set_focus_z(0.417)
        panel._tree.setCurrentItem(z_item)
        assert panel._btn_use_focus_z.isEnabled()

        # Force an armed + dry-run-ok state so we can observe it get
        # cleared, same as the plain spinbox-edit invalidation test.
        panel._dry_run_ok = True
        panel.set_hv_armed(True)
        assert panel._btn_start.isEnabled()

        panel._btn_use_focus_z.click()

        assert new_z_loop.start == pytest.approx(0.417)
        assert panel._dry_run_ok is False
        assert panel._hv_armed is False
        assert not panel._btn_start.isEnabled()
    finally:
        panel.shutdown()


def test_use_focus_z_disabled_for_x_and_y_loops():
    _app()
    panel = PlannerPanel()
    try:
        panel.set_focus_z(0.5)

        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        panel._tree.setCurrentItem(x_item)
        assert not panel._btn_use_focus_z.isEnabled()

        y_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Y)
        y_item = panel._item_for_block(y_loop)
        panel._tree.setCurrentItem(y_item)
        assert not panel._btn_use_focus_z.isEnabled()

        bias_loop = _bias_loop(panel._plan)
        bias_item = panel._item_for_block(bias_loop)
        panel._tree.setCurrentItem(bias_item)
        assert not panel._btn_use_focus_z.isEnabled()
    finally:
        panel.shutdown()


def test_use_focus_z_disabled_before_result_and_while_running():
    _app()
    panel = PlannerPanel()
    try:
        z_loop = LoopBlock(axis=Axis.STAGE_Z, start=-2.0, stop=2.0, step=0.1)
        panel._on_palette_append({"op": "new", "block": z_loop.to_dict()})
        new_z_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Z)
        z_item = panel._item_for_block(new_z_loop)
        panel._tree.setCurrentItem(z_item)

        # A valid Z-loop selection alone is not enough -- no focus result yet.
        assert panel._focus_z is None
        assert not panel._btn_use_focus_z.isEnabled()

        panel.set_focus_z(0.5)
        assert panel._btn_use_focus_z.isEnabled()

        # A run in progress locks the affordance out, same as the motor-
        # position button (the tree itself is disabled while running).
        panel.set_running(True)
        assert not panel._btn_use_focus_z.isEnabled()

        panel.set_running(False)
        assert panel._btn_use_focus_z.isEnabled()
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Planner v2 — drop ghost/delta PREVIEW (dragMoveEvent)                        #
# --------------------------------------------------------------------------- #

def test_drag_preview_ghost_appears_for_palette_new_at_correct_index():
    _app()
    panel = PlannerPanel()
    try:
        before_plan = panel._plan.to_dict()
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        before_children = len(x_loop.children)   # just [y_loop] -> no decorative rows

        new_block = ActionBlock(action=ActionType.WAIT, params={"seconds": 2.0})
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})
        decision = panel._preview_drag(mime, x_item, "on")
        assert decision is not None

        assert panel._ghost_item is not None
        assert x_item.indexOfChild(panel._ghost_item) == before_children
        labels = _ghost_labels(panel)
        assert any("Wait" in t for t in labels)
        assert any("2.0 s" in t for t in labels)

        # A preview NEVER mutates the real plan or the undo stack.
        assert panel._plan.to_dict() == before_plan
        assert panel._undo_stack == []
    finally:
        panel.shutdown()


def test_drag_preview_ghost_appears_for_internal_move_at_correct_index():
    _app()
    panel = PlannerPanel()
    try:
        before_plan = panel._plan.to_dict()
        y_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Y)
        acquire, save = y_loop.children[0], y_loop.children[1]
        acquire_path = panel._path_for_block(acquire)
        save_item = panel._item_for_block(save)
        y_item = panel._item_for_block(y_loop)

        mime = _mime_for({"op": "move", "path": acquire_path})
        decision = panel._preview_drag(mime, save_item, "below")
        assert decision is not None

        # y_loop's tree children are [move, settle, acquire, save] (2
        # decorative rows ahead of the 2 real ones) -- "below save" is
        # plan-index 2, so the ghost lands at tree-child-index 2 + 2 = 4.
        assert panel._ghost_item is not None
        assert y_item.indexOfChild(panel._ghost_item) == 4

        # An internal-move ghost renders the MOVED block's own live summary.
        labels = _ghost_labels(panel)
        assert any("Acquire waveform" in t for t in labels)
        assert any("64 avg" in t for t in labels)

        assert panel._plan.to_dict() == before_plan
        assert panel._undo_stack == []
    finally:
        panel.shutdown()


def test_drag_preview_ghost_for_new_loop_at_root_after_preflight_offset():
    _app()
    panel = PlannerPanel()
    try:
        z_loop = LoopBlock(axis=Axis.STAGE_Z, start=-2.0, stop=2.0, step=0.1)
        mime = _mime_for({"op": "new", "block": z_loop.to_dict()})
        decision = panel._preview_drag(mime, None, "viewport")
        assert decision is not None

        # topLevelItem(0) is the decorative Preflight row; root has one real
        # block (the bias loop) -> append lands at top-level index 2.
        assert panel._ghost_item is not None
        assert panel._tree.indexOfTopLevelItem(panel._ghost_item) == 2
        labels = _ghost_labels(panel)
        assert any("stage z" in t for t in labels)
        assert any("-2" in t and "2" in t for t in labels)
    finally:
        panel.shutdown()


def test_drag_preview_ghost_absent_for_self_and_descendant_move():
    _app()
    panel = PlannerPanel()
    try:
        bias_loop = _bias_loop(panel._plan)
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        bias_path = panel._path_for_block(bias_loop)
        bias_item = panel._item_for_block(bias_loop)
        x_item = panel._item_for_block(x_loop)
        mime = _mime_for({"op": "move", "path": bias_path})

        assert panel._preview_drag(mime, x_item, "on") is None
        assert panel._ghost_item is None
        assert not panel._chip_delta_preview.isVisibleTo(panel)

        assert panel._preview_drag(mime, bias_item, "on") is None
        assert panel._ghost_item is None
    finally:
        panel.shutdown()


def test_drag_preview_ghost_absent_for_leaf_into_target():
    _app()
    panel = PlannerPanel()
    try:
        y_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Y)
        acquire_item = panel._item_for_block(y_loop.children[0])
        new_block = ActionBlock(action=ActionType.WAIT)
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})

        assert panel._preview_drag(mime, acquire_item, "on") is None
        assert panel._ghost_item is None

        # "above" the same leaf is a valid location -- ghost DOES appear.
        assert panel._preview_drag(mime, acquire_item, "above") is not None
        assert panel._ghost_item is not None
    finally:
        panel.shutdown()


def test_drag_preview_candidate_change_moves_ghost_without_duplicate():
    _app()
    panel = PlannerPanel()
    try:
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        y_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Y)
        x_item = panel._item_for_block(x_loop)
        y_item = panel._item_for_block(y_loop)

        new_block = ActionBlock(action=ActionType.WAIT)
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})

        panel._preview_drag(mime, x_item, "on")
        first_ghost = panel._ghost_item
        assert first_ghost is not None
        assert _count_ghost_rows(panel) == 1

        panel._preview_drag(mime, y_item, "on")
        second_ghost = panel._ghost_item
        assert second_ghost is not None
        assert second_ghost is not first_ghost
        assert _count_ghost_rows(panel) == 1   # stale slot cleaned up, no dupe
    finally:
        panel.shutdown()


def test_drag_preview_same_candidate_slot_does_not_recreate_ghost():
    """Throttle: re-hovering the SAME (parent-path, index) candidate must not
    tear down and rebuild the ghost item (that's the per-pixel-flicker case
    the brief calls out)."""
    _app()
    panel = PlannerPanel()
    try:
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        new_block = ActionBlock(action=ActionType.WAIT)
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})

        panel._preview_drag(mime, x_item, "on")
        first_ghost = panel._ghost_item
        assert first_ghost is not None

        panel._preview_drag(mime, x_item, "on")
        assert panel._ghost_item is first_ghost
    finally:
        panel.shutdown()


def test_drag_preview_delta_computes_correct_candidate_points():
    _app()
    panel = PlannerPanel()
    try:
        before_plan_dict = panel._plan.to_dict()
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)

        new_block = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={"n_averages": 64})
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})
        decision = panel._preview_drag(mime, x_item, "on")
        assert decision is not None

        # Force the debounced compute now instead of waiting the real
        # 150 ms -- headless tests call the timer's slot directly.
        panel._on_preview_debounce_timeout()

        # Independently build the SAME candidate via plain ScanPlan/ScanBlock
        # APIs (not the panel's private mutation helpers) and compare.
        expected_plan = ScanPlan.from_dict(before_plan_dict)
        expected_x_loop = _find_loop_in_plan(expected_plan, Axis.STAGE_X)
        expected_x_loop.children.append(ScanBlock.from_dict(new_block.to_dict()))
        expected = estimate_plan(expected_plan)

        assert panel._chip_delta_preview.isVisibleTo(panel)
        assert f"{expected.total_points:,}" in panel._chip_delta_preview.text()

        assert panel._plan.to_dict() == before_plan_dict
        assert panel._undo_stack == []
    finally:
        panel.shutdown()


def test_drag_preview_delta_warns_when_candidate_exceeds_max_points():
    _app()
    panel = PlannerPanel()
    try:
        tiny_limits = PlanLimits(
            x_min_mm=-5.0, x_max_mm=5.0, y_min_mm=-5.0, y_max_mm=5.0,
            z_min_mm=-5.0, z_max_mm=5.0, voltage_range_V=3000.0, max_points=10,
        )
        panel.set_limits(tiny_limits)

        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        new_block = ActionBlock(action=ActionType.ACQUIRE_WAVEFORM)
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})
        decision = panel._preview_drag(mime, x_item, "on")
        assert decision is not None

        panel._on_preview_debounce_timeout()

        assert panel._chip_delta_preview.property("state") == "warn"
    finally:
        panel.shutdown()


def test_drag_preview_cleared_by_clear_drag_preview():
    """Stands in for both dragLeave and a rejected/accepted drop -- every
    exit path funnels through ``_clear_drag_preview()``."""
    _app()
    panel = PlannerPanel()
    try:
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        new_block = ActionBlock(action=ActionType.WAIT)
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})
        panel._preview_drag(mime, x_item, "on")
        panel._on_preview_debounce_timeout()
        assert panel._ghost_item is not None
        assert panel._chip_delta_preview.isVisibleTo(panel)

        panel._clear_drag_preview()

        assert panel._ghost_item is None
        assert panel._ghost_key is None
        assert panel._ghost_decision is None
        assert not panel._chip_delta_preview.isVisibleTo(panel)
        assert not panel._preview_debounce.isActive()
        assert _count_ghost_rows(panel) == 0
    finally:
        panel.shutdown()


def test_drag_preview_survives_into_real_drop_with_no_stray_ghost():
    """A real drop (palette-append fallback path exercised through the same
    _apply_drop the drop event calls) must leave no ghost/delta artifact
    behind, mirroring what _RecipeTree.dropEvent does before _apply_drop."""
    _app()
    panel = PlannerPanel()
    try:
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        new_block = ActionBlock(action=ActionType.WAIT, params={"seconds": 3.0})
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})

        decision = panel._preview_drag(mime, x_item, "on")
        assert panel._ghost_item is not None

        # Mirrors _RecipeTree.dropEvent: clear the preview, THEN apply.
        panel._clear_drag_preview()
        panel._apply_drop(*decision)

        assert panel._ghost_item is None
        assert _count_ghost_rows(panel) == 0
        new_x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        assert any(
            isinstance(c, ActionBlock) and c.action == ActionType.WAIT
            for c in new_x_loop.children
        )
    finally:
        panel.shutdown()


def test_shutdown_mid_drag_clears_ghost_and_stops_timers():
    _app()
    panel = PlannerPanel()
    x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
    x_item = panel._item_for_block(x_loop)
    new_block = ActionBlock(action=ActionType.WAIT)
    mime = _mime_for({"op": "new", "block": new_block.to_dict()})
    panel._preview_drag(mime, x_item, "on")
    assert panel._ghost_item is not None

    panel.shutdown()

    assert panel._ghost_item is None
    assert not panel._preview_debounce.isActive()
    assert not panel._debounce.isActive()


def test_drag_preview_never_touches_plan_or_undo_stack_across_a_session():
    """A whole preview "session" -- several hovers over different valid AND
    invalid candidates, plus a debounced delta compute -- must never mutate
    the real plan dict or push anything onto the undo stack."""
    _app()
    panel = PlannerPanel()
    try:
        before_plan = panel._plan.to_dict()
        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        y_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_Y)
        bias_loop = _bias_loop(panel._plan)
        x_item = panel._item_for_block(x_loop)
        y_item = panel._item_for_block(y_loop)
        bias_item = panel._item_for_block(bias_loop)

        new_action = _mime_for({"op": "new", "block": ActionBlock(action=ActionType.WAIT).to_dict()})
        move_bias = _mime_for({"op": "move", "path": panel._path_for_block(bias_loop)})

        panel._preview_drag(new_action, x_item, "on")
        panel._on_preview_debounce_timeout()
        panel._preview_drag(new_action, y_item, "on")
        panel._on_preview_debounce_timeout()
        panel._preview_drag(move_bias, x_item, "on")   # rejected: descendant
        panel._preview_drag(move_bias, bias_item, "on")   # rejected: self

        assert panel._plan.to_dict() == before_plan
        assert panel._undo_stack == []

        panel._clear_drag_preview()
        assert panel._plan.to_dict() == before_plan
        assert panel._undo_stack == []
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


def test_qt_danger_gate_no_stray_dialog_after_shutdown():
    """A queued confirm released by shutdown() must NOT pop a dialog when the
    event loop later delivers the stale request (reviewer-reproduced BUG:
    stray modal during window teardown)."""
    _app()
    gate = _StubGate(True)
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    # Let the worker post its queued request, then shut down BEFORE the GUI
    # thread pumps events (mimics teardown racing an in-flight confirm).
    time.sleep(0.1)
    gate.shutdown()
    t.join(timeout=5.0)
    assert not t.is_alive()
    assert result == [False]          # released as deny
    # NOW deliver the stale queued request — no dialog may appear.
    deadline = time.time() + 0.5
    while time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert gate.shown_actions == []


def test_qt_danger_gate_timeout_then_pump_shows_no_stray_dialog():
    """Same stray-request guard for the timeout path: after a confirm times
    out (deny), pumping the loop must not show the now-orphaned dialog."""
    _app()
    gate = _StubGate(True, timeout_s=0.05)
    action = DangerAction(kind="move", summary="Move stage")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive() and result == [False]
    deadline = time.time() + 0.5
    while time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert gate.shown_actions == []


def test_qt_danger_gate_dialog_exception_releases_worker_as_deny():
    """If the dialog slot raises, the blocked worker must be released
    immediately as deny — not stall until the timeout."""
    _app()

    class _RaisingGate(QtDangerGate):
        def _show_dialog(self, action: DangerAction) -> bool:
            raise RuntimeError("dialog exploded")

    gate = _RaisingGate(timeout_s=5.0)   # long timeout: release must NOT need it
    action = DangerAction(kind="hv_ramp", summary="Ramp")
    result: list[bool] = []

    def _worker() -> None:
        result.append(gate.confirm(action))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t0 = time.time()
    deadline = time.time() + 5.0
    while t.is_alive() and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    t.join(timeout=1.0)
    assert not t.is_alive()
    assert result == [False]
    assert time.time() - t0 < 4.0     # released by the finally, not the timeout


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
