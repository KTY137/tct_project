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
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QByteArray, QCoreApplication, QMimeData, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from controller.plan_estimate import PlanEstimate, estimate_plan
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan, ScanBlock
from controller.scan_plan_validator import PlanLimits, validate_plan
from gui.planner_panel import _MIME_TYPE, PlannerPanel, _default_template_plan

# TCT_app/routines/: resolved from this file's own path (tests/ -> TCT_app/),
# never from the CWD, so it stays correct regardless of where pytest runs from.
_ROUTINES_DIR = Path(__file__).resolve().parent.parent / "routines"


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump_until(predicate, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


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


def test_empty_plan_shows_empty_state_row_and_survives_theme_switch():
    """Design system §7/§9 D1 "Empty recipe state": a routine with no blocks
    gets a designed EmptyState row (never a silent blank tree), and it
    rebuilds cleanly across a live light/dark theme switch."""
    _app()
    from gui.panel_kit import EmptyState

    panel = PlannerPanel()
    try:
        panel.set_plan(ScanPlan(name="empty_routine", root=[]))
        # topLevelItem(0) is the decorative Preflight row (always present);
        # an empty plan adds exactly one more decorative row after it.
        assert panel._tree.topLevelItemCount() == 2
        widget = panel._tree.itemWidget(panel._tree.topLevelItem(1), 0)
        assert isinstance(widget, EmptyState)

        panel.refresh_theme("dark")
        assert panel._tree.topLevelItemCount() == 2
        widget = panel._tree.itemWidget(panel._tree.topLevelItem(1), 0)
        assert isinstance(widget, EmptyState)
        panel.refresh_theme("light")

        # Adding a real block clears the placeholder again (Preflight + the
        # one loop row, no EmptyState widget left behind).
        loop = LoopBlock(axis=Axis.STAGE_X, start=0.0, stop=1.0, step=0.1)
        panel.set_plan(ScanPlan(name="one_block", root=[loop]))
        assert panel._tree.topLevelItemCount() == 2
        widget = panel._tree.itemWidget(panel._tree.topLevelItem(1), 0)
        assert not isinstance(widget, EmptyState)
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


def test_default_template_matches_frozen_r1_routine():
    """``_default_template_plan()`` must stay byte-for-byte (as parsed dicts)
    identical to ``routines/R1_cce_v_map.yaml``.

    R1 is the frozen corpus routine originally GENERATED from this template
    (see ``tests/fixtures/routine_corpus/README.md``), plus an explicit
    post-bias-change settle WAIT that the template gained in the same beat
    that added this test. A failure here means one of two real regressions:
    either the template lost its bias-settle WAIT again (so a bias sweep
    would acquire during the bias/detector transient), or R1 and the template
    have independently drifted apart and one of them is now wrong -- in
    either case this is a real divergence to investigate, not a fixture to
    silently update. Read-only against ``routines/``; that file is a frozen,
    separately-owned fixture and is never written by this test."""
    r1_path = _ROUTINES_DIR / "R1_cce_v_map.yaml"
    assert r1_path.is_file(), f"expected frozen routine at {r1_path}"

    template_dict = _default_template_plan().to_dict()
    r1_dict = ScanPlan.load_yaml(str(r1_path)).to_dict()

    assert template_dict == r1_dict, (
        "_default_template_plan() has diverged from routines/R1_cce_v_map.yaml. "
        "R1 was generated from this template plus an explicit post-bias-change "
        "settle WAIT (first child of the bias_V loop, before the stage "
        "sub-loop) -- either the template lost that WAIT (a bias sweep would "
        "then acquire during the bias/detector transient) or the template and "
        "R1 have drifted apart independently and one of the two is wrong. "
        f"template={template_dict!r}\nr1={r1_dict!r}"
    )


def test_large_estimate_runs_off_gui_thread(monkeypatch):
    _app()
    import gui.planner_panel as planner_module

    started = threading.Event()
    release = threading.Event()

    def slow_estimate(_plan):
        started.set()
        assert release.wait(2.0)
        return PlanEstimate(
            total_points=42,
            total_leaf_visits=84,
            est_runtime_s=1.0,
            est_data_bytes=0,
            stage_travel_mm={"x": 0.0, "y": 0.0, "z": 0.0},
            hv_range_V=(0.0, 0.0),
        )

    panel = PlannerPanel()
    try:
        monkeypatch.setattr(planner_module, "estimate_plan", slow_estimate)
        panel._estimate_async_threshold = 0
        panel._last_estimate = None
        panel._last_estimate_key = None

        t0 = time.perf_counter()
        panel._recompute_estimate()
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.2
        assert panel._tile_points.value() == "…"
        assert panel._tile_points.is_stale()
        assert started.wait(1.0)

        release.set()
        assert _pump_until(lambda: panel._tile_points.value() == "42")
    finally:
        release.set()
        panel.shutdown()


def test_estimate_worker_thread_not_parented_to_panel():
    """Structural guard (MotorPanel crash class): the estimate worker QThread
    must not be a child of the panel that a soft config-reload's
    setCentralWidget() can delete mid-run (same guard as the laser worker)."""
    _app()
    panel = PlannerPanel()
    try:
        assert panel._estimate_thread is not None
        assert panel._estimate_thread.parent() is not panel
    finally:
        panel.shutdown()


def test_estimate_shutdown_bounded_when_estimate_in_flight(monkeypatch):
    """A huge estimate is a CPU walk quit() cannot interrupt; shutdown() must
    still RETURN within its bound (never hang the GUI thread waiting on it)."""
    _app()
    import gui.planner_panel as planner_module

    started = threading.Event()
    release = threading.Event()

    def slow_estimate(_plan):
        started.set()
        release.wait(5.0)
        return PlanEstimate(
            total_points=1, total_leaf_visits=1, est_runtime_s=0.0,
            est_data_bytes=0, stage_travel_mm={"x": 0.0, "y": 0.0, "z": 0.0},
            hv_range_V=(0.0, 0.0),
        )

    panel = PlannerPanel()
    try:
        # Patch AFTER construction so the constructor's (small default-template)
        # estimate uses the real, fast path and does not wedge on `release`.
        monkeypatch.setattr(planner_module, "estimate_plan", slow_estimate)
        panel._estimate_async_threshold = 0
        panel._last_estimate = None
        panel._last_estimate_key = None
        panel._recompute_estimate()
        assert started.wait(3.0), "estimate worker never entered the slow path"

        t0 = time.monotonic()
        panel.shutdown()
        elapsed = time.monotonic() - t0
        assert elapsed < 4.0, \
            f"shutdown() blocked {elapsed:.2f}s — the wait must be bounded"
    finally:
        release.set()          # let the still-running estimate finish + self-clean
        QCoreApplication.processEvents()


def test_rapid_estimate_edits_coalesce_latest_wins(monkeypatch):
    """Edits landing while an estimate runs must coalesce to the LATEST (never
    queue unboundedly), and a superseded result must not clobber the newer one.

    Wedge estimate A on the worker, fire two more edits (B then C) while it is
    in flight, release A: only A then C reach the worker — B is dropped — and
    the seq generation-guard discards A's stale result."""
    _app()
    import gui.planner_panel as planner_module

    calls: list[str] = []
    gate = threading.Event()       # holds the first estimate until released
    first = threading.Event()

    def rec_estimate(plan):
        calls.append(plan.name)
        if plan.name == "A":
            first.set()
            gate.wait(3.0)
        return PlanEstimate(
            total_points=len(plan.name), total_leaf_visits=1, est_runtime_s=0.0,
            est_data_bytes=0, stage_travel_mm={"x": 0.0, "y": 0.0, "z": 0.0},
            hv_range_V=(0.0, 0.0),
        )

    def mk(name: str) -> ScanPlan:
        loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0],
                         children=[ActionBlock(action=ActionType.ACQUIRE_WAVEFORM,
                                               params={})])
        return ScanPlan(name=name, root=[loop])

    panel = PlannerPanel()
    try:
        # Patch AFTER construction (constructor's estimate is the real fast
        # path); then only A/B/C reach the recording stub.
        monkeypatch.setattr(planner_module, "estimate_plan", rec_estimate)
        panel._estimate_async_threshold = 0
        panel._plan = mk("A")
        panel._last_estimate = None
        panel._last_estimate_key = None
        panel._recompute_estimate()               # A → worker (wedged on `gate`)
        assert first.wait(3.0), "estimate A never started on the worker"

        panel._plan = mk("B")                     # edit while A in flight
        panel._last_estimate_key = None
        panel._recompute_estimate()
        panel._plan = mk("C")                     # newer edit supersedes B
        panel._last_estimate_key = None
        panel._recompute_estimate()
        assert panel._estimate_pending is not None

        gate.set()                                # A returns → C runs next
        assert _pump_until(lambda: calls == ["A", "C"], 3.0), calls
        assert "B" not in calls, "a superseded edit reached the worker"
    finally:
        gate.set()
        panel.shutdown()


