"""Tests for controller.plan_compiler.compile_plan — the pure plan compiler.

Asserts the exact ordered Step list for a small nested plan (bias -> x -> y
snake): MoveStep only on driven-coordinate change (undriven axes stay None),
BiasStep only on bias change, and the danger flags set on both.
"""
from controller.scan_plan import (
    ActionBlock, ActionType, Axis, LoopBlock, ScanPlan,
)
from controller.plan_compiler import (
    compile_plan, MoveStep, BiasStep, AcquireStep, SaveStep,
    WaitStep, ManualPauseStep, ReadSlowControlStep, CapturePhotoStep,
)


def _acq(**p):
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params=p)


def _save():
    return ActionBlock(action=ActionType.SAVE_POINT, params={})


def _sig(step):
    """Compact comparable signature of a step's payload."""
    if isinstance(step, BiasStep):
        return ("Bias", step.target_V)
    if isinstance(step, MoveStep):
        return ("Move", step.x_mm, step.y_mm, step.z_mm)
    if isinstance(step, AcquireStep):
        return ("Acq", step.n_averages)
    if isinstance(step, SaveStep):
        return ("Save",)
    if isinstance(step, WaitStep):
        return ("Wait", step.seconds)
    if isinstance(step, ManualPauseStep):
        return ("Pause", step.prompt)
    if isinstance(step, ReadSlowControlStep):
        return ("Slow",)
    if isinstance(step, CapturePhotoStep):
        return ("Photo", step.settle_s, step.label)
    raise AssertionError(f"unknown step {step!r}")


def _photo(**p):
    return ActionBlock(action=ActionType.CAPTURE_PHOTO, params=p)


def nested_snake_plan():
    y = LoopBlock(axis=Axis.STAGE_Y, values=[0.0, 1.0], snake=True,
                  children=[_acq(), _save()])
    x = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0], children=[y])
    b = LoopBlock(axis=Axis.BIAS_V, values=[-10.0, -20.0], children=[x])
    return ScanPlan(root=[b], safety={"require_hv_confirmation": True})


def test_exact_step_sequence_for_nested_snake():
    steps = compile_plan(nested_snake_plan())
    got = [_sig(s) for s in steps]
    # Z is never a loop axis here, so every move leaves z_mm None ("do not
    # command") — the compiler must not fabricate z=0.0.
    expected = [
        # bias -10 block ------------------------------------------------
        ("Bias", -10.0),
        ("Move", 0.0, 0.0, None), ("Acq", 1), ("Save",),
        ("Move", 0.0, 1.0, None), ("Acq", 1), ("Save",),   # y 0->1
        ("Move", 1.0, 1.0, None), ("Acq", 1), ("Save",),   # x 0->1, y stays 1 (snake)
        ("Move", 1.0, 0.0, None), ("Acq", 1), ("Save",),   # y 1->0
        # bias -20 block ------------------------------------------------
        ("Bias", -20.0),
        ("Move", 0.0, 0.0, None), ("Acq", 1), ("Save",),
        ("Move", 0.0, 1.0, None), ("Acq", 1), ("Save",),
        ("Move", 1.0, 1.0, None), ("Acq", 1), ("Save",),
        ("Move", 1.0, 0.0, None), ("Acq", 1), ("Save",),
    ]
    assert got == expected


def test_bias_emitted_only_on_change():
    steps = compile_plan(nested_snake_plan())
    biases = [s.target_V for s in steps if isinstance(s, BiasStep)]
    assert biases == [-10.0, -20.0]          # two blocks, two BiasSteps only


def test_no_duplicate_move_when_two_actions_share_a_coordinate():
    # acquire + save at the same single coordinate -> exactly one MoveStep.
    loop = LoopBlock(axis=Axis.STAGE_X, values=[5.0], children=[_acq(), _save()])
    steps = compile_plan(ScanPlan(root=[loop]))
    moves = [s for s in steps if isinstance(s, MoveStep)]
    assert len(moves) == 1
    # x-only plan: the move commands x, and leaves y/z uncommanded (None).
    assert (moves[0].x_mm, moves[0].y_mm, moves[0].z_mm) == (5.0, None, None)


