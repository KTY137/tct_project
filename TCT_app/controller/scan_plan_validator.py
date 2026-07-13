"""
Fail-closed pre-flight validation for a :class:`~controller.scan_plan.ScanPlan`.

This is the plan-level analogue of :mod:`controller.config_validator`: it walks a
plan tree *before* any hardware exists and returns a list of
:class:`PlanIssue` (ERROR / WARNING), mirroring that module's idiom
(``validate_plan`` + ``errors`` / ``warnings`` helpers).

It is **pure**: it never imports ``DeviceManager`` or a device backend, never
opens a file, never talks to hardware.  :class:`PlanLimits` carries the concrete
gates (stage software limits, HV range, point cap) that the real hardware layer
(``motor_base.SoftwareLimits.check`` and
``bias_supply_base.check_voltage_in_range``) enforces at runtime; the validator
pre-flights those same gates so a scan is rejected on paper, not mid-run.

Design stance: fail closed.  A loop with a broken range is reported, never
crashed on; a plan that drives HV without an explicit confirmation flag is an
ERROR, not a shrug.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from controller.scan_plan import (
    ActionBlock,
    ActionType,
    Axis,
    LoopBlock,
    STAGE_AXES,
    ScanBlock,
    ScanPlan,
)

ERROR = "ERROR"
WARNING = "WARNING"


@dataclass(frozen=True)
class PlanIssue:
    severity: str    # ERROR | WARNING
    path: str        # node path in the plan tree, e.g. root/loop(bias_V)[0]
    message: str

    def __str__(self) -> str:
        return f"[{self.path}] {self.message}"


@dataclass(frozen=True)
class PlanLimits:
    """Pure guardrails the validator pre-flights.

    These mirror the runtime gates without importing them: ``x/y/z`` bounds
    stand in for ``motor_base.SoftwareLimits``; ``voltage_range_V`` stands in for
    ``bias_supply_base.check_voltage_in_range``; ``max_points`` caps
    ``ScanPlan.total_leaf_visits()``.  Never construct this from a
    ``DeviceManager`` — build it from config so the validator stays hardware-free.
    """
    x_min_mm: float
    x_max_mm: float
    y_min_mm: float
    y_max_mm: float
    z_min_mm: float
    z_max_mm: float
    voltage_range_V: float
    max_points: int
    homed_required: bool = True
    # Whether a camera device is configured/available for this run.  A
    # CAPTURE_PHOTO action is an ERROR unless this is True (fail-closed: a photo
    # step with no camera is rejected on paper, not left to fail mid-run).  Built
    # from config by the caller alongside the other guardrails — the validator
    # itself never imports a DeviceManager.  Defaults False so a caller that
    # never wires it can never accidentally admit a camera-less photo plan.
    camera_available: bool = False


# --------------------------------------------------------------------------- #
# Known-key sets — unknown keys are WARNED about (typo detection), exactly the  #
# config_validator discipline.  These are intentionally explicit, never a       #
# getattr/eval dispatch.                                                         #
# --------------------------------------------------------------------------- #

# LoopBlock.reduce is a represented-not-executed post-processing tag.  Unknown
# values are warned about; the set is a best-effort TCT vocabulary and should be
# reconciled with the (future) reduction implementation.
_KNOWN_REDUCE: frozenset[str] = frozenset({
    "max_gradient", "max_amplitude", "peak", "min", "max", "mean",
    "charge", "integral", "rise_time", "cfd_time", "amplitude",
})

# ActionBlock.params keys, per action.  Wavegen settings ride in
# ACQUIRE_WAVEFORM's params["wavegen"]; WAIT reads params["seconds"];
# MANUAL_PAUSE reads params["prompt"]/["message"].
_KNOWN_ACTION_PARAMS: dict[ActionType, frozenset[str]] = {
    ActionType.ACQUIRE_WAVEFORM: frozenset({
        "wavegen", "n_averages", "channels", "record_length",
        "timeout_s", "label",
    }),
    ActionType.SAVE_POINT: frozenset({"label", "tags", "reduce", "group"}),
    ActionType.WAIT: frozenset({"seconds", "reason"}),
    ActionType.MANUAL_PAUSE: frozenset({"prompt", "message", "reason"}),
    ActionType.READ_SLOW_CONTROL: frozenset({"channels", "sensors", "label"}),
    ActionType.CAPTURE_PHOTO: frozenset({"settle_s", "label"}),
}


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def validate_plan(plan: ScanPlan, limits: PlanLimits) -> list[PlanIssue]:
    """Validate *plan* against *limits*; return issues (may be empty).

    All checks are collected (never early-returned) so a single pass surfaces
    every problem, and no check is allowed to raise — a malformed loop range is
    reported as an ERROR, not propagated.
    """
    issues: list[PlanIssue] = []

    # (b) empty plan.
    if not plan.root:
        issues.append(PlanIssue(ERROR, "root", "plan is empty (no blocks to run)"))

    state = {"has_bias": False}
    _walk(plan.root, "root", limits, issues, state, acquired_in_scope=False)

    # (e) point cap.  total_leaf_visits() materializes internally, so wrap it —
    # a bad range is already reported by (a); we just avoid crashing here.
    try:
        visits = plan.total_leaf_visits()
    except ValueError:
        visits = None
    if visits is not None and visits > limits.max_points:
        issues.append(PlanIssue(
            ERROR, "root",
            f"plan runs {visits} leaf visits, exceeding max_points "
            f"= {limits.max_points}"))

    # (f) fail-closed HV confirmation: any bias-driving plan MUST carry an
    # explicit safety.require_hv_confirmation == True.
    if state["has_bias"] and (plan.safety or {}).get("require_hv_confirmation") is not True:
        issues.append(PlanIssue(
            ERROR, "root",
            "plan drives bias voltage but safety.require_hv_confirmation is not "
            "True — refusing (HV requires explicit confirmation, fail-closed)"))

    # (i) trailing manual pause: legal (the executor promotes the final PAUSED
    # to a clean FINISHED) but almost always a recipe mistake — the pause gates
    # nothing.  iter_leaf_contexts materializes internally, so wrap it; a bad
    # range is already reported by (a).
    try:
        last_action = None
        for _ctx, action in plan.iter_leaf_contexts():
            last_action = action
        if last_action is not None and last_action.action == ActionType.MANUAL_PAUSE:
            issues.append(PlanIssue(
                WARNING, "root",
                "plan ends on a MANUAL_PAUSE — it gates nothing (the run just "
                "finishes); move it before the steps it should gate"))
    except ValueError:
        pass

    return issues


def errors(issues: list[PlanIssue]) -> list[str]:
    return [str(i) for i in issues if i.severity == ERROR]


def warnings(issues: list[PlanIssue]) -> list[str]:
    return [str(i) for i in issues if i.severity == WARNING]


# --------------------------------------------------------------------------- #
# Tree walk                                                                    #
# --------------------------------------------------------------------------- #

def _walk(
    blocks: list[ScanBlock],
    path: str,
    limits: PlanLimits,
    issues: list[PlanIssue],
    state: dict[str, Any],
    acquired_in_scope: bool,
) -> None:
    """Recurse the block list, collecting issues.

    ``acquired_in_scope`` tracks whether an ACQUIRE_WAVEFORM has run *earlier in
    this branch* — either as a preceding sibling here or in an enclosing scope.
    It is threaded down into child loops but a sibling loop's internal acquire
    never leaks back out, which is exactly the "earlier in its branch" semantics
    of check (g).
    """
    seen_acquire = acquired_in_scope
    for i, b in enumerate(blocks):
        if isinstance(b, LoopBlock):
            npath = f"{path}/loop({b.axis.value})[{i}]"
            _check_loop_semantics(b, npath, issues)
            vals = _safe_materialize(b, npath, issues)
            if b.axis == Axis.BIAS_V:
                state["has_bias"] = True
                if vals is not None:
                    _check_bias_values(vals, npath, limits, issues)
            elif b.axis in STAGE_AXES and vals is not None:
                _check_stage_values(b.axis, vals, npath, limits, issues)
            _walk(b.children, f"{npath}/children", limits, issues, state,
                  acquired_in_scope=seen_acquire)
        elif isinstance(b, ActionBlock):
            npath = f"{path}/action({b.action.value})[{i}]"
            if b.action == ActionType.ACQUIRE_WAVEFORM:
                seen_acquire = True
            elif b.action == ActionType.SAVE_POINT and not seen_acquire:
                issues.append(PlanIssue(
                    WARNING, npath,
                    "SAVE_POINT with no ACQUIRE_WAVEFORM earlier in its branch "
                    "— nothing acquired to save"))
            # Device-availability gate (fail-closed): a photo step needs a
            # camera.  Mirrors the config-derived guardrails PlanLimits carries
            # for HV / stage limits — refuse on paper rather than mid-run.
            if b.action == ActionType.CAPTURE_PHOTO and not limits.camera_available:
                issues.append(PlanIssue(
                    ERROR, npath,
                    "CAPTURE_PHOTO needs a camera but none is configured/available "
                    "(PlanLimits.camera_available is False) — refusing (fail-closed)"))
            _check_action_params(b, npath, issues)


def _safe_materialize(
    loop: LoopBlock, path: str, issues: list[PlanIssue]
) -> list[float] | None:
    """(a) materialize, converting any ValueError into an ERROR issue."""
    try:
        return loop.materialize()
    except ValueError as exc:
        issues.append(PlanIssue(ERROR, path, f"invalid loop range: {exc}"))
        return None


def _check_loop_semantics(
    loop: LoopBlock, path: str, issues: list[PlanIssue]
) -> None:
    """(h) settle_s / n_averages / reduce / HV ramp shaping sanity on a loop."""
    if _is_num(loop.settle_s) and float(loop.settle_s) < 0:
        issues.append(PlanIssue(
            ERROR, path, f"settle_s must be >= 0 (got {loop.settle_s!r})"))
    if loop.n_averages is not None and int(loop.n_averages) < 1:
        issues.append(PlanIssue(
            ERROR, path, f"n_averages must be >= 1 (got {loop.n_averages!r})"))
    if loop.reduce is not None and str(loop.reduce) not in _KNOWN_REDUCE:
        issues.append(PlanIssue(
            WARNING, path,
            f"unknown reduce '{loop.reduce}' — typo? It is ignored downstream."))

    # HV ramp shaping (BIAS_V loops only).  Fail closed: a nonsensical shape
    # would drive the supply badly, so a non-positive step or a negative delay
    # is an ERROR (a zero step could jump/loop badly in the driver's ramp).
    if loop.ramp_step_V is not None and (
        not _is_num(loop.ramp_step_V) or float(loop.ramp_step_V) <= 0
    ):
        issues.append(PlanIssue(
            ERROR, path, f"ramp_step_V must be > 0 (got {loop.ramp_step_V!r})"))
    if loop.ramp_delay_s is not None and (
        not _is_num(loop.ramp_delay_s) or float(loop.ramp_delay_s) < 0
    ):
        issues.append(PlanIssue(
            ERROR, path,
            f"ramp_delay_s must be >= 0 (got {loop.ramp_delay_s!r})"))
    if loop.axis != Axis.BIAS_V and (
        loop.ramp_step_V is not None or loop.ramp_delay_s is not None
    ):
        issues.append(PlanIssue(
            WARNING, path,
            "ramp_step_V / ramp_delay_s are ignored on a non-bias loop "
            "(only a bias_V loop drives HV ramp shaping)"))


def _check_bias_values(
    vals: list[float], path: str, limits: PlanLimits, issues: list[PlanIssue]
) -> None:
    """(d) |V| within voltage_range_V for every bias set point."""
    limit = abs(float(limits.voltage_range_V))
    over = [v for v in vals if abs(v) > limit]
    if over:
        issues.append(PlanIssue(
            ERROR, path,
            f"{len(over)} bias value(s) exceed voltage_range_V = "
            f"+/-{limit:g} V (extremum {_extreme(over):g} V)"))


def _check_stage_values(
    axis: Axis, vals: list[float], path: str,
    limits: PlanLimits, issues: list[PlanIssue],
) -> None:
    """(c) every stage set point within its software limit."""
    lo, hi = _axis_bounds(axis, limits)
    out = [v for v in vals if not (lo <= v <= hi)]
    if out:
        issues.append(PlanIssue(
            ERROR, path,
            f"{len(out)} {axis.value} set point(s) outside software limits "
            f"[{lo:g}, {hi:g}] mm (extremum {_extreme(out):g} mm)"))


def _check_action_params(
    action: ActionBlock, path: str, issues: list[PlanIssue]
) -> None:
    """(h) WAIT seconds >= 0, ACQUIRE n_averages >= 1; unknown keys → WARNING."""
    params = action.params or {}
    if action.action == ActionType.WAIT:
        secs = params.get("seconds")
        if secs is not None and _is_num(secs) and float(secs) < 0:
            issues.append(PlanIssue(
                ERROR, path, f"WAIT seconds must be >= 0 (got {secs!r})"))
    if action.action == ActionType.ACQUIRE_WAVEFORM:
        navg = params.get("n_averages")
        if navg is not None and _is_num(navg) and int(navg) < 1:
            issues.append(PlanIssue(
                ERROR, path, f"n_averages must be >= 1 (got {navg!r})"))
    if action.action == ActionType.CAPTURE_PHOTO:
        secs = params.get("settle_s")
        if secs is not None and _is_num(secs) and float(secs) < 0:
            issues.append(PlanIssue(
                ERROR, path, f"CAPTURE_PHOTO settle_s must be >= 0 (got {secs!r})"))

    known = _KNOWN_ACTION_PARAMS.get(action.action, frozenset())
    for key in params:
        if key not in known:
            issues.append(PlanIssue(
                WARNING, path,
                f"unknown param '{key}' for {action.action.value} — typo? "
                "It is ignored by the executor."))


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

def _axis_bounds(axis: Axis, limits: PlanLimits) -> tuple[float, float]:
    if axis == Axis.STAGE_X:
        return float(limits.x_min_mm), float(limits.x_max_mm)
    if axis == Axis.STAGE_Y:
        return float(limits.y_min_mm), float(limits.y_max_mm)
    return float(limits.z_min_mm), float(limits.z_max_mm)


def _extreme(vals: list[float]) -> float:
    """The offending value with the largest magnitude (most informative)."""
    return max(vals, key=abs)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)