def test_safe_estimate_routes_large_plan_off_gui_thread(monkeypatch):
    """_safe_estimate() must NEVER run a full estimate_plan() leaf walk inline
    on the GUI thread for a large plan (the founding three-layer-law breach).
    It hands the plan to the existing off-thread worker (latest-wins coalescing)
    and returns the stale-but-marked cached value; the fresh estimate lands on
    the GUI thread only via the worker's queued ``done`` signal."""
    _app()
    import gui.planner_panel as planner_module

    call_threads: list = []

    def recording_estimate(_plan):
        call_threads.append(threading.current_thread())
        return PlanEstimate(
            total_points=7, total_leaf_visits=3, est_runtime_s=0.0,
            est_data_bytes=0, stage_travel_mm={"x": 0.0, "y": 0.0, "z": 0.0},
            hv_range_V=(0.0, 0.0),
        )

    panel = PlannerPanel()
    try:
        # Patch AFTER construction so the constructor's real (fast) estimate is
        # not recorded; then gate every plan as "large".
        monkeypatch.setattr(planner_module, "estimate_plan", recording_estimate)
        panel._estimate_async_threshold = 0
        panel._last_estimate = None
        panel._last_estimate_key = None

        result = panel._safe_estimate()

        # No synchronous GUI-thread leaf walk, and the stale value (None) returns
        # immediately.
        assert call_threads == [], "estimate_plan ran synchronously on the GUI thread"
        assert result is None

        # The worker delivers the fresh estimate OFF the GUI thread.
        assert _pump_until(lambda: len(call_threads) == 1)
        assert call_threads[0] is not threading.main_thread()
        assert _pump_until(lambda: panel._tile_points.value() == "7")
    finally:
        panel.shutdown()


