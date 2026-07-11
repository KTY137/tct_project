"""Property-style *parity* tests between the two consumers of
``ScanPlan.iter_leaf_contexts_ex``:

* :func:`controller.plan_estimate.estimate_plan` — streams the plan and sums a
  cost estimate (:class:`PlanEstimate`), and
* :func:`controller.plan_compiler.compile_plan` — flattens the same stream into a
  concrete ``list[Step]``.

They must stay in **parity**: the estimate's exposed counts / bias range / data
volume / travel accounting have to match what the compiler actually emits.  The
two modules are otherwise tested only in isolation (``test_plan_estimate.py``,
``test_plan_compiler.py``); a coffee-retro flagged the missing cross-check.

No new dependencies (no hypothesis): a seeded :class:`random.Random` generates a
few hundred small, valid, randomly-shaped plans across the representative space
(nesting depth, axis subsets, bias / no-bias, degenerate single points, snake,
repeats / multiple leaf visits per point).  Every parity check asserts only on
what the **public** ``PlanEstimate`` API exposes and cross-checks it against the
compiled step list — it never reimplements either module's internal maths.  On
any violation the failing plan's ``to_dict()`` is printed for reproducibility.

Parity properties asserted here (all against the compiled list):

1. ``total_points``      == plan.total_points()      == #AcquireStep
   (generator invariant: exactly one ACQUIRE per action-bearing coordinate).
2. ``total_leaf_visits`` == plan.total_leaf_visits() == #action-derived steps.
3. ``est_data_bytes``    == #SaveStep * Sizing.bytes_per_save().
4. ``hv_range_V``        == (min, max) of compiled BiasStep.target_V (else 0,0).
5. per-axis ``stage_travel_mm`` is consistent with which axes MoveSteps command.
6. the "compiled to zero steps" warning fires iff compile_plan() is empty.
7. the "manual pause" warning fires iff a ManualPauseStep is emitted.

Deliberately NOT asserted (the public API does not expose comparable data — see
the module docstring's follow-up list at the bottom).
"""
from __future__ import annotations

import random

import pytest

from controller.scan_plan import (
    ActionBlock, ActionType, Axis, LoopBlock, ScanPlan,
)
from controller.plan_estimate import estimate_plan, Sizing
from controller.plan_compiler import (
    compile_plan, MoveStep, BiasStep, AcquireStep, SaveStep,
    WaitStep, ManualPauseStep, ReadSlowControlStep,
)

# Loop sizes are tiny (<= 3 values, depth <= 3, <= 2 sibling loops) so each plan
# has at most a few dozen coordinates; a couple hundred plans compile + estimate
# in well under a second.  Seeds are fixed => fully deterministic.
N_PLANS = 160
_STAGE_AXES = (Axis.STAGE_X, Axis.STAGE_Y, Axis.STAGE_Z)
_ALL_AXES = _STAGE_AXES + (Axis.BIAS_V,)
_AXIS_KEY = {Axis.STAGE_X: "x", Axis.STAGE_Y: "y", Axis.STAGE_Z: "z"}


# --------------------------------------------------------------------------- #
# Random plan generation (seeded, no hypothesis).                             #
#                                                                             #
# Structural invariant that makes point/leaf parity checkable WITHOUT copying #
# the modules' logic: a block-list is EITHER a single "action group" (exactly #
# one ACQUIRE + optional other actions) OR one/two sibling LoopBlocks — never  #
# a mix.  So every action-bearing coordinate carries exactly one ACQUIRE, and #
# #AcquireStep == total_points by construction.                               #
# --------------------------------------------------------------------------- #