def test_x_only_plan_never_commands_y_or_z():
    """Regression (BLOCKER): an x-only plan must never fabricate y/z as 0.0 —
    every MoveStep leaves the undriven axes None ("do not command")."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 5.0, 10.0],
                     children=[_acq(), _save()])
    steps = compile_plan(ScanPlan(root=[loop]))
    moves = [s for s in steps if isinstance(s, MoveStep)]
    assert moves  # at least one move emitted
    assert all(m.y_mm is None and m.z_mm is None for m in moves)
    assert [m.x_mm for m in moves] == [0.0, 5.0, 10.0]


def test_danger_flags_on_move_and_bias():
    steps = compile_plan(nested_snake_plan())
    for s in steps:
        if isinstance(s, MoveStep):
            assert s.requires_confirm is True and s.danger_kind == "move"
        if isinstance(s, BiasStep):
            assert s.requires_confirm is True and s.danger_kind == "hv_ramp"


def test_bias_before_move_when_both_change():
    steps = compile_plan(nested_snake_plan())
    # first two steps of the whole plan: Bias then Move.
    assert isinstance(steps[0], BiasStep)
    assert isinstance(steps[1], MoveStep)


def test_bias_only_plan_emits_no_move():
    loop = LoopBlock(axis=Axis.BIAS_V, values=[-10.0, -20.0],
                     children=[_acq(), _save()])
    plan = ScanPlan(root=[loop], safety={"require_hv_confirmation": True})
    steps = compile_plan(plan)
    assert not any(isinstance(s, MoveStep) for s in steps)
    assert [s.target_V for s in steps if isinstance(s, BiasStep)] == [-10.0, -20.0]


def test_n_averages_read_from_acquire_params():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(n_averages=32), _save()])
    steps = compile_plan(ScanPlan(root=[loop]))
    acq = next(s for s in steps if isinstance(s, AcquireStep))
    assert acq.n_averages == 32


def test_loop_n_averages_propagates_to_acquire():
    """Regression (BUG): a loop-level n_averages must reach the AcquireStep, not
    be silently dropped to 1."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], n_averages=64,
                     children=[_acq(), _save()])
    steps = compile_plan(ScanPlan(root=[loop]))
    acq = next(s for s in steps if isinstance(s, AcquireStep))
    assert acq.n_averages == 64


def test_acquire_param_overrides_loop_n_averages():
    """Precedence: action params > enclosing loop."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], n_averages=64,
                     children=[_acq(n_averages=8), _save()])
    steps = compile_plan(ScanPlan(root=[loop]))
    acq = next(s for s in steps if isinstance(s, AcquireStep))
    assert acq.n_averages == 8


def test_innermost_loop_n_averages_wins():
    """Precedence: nearest enclosing loop that sets the field wins."""
    inner = LoopBlock(axis=Axis.STAGE_Y, values=[0.0], n_averages=8,
                      children=[_acq(), _save()])
    outer = LoopBlock(axis=Axis.STAGE_X, values=[0.0], n_averages=64,
                      children=[inner])
    steps = compile_plan(ScanPlan(root=[outer]))
    acq = next(s for s in steps if isinstance(s, AcquireStep))
    assert acq.n_averages == 8


def test_inner_loop_inherits_outer_n_averages_when_unset():
    """An inner loop that leaves n_averages unset inherits the outer loop's."""
    inner = LoopBlock(axis=Axis.STAGE_Y, values=[0.0],
                      children=[_acq(), _save()])          # n_averages None
    outer = LoopBlock(axis=Axis.STAGE_X, values=[0.0], n_averages=64,
                      children=[inner])
    steps = compile_plan(ScanPlan(root=[outer]))
    acq = next(s for s in steps if isinstance(s, AcquireStep))
    assert acq.n_averages == 64


def test_loop_settle_emits_waitstep_between_move_and_acquire():
    """Regression (BUG): a loop-level settle_s must become an explicit settle
    WaitStep, in move -> settle -> acquire order."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], settle_s=0.5,
                     children=[_acq(), _save()])
    steps = compile_plan(ScanPlan(root=[loop]))
    sigs = [_sig(s) for s in steps]
    assert sigs == [("Move", 0.0, None, None), ("Wait", 0.5),
                    ("Acq", 1), ("Save",)]


def test_no_settle_waitstep_when_settle_is_zero():
    """Default settle_s (0.0) emits no settle WaitStep (nothing to double-count)."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0],
                     children=[_acq(), _save()])
    steps = compile_plan(ScanPlan(root=[loop]))
    assert not any(isinstance(s, WaitStep) for s in steps)


def test_wavegen_settings_ride_in_acquire_params():
    wg = {"frequency_hz": 1000, "amplitude_V": 2.0}
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(wavegen=wg), _save()])
    steps = compile_plan(ScanPlan(root=[loop]))
    acq = next(s for s in steps if isinstance(s, AcquireStep))
    assert acq.params["wavegen"] == wg