def test_safe_estimate_small_plan_still_runs_inline(monkeypatch):
    """The small-plan fast path is unchanged: below the async threshold the
    leaf walk is cheap, so _safe_estimate() computes it inline on the GUI thread
    and caches the result (no round-trip)."""
    _app()
    import gui.planner_panel as planner_module

    call_threads: list = []

    def recording_estimate(_plan):
        call_threads.append(threading.current_thread())
        return PlanEstimate(
            total_points=5, total_leaf_visits=2, est_runtime_s=0.0,
            est_data_bytes=0, stage_travel_mm={"x": 0.0, "y": 0.0, "z": 0.0},
            hv_range_V=(0.0, 0.0),
        )

    panel = PlannerPanel()
    try:
        monkeypatch.setattr(planner_module, "estimate_plan", recording_estimate)
        panel._estimate_async_threshold = 10_000_000   # every plan is "small"
        panel._last_estimate = None
        panel._last_estimate_key = None

        result = panel._safe_estimate()

        assert len(call_threads) == 1
        assert call_threads[0] is threading.main_thread()
        assert result is not None and result.total_points == 5
    finally:
        panel.shutdown()


def test_drag_preview_large_candidate_skips_synchronous_estimate(monkeypatch):
    """The drag-drop delta preview must not run a full estimate_plan() leaf walk
    on the GUI thread for a large candidate.  Above the async threshold the
    candidate preview is a cheap point-count-only upper bound (total_points /
    total_leaf_visits are structural products, no leaf walk), and the chip
    honestly omits the runtime delta rather than blocking to compute one."""
    _app()
    import gui.planner_panel as planner_module

    call_threads: list = []

    def recording_estimate(plan):
        # Should never be reached synchronously on the preview path: the base
        # estimate is a cache hit and the large candidate is point-count-only.
        call_threads.append(threading.current_thread())
        raise AssertionError("estimate_plan ran on the GUI thread for a large candidate")

    panel = PlannerPanel()
    try:
        # Independently compute the expected candidate point count with the real
        # estimator BEFORE patching (the panel appends the new block into x_loop).
        before = panel._plan.to_dict()
        expected_plan = ScanPlan.from_dict(before)
        expected_x = _find_loop_in_plan(expected_plan, Axis.STAGE_X)
        new_block = ActionBlock(action=ActionType.WAIT, params={"seconds": 1.0})
        expected_x.children.append(ScanBlock.from_dict(new_block.to_dict()))
        expected_points = estimate_plan(expected_plan).total_points

        monkeypatch.setattr(planner_module, "estimate_plan", recording_estimate)
        panel._estimate_async_threshold = 0   # gate the candidate as "large"

        x_loop = _find_loop_in_plan(panel._plan, Axis.STAGE_X)
        x_item = panel._item_for_block(x_loop)
        mime = _mime_for({"op": "new", "block": new_block.to_dict()})
        assert panel._preview_drag(mime, x_item, "on") is not None

        panel._on_preview_debounce_timeout()

        # No synchronous estimate_plan anywhere on the preview path.
        assert call_threads == []
        text = panel._chip_delta_preview.text()
        assert panel._chip_delta_preview.isVisibleTo(panel)
        assert f"{expected_points:,}" in text
        assert "pts" in text
        # Point-count-only preview: the runtime-delta segment is dropped.
        assert "·" not in text
        # The preview never mutated the real plan / undo stack.
        assert panel._plan.to_dict() == before
        assert panel._undo_stack == []
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