def _rand_values_spec(rng: random.Random, axis: Axis) -> dict:
    """A materializable value spec: explicit ``values`` or a ``start/stop/step``
    range, sometimes degenerate (single point), sometimes descending."""
    lo, hi = (-80.0, 0.0) if axis is Axis.BIAS_V else (0.0, 20.0)
    roll = rng.random()
    if roll < 0.25:                              # degenerate single point
        return {"values": [round(rng.uniform(lo, hi), 2)]}
    if roll < 0.70:                              # explicit 2-3 point list
        n = rng.randint(2, 3)
        start = round(rng.uniform(lo, hi), 2)
        step = round(rng.uniform(1.0, 6.0), 2)
        if rng.random() < 0.5:
            step = -step                         # descending sweep
        return {"values": [float(round(start + i * step, 2)) for i in range(n)]}
    # start/stop/step range (0..3 intervals; 0 => single-point degenerate)
    n = rng.randint(0, 3)
    start = round(rng.uniform(lo, hi), 2)
    step = round(rng.uniform(1.0, 5.0), 2)
    stop = round(start + (n * step) * (1 if rng.random() < 0.5 else -1), 2)
    return {"start": float(start), "stop": float(stop), "step": float(step)}


def _loop_kwargs(rng: random.Random, axis: Axis, allow_settle: bool) -> dict:
    kw: dict = {
        "n_averages": rng.choice([None, None, 2, 4]),
        "snake": rng.random() < 0.4,
    }
    if allow_settle and rng.random() < 0.4:
        kw["settle_s"] = round(rng.uniform(0.1, 0.5), 2)
    if axis is Axis.BIAS_V and rng.random() < 0.4:
        kw["ramp_step_V"] = round(rng.uniform(2.0, 25.0), 2)
        kw["ramp_delay_s"] = round(rng.uniform(0.05, 0.3), 2)
    return kw


def _action_group(rng: random.Random, *, allow_wait: bool) -> list[ActionBlock]:
    """One action-bearing block-list: EXACTLY one ACQUIRE + optional extras.

    The extras (save / read_slow_control / wait / manual_pause) give >1 leaf
    visit per coordinate — exercising the repeats / leaf-visit shape — while the
    single ACQUIRE keeps #AcquireStep == total_points."""
    acts = [ActionBlock(ActionType.ACQUIRE_WAVEFORM,
                        params=({"n_averages": rng.choice([2, 8])}
                                if rng.random() < 0.3 else {}))]
    if rng.random() < 0.85:
        acts.append(ActionBlock(ActionType.SAVE_POINT, params={}))
    if rng.random() < 0.30:
        acts.append(ActionBlock(ActionType.READ_SLOW_CONTROL, params={}))
    if allow_wait and rng.random() < 0.30:
        acts.append(ActionBlock(ActionType.WAIT,
                                params={"seconds": round(rng.uniform(0.5, 3.0), 2)}))
    if rng.random() < 0.15:
        acts.append(ActionBlock(ActionType.MANUAL_PAUSE, params={"prompt": "swap"}))
    return acts


def _rand_children(
    rng: random.Random, depth: int, *, allow_wait: bool, allow_settle: bool,
) -> list:
    """A block-list: an action group at the bottom, else 1-2 sibling loops."""
    if depth <= 0 or rng.random() < 0.30:
        return _action_group(rng, allow_wait=allow_wait)
    loops = []
    for _ in range(rng.randint(1, 2)):
        axis = rng.choice(_ALL_AXES)
        loops.append(LoopBlock(
            axis=axis,
            children=_rand_children(rng, depth - 1,
                                    allow_wait=allow_wait, allow_settle=allow_settle),
            **_rand_values_spec(rng, axis),
            **_loop_kwargs(rng, axis, allow_settle),
        ))
    return loops


def random_plan(
    rng: random.Random, *, allow_wait: bool = True, allow_settle: bool = True,
) -> ScanPlan:
    depth = rng.randint(0, 3)
    root = _rand_children(rng, depth, allow_wait=allow_wait, allow_settle=allow_settle)
    return ScanPlan(root=root, safety={"require_hv_confirmation": True})


def random_empty_plan(rng: random.Random) -> ScanPlan:
    """A plan that compiles to ZERO steps: no action anywhere (empty root, or
    loops whose innermost children list is empty)."""
    if rng.random() < 0.3:
        return ScanPlan(root=[])

    def build(d: int) -> LoopBlock:
        axis = rng.choice(_ALL_AXES)
        children = [] if d <= 1 else [build(d - 1)]
        return LoopBlock(axis=axis, children=children, **_rand_values_spec(rng, axis))

    return ScanPlan(root=[build(rng.randint(1, 3))])


