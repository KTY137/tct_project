"""
Dry-run cost estimate for a :class:`~controller.scan_plan.ScanPlan`.

Given simple :class:`Timing` / :class:`Sizing` models, produce a
:class:`PlanEstimate`: point counts, wall-clock runtime, on-disk bytes,
per-axis stage travel and the HV range the plan will span.

Settle time is NOT modelled here: the plan is the single source of truth for it,
so the estimator adds the loop's effective settle time after each move. A move
contributes only travel-time; an axis missing from the current loop context
means "do not command" and adds no travel.

Pure and hardware-free. The estimator walks the plan stream directly instead of
compiling a giant ``list[Step]`` first, so large scans do not spend time and
memory allocating transient step objects just to add their costs. Serpentine
savings (fewer/shorter moves) are still reflected in both runtime and travel.
The estimate is deliberately a conservative upper bound (sequential-axis
motion, initial approach excluded).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from controller.plan_compiler import BiasStep
from controller.scan_plan import ActionType, LeafMeta, ScanPlan

# Fixed wall-clock cost of one CAPTURE_PHOTO grab+readout, on top of the step's
# own settle_s.  A small, backend-agnostic constant (exposure + USB transfer +
# per-chunk gzip are all ~tens of ms for an ROI frame); the estimate is a
# conservative upper bound, not a per-camera model.
CAMERA_GRAB_S: float = 0.05

# Structural ceiling above which ``estimate_plan`` refuses to walk the leaf
# stream and returns a not-estimated result instead.  The leaf walk runs at a
# measured ~342k leaf visits/s; at 1,000,000 visits that is ~3 s, which is the
# estimate worker's shutdown-join budget — walking a larger plan would let the
# worker overrun that join on teardown (the gate-red "estimate explosion").
# Above this, the cheap structural counts (``total_points`` /
# ``total_leaf_visits``, O(sum of loop lengths) via ``LoopBlock.materialize``)
# are still reported, but runtime/data/travel/HV come back as explicit
# not-estimated sentinels rather than misleading zeros.
#
# This is DISTINCT from the validator's ``PlanLimits.max_points`` (250,000),
# which independently REJECTS oversized plans on Validate / Dry-run.  The two
# thresholds serve different purposes (this one guards the estimator's worker
# join; that one is a hard run gate) and must not be unified: a plan between
# 250k and 1M still estimates fully here while the validator still flags it.
#
# ACCEPTED RESIDUAL (Mary review 44e17d4, Adam ruling 2026-07-14): the 1M
# ceiling is calibrated to the bench rate (~342k visits/s ⇒ ~3 s, the estimate
# worker's shutdown join budget).  On a slower machine a plan in the ~300k-1M
# band can still out-walk the 3 s join at full-app teardown.  The ceiling is
# NOT lowered because a validator-legal plan (≤250k points) can carry more
# leaf VISITS than points and must still estimate fully.  The real mitigation
# is a cooperative abort check inside the walk ("option c", queued follow-up);
# until it lands this narrow, human-only window is the documented trade-off.
ESTIMATE_MAX_LEAF_VISITS: int = 1_000_000


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
    # Bytes for one CAPTURE_PHOTO frame.  Resolution is unknown at estimate time
    # (ROI crop is chosen at run time), so this is a deliberately conservative
    # UPPER bound: a full-frame Mono8 Blackfly grab = 1920 x 1200 x 1 byte
    # (~2.3 MB).  A real ROI-cropped survey writes strictly less; gzip savings on
    # a textured surface are poor (~1.2-1.5x) so raw bytes stay the honest cap.
    camera_frame_bytes: int = 1920 * 1200

    def bytes_per_save(self) -> int:
        wave = self.channels * self.record_length * self.bytes_per_waveform_point
        return wave + self.scalars * 8


@dataclass(frozen=True)
class PlanEstimate:
    """Cost estimate for a plan.

    ``estimated`` is the honesty flag: when ``True`` (the normal case) the
    runtime/data/travel/HV fields carry real numbers.  When ``False`` the plan
    was above :data:`ESTIMATE_MAX_LEAF_VISITS` and the leaf walk was skipped, so
    those four fields are ``None`` *sentinels* — "not estimated", NOT zero — and
    only the cheap structural counts (``total_points`` / ``total_leaf_visits``)
    plus a too-large ``warnings`` entry are meaningful.  Consumers must branch on
    ``estimated`` (or equivalently check ``est_runtime_s is None``) before
    formatting the numeric fields.
    """
    total_points: int
    total_leaf_visits: int
    est_runtime_s: float | None
    est_data_bytes: int | None
    stage_travel_mm: dict[str, float] | None
    hv_range_V: tuple[float, float] | None
    warnings: list[str] = field(default_factory=list)
    estimated: bool = True

    def __post_init__(self) -> None:
        # The honesty flag and the sentinels must agree: estimated=True with a
        # None runtime (or the reverse) would sail past every consumer's
        # ``if not estimate.estimated`` guard into a float-format path.
        if self.estimated != (self.est_runtime_s is not None):
            raise ValueError(
                "PlanEstimate invariant violated: estimated="
                f"{self.estimated} but est_runtime_s={self.est_runtime_s!r}")


def estimate_plan(
    plan: ScanPlan,
    timing: Timing | None = None,
    sizing: Sizing | None = None,
) -> PlanEstimate:
    """Estimate the cost of *plan* by walking its leaf stream directly.

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

    # Structural short-circuit BEFORE any leaf walk.  ``total_leaf_visits`` is
    # cheap (O(sum of loop lengths): each LoopBlock materializes its own values
    # once and counts are multiplied, never the full cartesian product), so this
    # is instant even for a plan whose walk would take minutes.  Above the
    # ceiling we return the structural counts with not-estimated sentinels
    # rather than block the estimate worker's shutdown join (see
    # ESTIMATE_MAX_LEAF_VISITS).
    leaf_visits = plan.total_leaf_visits()
    if leaf_visits > ESTIMATE_MAX_LEAF_VISITS:
        return PlanEstimate(
            total_points=plan.total_points(),
            total_leaf_visits=leaf_visits,
            est_runtime_s=None,
            est_data_bytes=None,
            stage_travel_mm=None,
            hv_range_V=None,
            warnings=[
                f"Plan too large to estimate precisely "
                f"({leaf_visits:,} leaf visits) — reduce loop ranges."
            ],
            estimated=False,
        )

    runtime = 0.0
    travel = {"x": 0.0, "y": 0.0, "z": 0.0}
    n_saves = 0
    n_photos = 0
    warnings: list[str] = []

    # Per-axis last commanded position; None until that axis is first driven.
    cur = {"x": None, "y": None, "z": None}
    cur_bias: float | None = None
    prev_bias = 0.0            # HV starts off / at 0 V
    bias_targets: list[float] = []
    speed = timing.motor_speed_mm_s if timing.motor_speed_mm_s > 0 else 1.0
    n_manual = 0
    n_steps = 0

    for ctx, action, meta in plan.iter_leaf_contexts_ex():
        if "bias_V" in ctx:
            target = float(ctx["bias_V"])
            if cur_bias != target:
                bias_targets.append(target)
                dv = abs(target - prev_bias)
                runtime += _bias_ramp_seconds(
                    dv,
                    BiasStep(
                        target_V=target,
                        ramp_step_V=meta.bias_ramp_step_V,
                        ramp_delay_s=meta.bias_ramp_delay_s,
                    ),
                    timing,
                ) + timing.bias_hold_s
                cur_bias = target
                prev_bias = target
                n_steps += 1

        moved = (
            ("stage_x" in ctx and float(ctx["stage_x"]) != cur["x"])
            or ("stage_y" in ctx and float(ctx["stage_y"]) != cur["y"])
            or ("stage_z" in ctx and float(ctx["stage_z"]) != cur["z"])
        )
        if moved:
            move_dist = 0.0
            for ctx_key, axis in (("stage_x", "x"), ("stage_y", "y"), ("stage_z", "z")):
                if ctx_key not in ctx:
                    continue          # axis not commanded by this move
                val = float(ctx[ctx_key])
                prev = cur[axis]
                if prev is not None:  # first drive of an axis is a free approach
                    d = abs(val - prev)
                    travel[axis] += d
                    move_dist += d
                cur[axis] = val
            runtime += move_dist / speed
            n_steps += 1
            if meta.settle_s > 0.0:
                runtime += meta.settle_s
                n_steps += 1

        params = action.params or {}
        at = action.action
        if at == ActionType.ACQUIRE_WAVEFORM:
            runtime += _effective_n_averages(params, meta) * timing.s_per_average
            n_steps += 1
        elif at == ActionType.SAVE_POINT:
            n_saves += 1
            n_steps += 1
        elif at == ActionType.WAIT:
            runtime += float(params.get("seconds", 0.0))
            n_steps += 1
        elif at == ActionType.MANUAL_PAUSE:
            n_manual += 1
            n_steps += 1
        elif at == ActionType.READ_SLOW_CONTROL:
            n_steps += 1  # slow-control read cost is negligible in this model
        elif at == ActionType.CAPTURE_PHOTO:
            # settle (dwell before grab) + a fixed grab/readout cost; the frame
            # adds camera_frame_bytes to the data estimate below.
            runtime += float(params.get("settle_s", 0.0)) + CAMERA_GRAB_S
            n_photos += 1
            n_steps += 1

    if n_manual:
        warnings.append(
            f"{n_manual} manual pause(s): runtime excludes indeterminate human "
            "wait time")
    if not n_steps:
        warnings.append("plan compiled to zero steps (nothing to run)")

    hv_range = (min(bias_targets), max(bias_targets)) if bias_targets else (0.0, 0.0)
    est_data = sizing.bytes_per_save() * n_saves + sizing.camera_frame_bytes * n_photos

    return PlanEstimate(
        total_points=plan.total_points(),
        total_leaf_visits=leaf_visits,
        est_runtime_s=runtime,
        est_data_bytes=est_data,
        stage_travel_mm=travel,
        hv_range_V=hv_range,
        warnings=warnings,
    )