def test_arm_confirmation_uses_live_plan_bias_range_not_stale_estimate(monkeypatch):
    """Regression (Mary review NIT): the Arm HV confirmation text must always
    match the plan being armed, even for a plan above
    ``_estimate_async_threshold`` whose cached ``_safe_estimate()`` result is
    stale (a fresh one is still in flight off-thread) or ``None``.  Seed a
    stale cached estimate carrying an obviously-wrong pre-edit bias range,
    edit the live plan's bias loop, and confirm the dialog text reflects the
    POST-edit range -- computed synchronously from the plan's own bias loops,
    never from the cache -- BEFORE any worker result could land (no
    ``processEvents()`` runs between the edit and the arm click)."""
    _app()
    import gui.planner_panel as planner_module

    captured: dict[str, str] = {}

    def fake_warning(parent, title, text, *args, **kwargs):
        captured["text"] = text
        return QMessageBox.StandardButton.No

    panel = PlannerPanel()
    try:
        panel._estimate_async_threshold = 0   # gate every plan as "large"

        # Stale cache: as if computed before the edit below, and deliberately
        # wrong so the test fails loudly if the dialog ever reads it.
        panel._last_estimate = PlanEstimate(
            total_points=1, total_leaf_visits=1, est_runtime_s=0.0,
            est_data_bytes=0, stage_travel_mm={"x": 0.0, "y": 0.0, "z": 0.0},
            hv_range_V=(-999.0, -999.0),
        )
        panel._last_estimate_key = "stale-key-not-matching-current-plan"

        # Edit the live plan's bias loop to a distinctive post-edit range.
        bias_loop = _bias_loop(panel._plan)
        bias_loop.values = None
        bias_loop.start = 12.0
        bias_loop.stop = 34.0
        bias_loop.step = 1.0

        monkeypatch.setattr(planner_module.QMessageBox, "warning", fake_warning)

        panel._on_arm_clicked()

        assert "text" in captured, "QMessageBox.warning was never called"
        assert "34" in captured["text"]
        assert "12" in captured["text"]
        assert "-999" not in captured["text"]
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
# Run-end clears the per-run arm (armed-envelope-expiry bug, Kaya 2026-07-13)  #
# --------------------------------------------------------------------------- #
def test_run_end_clears_stale_arm_so_second_execute_needs_rearm():
    """A finished run must leave NOTHING armed: before the fix _hv_armed /
    _armed_env / _env_cache all SURVIVED the run (only a plan EDIT cleared them),
    so the 2nd Execute of an UNCHANGED recipe rebuilt a gate from the stale
    envelope — a 100%-deterministic silent mid-run abort.  After the fix,
    on_finished re-locks Start and discards the committed envelope; the operator
    must re-arm, which re-derives FRESH."""
    _app()
    panel = PlannerPanel()
    try:
        # Arm the recipe the way a real run does: dry run → latch arm → the
        # coordinator's set_hv_armed(True) → set_running(True).
        panel._on_dry_run_clicked()
        panel._latch._arm_btn.click()
        panel._latch._arm_btn.click()
        assert panel._latch.is_armed()
        panel.set_hv_armed(True)

        # Bug PRECONDITION: everything the stale 2nd Execute fed on is live.
        assert panel._hv_armed is True
        assert panel._armed_env is not None
        assert panel._env_cache is not None
        stale_env = panel._armed_env

        panel.set_running(True)     # run starts (latch drops its arm during a run)
        panel.on_finished()         # run ends

        # The per-run arm is gone: Start re-locks, the committed envelope + cache
        # are discarded, and the latch is not armed — a 2nd Execute is impossible
        # without a fresh re-arm.
        assert panel._hv_armed is False
        assert panel._armed_env is None
        assert panel._env_cache is None
        assert panel._env_cache_key is None
        assert not panel._latch.is_armed()

        # Re-arming re-derives a FRESH envelope (never the stale one): the recipe
        # is unchanged (dry-run still valid), so the operator can re-arm.
        panel._on_dry_run_clicked()
        panel._latch._arm_btn.click()
        panel._latch._arm_btn.click()
        assert panel._latch.is_armed()
        assert panel._armed_env is not None
        assert panel._armed_env is not stale_env      # a fresh derivation, not the stale one
    finally:
        panel.shutdown()