def test_compiled_params_are_deep_copied_from_live_plan():
    """Regression (MAJOR): the compiler snapshots step params by DEEP copy.

    A shallow ``dict(params)`` would leave the NESTED ``wavegen`` mapping shared
    with the live plan object, so mutating ``plan.root[...].params['wavegen']``
    after validation/compile would silently change the values the executor
    commands to hardware — with no re-validation.  The compiled step must be an
    isolated snapshot."""
    acq = _acq(wavegen={"duty_cycle_pct": 0.2, "frequency_hz": 1000.0})
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[acq, _save()])
    plan = ScanPlan(root=[loop])
    step = next(s for s in compile_plan(plan) if isinstance(s, AcquireStep))
    assert step.params["wavegen"]["duty_cycle_pct"] == 0.2

    # Mutate the LIVE plan's nested wavegen mapping post-compile.
    plan.root[0].children[0].params["wavegen"]["duty_cycle_pct"] = 99.9
    # The compiled snapshot is untouched — it does not alias the live nested dict.
    assert step.params["wavegen"]["duty_cycle_pct"] == 0.2
    assert step.params["wavegen"] is not acq.params["wavegen"]


def test_every_visit_of_a_leaf_is_isolated_from_the_live_plan():
    """The isolation property holds for EVERY visit of a multi-visit leaf.

    The snapshot is taken once per leaf and shared across its visits (see
    ``test_one_params_snapshot_per_leaf_not_per_visit``), so this is the test
    that pins the property that memoization must not break: no compiled step —
    not the first visit, not the hundredth — may alias the live plan's nested
    ``wavegen`` mapping."""
    acq = _acq(wavegen={"duty_cycle_pct": 0.2})
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0, 2.0],
                     children=[acq, _save()])
    plan = ScanPlan(root=[loop])
    acqs = [s for s in compile_plan(plan) if isinstance(s, AcquireStep)]
    assert len(acqs) == 3                       # the leaf really was visited 3x

    plan.root[0].children[0].params["wavegen"]["duty_cycle_pct"] = 99.9
    assert all(s.params["wavegen"]["duty_cycle_pct"] == 0.2 for s in acqs)
    assert all(s.params["wavegen"] is not acq.params["wavegen"] for s in acqs)


def test_one_params_snapshot_per_leaf_not_per_visit():
    """Regression (RISK, perf): the params deepcopy is per LEAF, not per VISIT.

    ``compile_plan`` runs on the GUI thread (``ScanController.start_plan``), and
    ``PlanLimits.max_points`` legally admits 250k leaf visits — a deepcopy per
    *visit* costs ~0.65 s on a 90k-acquire plan and freezes the UI at scan start
    for no benefit.  All visits of one leaf therefore share ONE frozen snapshot;
    this identity assertion is the cheap, non-flaky guard against a silent
    regression to per-visit copying (a wall-clock bound would be flaky under a
    loaded test runner)."""
    acq = _acq(wavegen={"duty_cycle_pct": 0.2})
    loop = LoopBlock(axis=Axis.STAGE_X, values=[float(i) for i in range(50)],
                     children=[acq, _save()])
    acqs = [s for s in compile_plan(ScanPlan(root=[loop]))
            if isinstance(s, AcquireStep)]
    assert len(acqs) == 50
    assert len({id(s.params) for s in acqs}) == 1      # exactly one deepcopy

    # Two DIFFERENT leaves never share a snapshot (the memo is keyed per leaf).
    a1, a2 = _acq(wavegen={"duty_cycle_pct": 0.2}), _acq(wavegen={"duty_cycle_pct": 0.4})
    two = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[a1, a2, _save()])
    s1, s2 = [s for s in compile_plan(ScanPlan(root=[two]))
              if isinstance(s, AcquireStep)]
    assert s1.params is not s2.params
    assert s1.params["wavegen"]["duty_cycle_pct"] == 0.2
    assert s2.params["wavegen"]["duty_cycle_pct"] == 0.4


