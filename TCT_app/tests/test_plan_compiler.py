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
    WaitStep, ManualPauseStep, ReadSlowControlStep,
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
    raise AssertionError(f"unknown step {step!r}")


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