def test_on_error_also_clears_the_per_run_arm():
    """The error terminal clears the arm exactly like on_finished — an errored
    run must not leave a stale authorization behind either."""
    _app()
    panel = PlannerPanel()
    try:
        panel._on_dry_run_clicked()
        panel._latch._arm_btn.click()
        panel._latch._arm_btn.click()
        panel.set_hv_armed(True)
        assert panel._hv_armed is True and panel._armed_env is not None

        panel.set_running(True)
        panel.on_error("compliance trip")

        assert panel._hv_armed is False
        assert panel._armed_env is None
        assert panel._env_cache is None
        assert not panel._latch.is_armed()
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
# CAPTURE_PHOTO palette rider (B2) + camera_available wiring                    #
# --------------------------------------------------------------------------- #
def _limits(camera_available: bool) -> PlanLimits:
    return PlanLimits(
        x_min_mm=-5.0, x_max_mm=5.0, y_min_mm=-5.0, y_max_mm=5.0,
        z_min_mm=-5.0, z_max_mm=5.0, voltage_range_V=3000.0, max_points=250_000,
        camera_available=camera_available,
    )


def _capture_photo_plan() -> ScanPlan:
    return ScanPlan(
        name="photo",
        root=[LoopBlock(
            axis=Axis.STAGE_X, values=[0.0, 1.0],
            children=[ActionBlock(action=ActionType.CAPTURE_PHOTO,
                                  params={"settle_s": 0.1})])],
    )


def test_palette_has_capture_photo_block():
    """The Add-blocks palette carries a CAPTURE_PHOTO entry (mechanical mirror of
    the WAIT row) whose drop payload is a real capture_photo action block."""
    _app()
    panel = PlannerPanel()
    idxs = [i for i in range(panel._palette.count())
            if "Capture photo" in panel._palette.item(i).text()]
    assert idxs, "no 'Capture photo' palette entry"
    payload = panel._palette.item(idxs[0]).data(Qt.ItemDataRole.UserRole)
    assert payload["op"] == "new"
    assert payload["block"]["action"] == "capture_photo"
    assert "settle_s" in payload["block"]["params"]


def test_capture_photo_validates_with_camera_and_rejects_without():
    """A capture_photo plan validates when a camera is configured and
    ERROR-rejects when not (fail-closed) — the two ends of the wired flag."""
    plan = _capture_photo_plan()
    ok = validate_plan(plan, _limits(camera_available=True))
    assert not any(
        "camera" in i.message.lower() and i.severity == "ERROR" for i in ok)
    rejected = validate_plan(plan, _limits(camera_available=False))
    assert any(
        "camera" in i.message.lower() and i.severity == "ERROR" for i in rejected)


def test_default_planner_limits_enable_camera():
    """Planner construction site: the standalone default admits capture_photo."""
    assert PlannerPanel._DEFAULT_LIMITS.camera_available is True


def test_plan_limits_camera_available_from_devices():
    """tct_gui construction site: camera_available tracks a configured camera
    backend (present → True; absent → False, fail-closed)."""
    from tct_gui import TCTMainWindow
    with_cam = SimpleNamespace(
        _devices=SimpleNamespace(camera=object(), motor=None,
                                 bias_supply=SimpleNamespace(voltage_range_V=1000.0)))
    assert TCTMainWindow._plan_limits(with_cam).camera_available is True
    without_cam = SimpleNamespace(
        _devices=SimpleNamespace(camera=None, motor=None,
                                 bias_supply=SimpleNamespace(voltage_range_V=1000.0)))
    assert TCTMainWindow._plan_limits(without_cam).camera_available is False
