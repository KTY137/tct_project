"""
Dry-run cost estimate for a :class:`~controller.scan_plan.ScanPlan`.

Given a compiled step list (from :func:`controller.plan_compiler.compile_plan`)
and simple :class:`Timing` / :class:`Sizing` models, produce a
:class:`PlanEstimate`: point counts, wall-clock runtime, on-disk bytes, per-axis
stage travel and the HV range the plan will span.

Settle time is NOT modelled here: the plan is the single source of truth for it,
so the compiler emits an explicit settle :class:`WaitStep` after each move and
this estimate simply sums those ``WaitStep``s.  A ``MoveStep`` contributes only
travel-time; an axis whose target is ``None`` ("do not command") adds no travel.

Pure and hardware-free.  There is exactly **one** walk of the plan — the
compiler's — so serpentine savings (fewer/shorter moves) are automatically
reflected in both runtime and travel.  The estimate is deliberately a
conservative upper bound (sequential-axis motion, initial approach excluded).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from controller.plan_compiler import (
    AcquireStep,
    BiasStep,
    ManualPauseStep,
    MoveStep,
    ReadSlowControlStep,
    SaveStep,
    WaitStep,
    compile_plan,
)
from controller.scan_plan import ScanPlan


@dataclass(frozen=True)
class Timing:
    """Wall-clock model.  Defaults track the shipped config / ramp_to defaults.

    ``motor_speed_mm_s`` = 1500 mm/min feed rate; ``bias_ramp_step_V`` /
    ``bias_ramp_delay_s`` mirror ``bias_supply_base.ramp_to`` (5 V / 0.1 s).

    Settle time is deliberately absent: it is owned by the plan (``LoopBlock``'s
    ``settle_s``) and reaches the estimate as explicit settle ``WaitStep``s the
    compiler emits, so modelling it here too would double-count it.
    """
    motor_speed_mm_s: float = 25.0
    s_per_average: float = 0.02
    bias_ramp_step_V: float = 5.0
    bias_ramp_delay_s: float = 0.1
    bias_hold_s: float = 1.0


@dataclass(frozen=True)
class Sizing:
    """On-disk model.  Defaults track SCAN_DATA_FORMAT: f4 samples, 2 channels."""
    bytes_per_waveform_point: int = 4      # float32 (f4) per sample
    record_length: int = 1024              # samples per waveform
    channels: int = 2                      # ref_ch1 + dut_ch2
    scalars: int = 16                      # f8 scalars per point (pos/bias/...)

    def bytes_per_save(self) -> int:
        wave = self.channels * self.record_length * self.bytes_per_waveform_point
        return wave + self.scalars * 8


@dataclass(frozen=True)
class PlanEstimate:
    total_points: int
    total_leaf_visits: int
    est_runtime_s: float
    est_data_bytes: int
    stage_travel_mm: dict[str, float]
    hv_range_V: tuple[float, float]
    warnings: list[str] = field(default_factory=list)


def estimate_plan(
    plan: ScanPlan,
    timing: Timing | None = None,
    sizing: Sizing | None = None,
) -> PlanEstimate:
    """Estimate the cost of *plan* by walking its compiled step list.

    Runtime is summed per step:
      * MoveStep  -> (|dx|+|dy|+|dz|) / speed  (settle is a separate WaitStep)
      * BiasStep  -> (|dV| / ramp_step) * ramp_delay + hold
      * AcquireStep -> n_averages * s_per_average
      * WaitStep  -> seconds  (covers both explicit WAIT actions and settle)
    Data is ``bytes_per_save`` times the number of SaveSteps.  Travel is tracked
    per axis: an axis whose target is ``None`` ("do not command") is skipped, and
    the first time an axis is commanded is a free initial approach (start
    position is unknown), which keeps the snake vs. raster travel comparison
    honest.
    """
    timing = timing or Timing()
    sizing = sizing or Sizing()
    steps = compile_plan(plan)

    runtime = 0.0
    travel = {"x": 0.0, "y": 0.0, "z": 0.0}
    n_saves = 0
    warnings: list[str] = []

    # Per-axis last commanded position; None until that axis is first driven.
    cur = {"x": None, "y": None, "z": None}
    prev_bias = 0.0            # HV starts off / at 0 V
    bias_targets: list[float] = []
    speed = timing.motor_speed_mm_s if timing.motor_speed_mm_s > 0 else 1.0
    ramp_step = timing.bias_ramp_step_V if timing.bias_ramp_step_V > 0 else 1.0
    n_manual = 0

    for step in steps:
        if isinstance(step, MoveStep):
            move_dist = 0.0
            for axis, val in (("x", step.x_mm), ("y", step.y_mm), ("z", step.z_mm)):
                if val is None:
                    continue          # axis not commanded by this move
                prev = cur[axis]
                if prev is not None:  # first drive of an axis is a free approach
                    d = abs(val - prev)
                    travel[axis] += d
                    move_dist += d
                cur[axis] = val
            runtime += move_dist / speed
        elif isinstance(step, BiasStep):
            bias_targets.append(step.target_V)
            dv = abs(step.target_V - prev_bias)
            runtime += (dv / ramp_step) * timing.bias_ramp_delay_s + timing.bias_hold_s
            prev_bias = step.target_V
        elif isinstance(step, AcquireStep):
            runtime += step.n_averages * timing.s_per_average
        elif isinstance(step, WaitStep):
            runtime += step.seconds
        elif isinstance(step, SaveStep):
            n_saves += 1
        elif isinstance(step, ManualPauseStep):
            n_manual += 1
        elif isinstance(step, ReadSlowControlStep):
            pass  # slow-control read cost is negligible in this model

    if n_manual:
        warnings.append(
            f"{n_manual} manual pause(s): runtime excludes indeterminate human "
            "wait time")
    if not steps:
        warnings.append("plan compiled to zero steps (nothing to run)")

    hv_range = (min(bias_targets), max(bias_targets)) if bias_targets else (0.0, 0.0)
    est_data = sizing.bytes_per_save() * n_saves

    return PlanEstimate(
        total_points=plan.total_points(),
        total_leaf_visits=plan.total_leaf_visits(),
        est_runtime_s=runtime,
        est_data_bytes=est_data,
        stage_travel_mm=travel,
        hv_range_V=hv_range,
        warnings=warnings,
    )