# --------------------------------------------------------------------------- #
# Small helpers — count compiled step TYPES (never re-derive plan maths).      #
# --------------------------------------------------------------------------- #

_ACTION_STEP_TYPES = (
    AcquireStep, SaveStep, WaitStep, ManualPauseStep, ReadSlowControlStep,
)


def _count(steps, cls) -> int:
    return sum(isinstance(s, cls) for s in steps)


def _bail(plan: ScanPlan, idx: int, msg: str) -> None:
    pytest.fail(f"parity violation (plan #{idx}): {msg}\nplan={plan.to_dict()!r}")


# --------------------------------------------------------------------------- #
# 1. point count  ==  #AcquireStep                                            #
# --------------------------------------------------------------------------- #

def test_point_count_parity():
    """total_points (estimate == plan) == number of compiled AcquireSteps.

    The generator places exactly one ACQUIRE at every action-bearing coordinate,
    so the count of AcquireSteps the compiler emits is an INDEPENDENT witness of
    the grid size the estimate reports."""
    rng = random.Random(20260711)
    for i in range(N_PLANS):
        plan = random_plan(rng)
        est = estimate_plan(plan)
        n_acq = _count(compile_plan(plan), AcquireStep)
        if not (est.total_points == plan.total_points() == n_acq):
            _bail(plan, i,
                  f"est.total_points={est.total_points} "
                  f"plan.total_points={plan.total_points()} #AcquireStep={n_acq}")


# --------------------------------------------------------------------------- #
# 2. leaf visits  ==  #action-derived steps                                   #
# --------------------------------------------------------------------------- #

def test_leaf_visit_parity():
    """total_leaf_visits (estimate == plan) == number of ACTION-derived compiled
    steps.

    ``allow_settle=False`` here so every compiled ``WaitStep`` comes from a WAIT
    *action* (not a settle wait), making "action-derived steps" exactly the five
    action step types — with no need to guess which WaitSteps are settle."""
    rng = random.Random(19700101)
    for i in range(N_PLANS):
        plan = random_plan(rng, allow_settle=False)
        est = estimate_plan(plan)
        steps = compile_plan(plan)
        n_action = sum(_count(steps, c) for c in _ACTION_STEP_TYPES)
        # sanity: with no settle, the only non-action steps are Move/Bias.
        assert n_action == len(steps) - _count(steps, MoveStep) - _count(steps, BiasStep)
        if not (est.total_leaf_visits == plan.total_leaf_visits() == n_action):
            _bail(plan, i,
                  f"est.total_leaf_visits={est.total_leaf_visits} "
                  f"plan.total_leaf_visits={plan.total_leaf_visits()} "
                  f"#action_steps={n_action}")


# --------------------------------------------------------------------------- #
# 3. data volume  ==  #SaveStep * bytes_per_save                              #
# --------------------------------------------------------------------------- #

def test_data_bytes_parity():
    """est_data_bytes is exactly #SaveStep worth of saves (the estimate counts a
    save per SAVE_POINT; the compiler emits one SaveStep per SAVE_POINT)."""
    rng = random.Random(31415926)
    per_save = Sizing().bytes_per_save()
    for i in range(N_PLANS):
        plan = random_plan(rng)
        est = estimate_plan(plan)
        n_save = _count(compile_plan(plan), SaveStep)
        if est.est_data_bytes != n_save * per_save:
            _bail(plan, i,
                  f"est_data_bytes={est.est_data_bytes} "
                  f"#SaveStep*per_save={n_save * per_save} (#SaveStep={n_save})")


# --------------------------------------------------------------------------- #
# 4. HV range  ==  min/max of compiled BiasStep targets                       #
# --------------------------------------------------------------------------- #

def test_hv_range_parity():
    """hv_range_V equals (min, max) over the bias set points the compiler emits,
    and is (0, 0) exactly when no BiasStep is emitted."""
    rng = random.Random(27182818)
    for i in range(N_PLANS):
        plan = random_plan(rng)
        est = estimate_plan(plan)
        targets = [s.target_V for s in compile_plan(plan) if isinstance(s, BiasStep)]
        expected = (min(targets), max(targets)) if targets else (0.0, 0.0)
        if est.hv_range_V != expected:
            _bail(plan, i, f"hv_range_V={est.hv_range_V} vs compiled {expected}")