def test_live_edit_between_two_visits_of_one_leaf_never_reaches_a_step():
    """Hostile case: the live plan is mutated *during* the compile walk.

    Drives ``compile_plan`` through a plan proxy that edits the leaf's live
    ``wavegen`` mapping after the first visit is yielded.  Both compiled steps
    must still carry the ORIGINAL, once-snapshotted value: the snapshot is a
    real deep copy taken from the live plan, so no compiled step can ever be
    reached by a mutation of that plan — whenever it happens."""
    acq = _acq(wavegen={"duty_cycle_pct": 0.2})
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0], children=[acq])
    plan = ScanPlan(root=[loop])

    class _MutatingPlan:
        """Plan proxy: mutates the LIVE action params between leaf visits."""
        def iter_leaf_contexts_ex(self):
            for i, item in enumerate(plan.iter_leaf_contexts_ex()):
                if i == 1:                       # after visit 0 was compiled
                    acq.params["wavegen"]["duty_cycle_pct"] = 99.9
                yield item

    acqs = [s for s in compile_plan(_MutatingPlan()) if isinstance(s, AcquireStep)]
    assert len(acqs) == 2
    assert acq.params["wavegen"]["duty_cycle_pct"] == 99.9      # mutation DID run
    assert [s.params["wavegen"]["duty_cycle_pct"] for s in acqs] == [0.2, 0.2]


def test_recompile_picks_up_a_live_plan_edit():
    """The snapshot memo is per-CALL, never module-level.

    A cache that outlived the call would (a) hand a later compile a stale
    snapshot and (b) key on a possibly-recycled ``id()``.  Editing the plan and
    recompiling must therefore compile the NEW value — an operator who edits a
    parameter and restarts the scan gets what they see in the planner."""
    acq = _acq(wavegen={"duty_cycle_pct": 0.2})
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[acq])
    plan = ScanPlan(root=[loop])

    first = next(s for s in compile_plan(plan) if isinstance(s, AcquireStep))
    acq.params["wavegen"]["duty_cycle_pct"] = 0.9
    second = next(s for s in compile_plan(plan) if isinstance(s, AcquireStep))

    assert first.params["wavegen"]["duty_cycle_pct"] == 0.2     # old snapshot frozen
    assert second.params["wavegen"]["duty_cycle_pct"] == 0.9    # new compile re-reads
    assert first.params is not second.params


def test_all_action_types_map_to_steps():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[
        ActionBlock(action=ActionType.WAIT, params={"seconds": 2.5}),
        ActionBlock(action=ActionType.MANUAL_PAUSE, params={"prompt": "set laser"}),
        ActionBlock(action=ActionType.READ_SLOW_CONTROL, params={}),
    ])
    steps = compile_plan(ScanPlan(root=[loop]))
    kinds = [_sig(s) for s in steps if not isinstance(s, MoveStep)]
    assert kinds == [("Wait", 2.5), ("Pause", "set laser"), ("Slow",)]


def test_manual_pause_prompt_falls_back_to_message():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[
        ActionBlock(action=ActionType.MANUAL_PAUSE, params={"message": "hi"}),
    ])
    steps = compile_plan(ScanPlan(root=[loop]))
    pause = next(s for s in steps if isinstance(s, ManualPauseStep))
    assert pause.prompt == "hi"


def test_steps_are_frozen():
    import dataclasses
    import pytest
    step = MoveStep(1.0, 2.0, 3.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.x_mm = 9.0


# --------------------------------------------------------------------------- #
# HV ramp shaping (G1): the BIAS_V loop's shaping stamps onto each BiasStep    #
# --------------------------------------------------------------------------- #

def test_bias_ramp_shaping_stamped_from_loop():
    """A BIAS_V loop's ramp_step_V / ramp_delay_s reach every emitted BiasStep."""
    loop = LoopBlock(axis=Axis.BIAS_V, values=[-10.0, -20.0],
                     ramp_step_V=7.5, ramp_delay_s=0.25,
                     children=[_acq(), _save()])
    plan = ScanPlan(root=[loop], safety={"require_hv_confirmation": True})
    bias_steps = [s for s in compile_plan(plan) if isinstance(s, BiasStep)]
    assert [s.target_V for s in bias_steps] == [-10.0, -20.0]
    assert all(s.ramp_step_V == 7.5 and s.ramp_delay_s == 0.25 for s in bias_steps)


def test_bias_ramp_shaping_absent_is_none():
    """A BIAS_V loop with no ramp shaping emits BiasSteps carrying None (=
    driver default) — byte-identical to the pre-shaping behaviour."""
    steps = compile_plan(nested_snake_plan())
    bias_steps = [s for s in steps if isinstance(s, BiasStep)]
    assert bias_steps
    assert all(s.ramp_step_V is None and s.ramp_delay_s is None for s in bias_steps)


def test_bias_ramp_shaping_inherited_from_outer_bias_loop():
    """An inner BIAS_V loop that leaves shaping unset inherits the outer bias
    loop's (nearest-set-wins, mirroring n_averages/settle inheritance)."""
    inner = LoopBlock(axis=Axis.BIAS_V, values=[-10.0],
                      children=[_acq(), _save()])            # no shaping set
    outer = LoopBlock(axis=Axis.BIAS_V, values=[-100.0],
                      ramp_step_V=25.0, ramp_delay_s=0.05, children=[inner])
    plan = ScanPlan(root=[outer], safety={"require_hv_confirmation": True})
    bias_steps = [s for s in compile_plan(plan) if isinstance(s, BiasStep)]
    assert bias_steps
    assert all(s.ramp_step_V == 25.0 and s.ramp_delay_s == 0.05 for s in bias_steps)


def test_stage_loop_ramp_shaping_never_reaches_bias_step():
    """Ramp shaping set on a STAGE loop is ignored — only a BIAS_V loop
    contributes it (the validator warns about the misuse)."""
    bias = LoopBlock(axis=Axis.BIAS_V, values=[-10.0], children=[_acq(), _save()])
    stage = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                      ramp_step_V=99.0, ramp_delay_s=9.0, children=[bias])
    plan = ScanPlan(root=[stage], safety={"require_hv_confirmation": True})
    bias_steps = [s for s in compile_plan(plan) if isinstance(s, BiasStep)]
    assert bias_steps
    assert all(s.ramp_step_V is None and s.ramp_delay_s is None for s in bias_steps)