def _bias_ramp_seconds(dv: float, step: BiasStep, timing: Timing) -> float:
    """Wall-clock estimate for one ``BiasStep``'s ramp of magnitude *dv*.

    *dv* is measured from the previous compiled bias set point (0 V at run
    start), which the walk tracks in ``prev_bias`` — the estimate never needs a
    conservative guess.

    Two regimes, so a plan-driven shaped ramp is estimated with the shape it
    will actually use:

    * **No per-step shaping** (``ramp_step_V`` and ``ramp_delay_s`` both None):
      byte-identical to the historic estimate ``(dv / global_step) *
      global_delay`` — a float step count against the ``Timing`` defaults.  This
      keeps every existing preview unchanged.
    * **Per-step shaping** (either field set): the ramp is modelled as the real
      DISCRETE step count the driver walks, ``ceil(dv / step) * delay``.  Each
      field independently falls back to the ``Timing`` global when only the
      other is set (mirroring the executor's ``_ramp_bias`` fallback).
    """
    if step.ramp_step_V is None and step.ramp_delay_s is None:
        gstep = timing.bias_ramp_step_V if timing.bias_ramp_step_V > 0 else 1.0
        return (dv / gstep) * timing.bias_ramp_delay_s

    eff_step = (step.ramp_step_V if step.ramp_step_V is not None
                else timing.bias_ramp_step_V)
    eff_step = eff_step if eff_step > 0 else 1.0
    eff_delay = (step.ramp_delay_s if step.ramp_delay_s is not None
                 else timing.bias_ramp_delay_s)
    n_steps = math.ceil(dv / eff_step) if dv > 0 else 0
    return n_steps * eff_delay


def _effective_n_averages(params: dict, meta: LeafMeta) -> int:
    """Effective averages for one acquire action, matching the compiler."""
    raw = params.get("n_averages", meta.n_averages)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = meta.n_averages
    return n if n >= 1 else 1