# --------------------------------------------------------------------------- #
# 5. per-axis travel is consistent with which axes MoveSteps command          #
# --------------------------------------------------------------------------- #

def test_travel_axis_consistency():
    """The estimate reports travel > 0 for an axis only if the compiler actually
    commands that axis in some MoveStep; and an axis no MoveStep ever commands
    reports exactly zero travel.

    (This is the strongest travel property assertable WITHOUT duplicating the
    estimate's free-initial-approach distance maths — see the skip list.)"""
    rng = random.Random(16180339)
    for i in range(N_PLANS):
        plan = random_plan(rng)
        est = estimate_plan(plan)
        moves = [s for s in compile_plan(plan) if isinstance(s, MoveStep)]
        for axis, key in _AXIS_KEY.items():
            attr = f"{key}_mm"
            commanded = any(getattr(m, attr) is not None for m in moves)
            travel = est.stage_travel_mm[key]
            if travel > 0.0 and not commanded:
                _bail(plan, i,
                      f"axis {key}: travel={travel} but no MoveStep commands it")
            if not commanded and travel != 0.0:
                _bail(plan, i,
                      f"axis {key}: uncommanded but travel={travel} (expected 0)")


# --------------------------------------------------------------------------- #
# 6. zero-step warning  <=>  compile_plan() is empty                          #
# --------------------------------------------------------------------------- #

def test_zero_step_warning_parity():
    """The 'compiled to zero steps' warning appears exactly when the compiler
    produces an empty step list — the estimate's internal step tally and the
    compiled length agree on emptiness."""
    rng = random.Random(12345678)
    for i in range(N_PLANS):
        # Alternate genuinely-empty plans with normal (>= 1 acquire) ones so both
        # directions of the iff are exercised.
        plan = random_empty_plan(rng) if i % 2 == 0 else random_plan(rng)
        est = estimate_plan(plan)
        compiled_empty = len(compile_plan(plan)) == 0
        warned = any("zero steps" in w for w in est.warnings)
        if warned != compiled_empty:
            _bail(plan, i,
                  f"zero-step warning={warned} but compiled_empty={compiled_empty}")


# --------------------------------------------------------------------------- #
# 7. manual-pause warning  <=>  a ManualPauseStep is emitted                   #
# --------------------------------------------------------------------------- #

def test_manual_pause_warning_parity():
    """The manual-pause warning appears exactly when the compiler emits at least
    one ManualPauseStep."""
    rng = random.Random(99887766)
    for i in range(N_PLANS):
        plan = random_plan(rng)
        est = estimate_plan(plan)
        has_pause = any(isinstance(s, ManualPauseStep) for s in compile_plan(plan))
        warned = any("manual pause" in w for w in est.warnings)
        if warned != has_pause:
            _bail(plan, i,
                  f"manual-pause warning={warned} but has_pause={has_pause}")


# --------------------------------------------------------------------------- #
# Follow-up candidates (parities the PUBLIC PlanEstimate API cannot express).  #
#                                                                             #
# * EXACT total step-count parity: internally estimate_plan's ``n_steps``      #
#   equals len(compile_plan(plan)) step-for-step, but PlanEstimate exposes     #
#   neither a step count nor a per-type breakdown — only the zero-step warning #
#   boundary (asserted in #6) is observable.  Exposing a StepCounts summary    #
#   (moves/bias/acquire/save/wait/...) would let a test assert full per-type   #
#   parity directly.                                                           #
# * EXACT travel DISTANCE parity: recomputing per-axis travel from MoveSteps   #
#   would duplicate the estimate's free-initial-approach accounting, so #5     #
#   only checks the presence/absence direction.  A public "n_moves" (or the    #
#   move count) on PlanEstimate would make an exact move-count parity checkable#
#   without reimplementing the distance maths.                                 #
# --------------------------------------------------------------------------- #