# --------------------------------------------------------------------------- #
# CAPTURE_PHOTO (B2): passive camera-grab step, carries settle_s/label,        #
# emitted after the move-on-change, and NOT danger-marked.                     #
# --------------------------------------------------------------------------- #

def test_capture_photo_compiles_to_step_with_params():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_photo(settle_s=0.25, label="tile-1")])
    steps = compile_plan(ScanPlan(root=[loop]))
    photo = next(s for s in steps if isinstance(s, CapturePhotoStep))
    assert photo.settle_s == 0.25
    assert photo.label == "tile-1"


def test_capture_photo_defaults_when_params_absent():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[_photo()])
    photo = next(s for s in compile_plan(ScanPlan(root=[loop]))
                 if isinstance(s, CapturePhotoStep))
    assert photo.settle_s == 0.0 and photo.label == ""


def test_capture_photo_is_not_danger_marked():
    """A camera grab is passive — CapturePhotoStep must carry NO confirmation /
    danger flags (unlike MoveStep / BiasStep), so the executor never gates it."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[_photo()])
    photo = next(s for s in compile_plan(ScanPlan(root=[loop]))
                 if isinstance(s, CapturePhotoStep))
    assert not hasattr(photo, "requires_confirm")
    assert not hasattr(photo, "danger_kind")


def test_capture_photo_emitted_after_move_at_coordinate():
    """MOVE-on-change fires first, then the photo grabs at that position."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 5.0],
                     children=[_photo(label="t"), _acq(), _save()])
    sigs = [_sig(s) for s in compile_plan(ScanPlan(root=[loop]))]
    assert sigs == [
        ("Move", 0.0, None, None), ("Photo", 0.0, "t"), ("Acq", 1), ("Save",),
        ("Move", 5.0, None, None), ("Photo", 0.0, "t"), ("Acq", 1), ("Save",),
    ]


def test_estimate_counts_capture_photo():
    """The estimator charges settle_s + a fixed grab cost and one frame's bytes
    (kept here because test_plan_estimate.py is outside this beat's file scope)."""
    import pytest
    from controller.plan_estimate import estimate_plan, CAMERA_GRAB_S, Sizing

    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_photo(settle_s=0.3)])
    est = estimate_plan(ScanPlan(root=[loop]))
    # First move is a free approach (0 travel); runtime = settle + grab cost.
    assert est.est_runtime_s == pytest.approx(0.3 + CAMERA_GRAB_S)
    # Data = exactly one conservative full-frame default, no SaveStep bytes.
    assert est.est_data_bytes == Sizing().camera_frame_bytes


def test_estimate_photo_data_scales_with_count():
    from controller.plan_estimate import estimate_plan, Sizing
    one = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[_photo()])
    three = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0, 2.0],
                      children=[_photo()])
    e1 = estimate_plan(ScanPlan(root=[one]))
    e3 = estimate_plan(ScanPlan(root=[three]))
    assert e1.est_data_bytes == Sizing().camera_frame_bytes
    assert e3.est_data_bytes == 3 * Sizing().camera_frame_bytes
