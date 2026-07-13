"""
Plan *compiler*: flatten a :class:`~controller.scan_plan.ScanPlan` tree into a
linear list of :class:`Step` records.

This module is a **pure translation layer** — it produces the ordered step list
that a (future) executor will drive.  It performs NO execution: no threads, no
hardware, no files, no sleeps.  It does not import Qt or any device backend.

The compiler is the single place that turns nested loop coordinates into
concrete motion/bias/acquire steps, applying the "emit-on-change" rule:

* a :class:`MoveStep` is emitted only when a *driven* stage axis actually
  changes (axes the plan never drives stay ``None`` — "do not command" — and are
  never fabricated as 0.0),
* a :class:`BiasStep` is emitted only when the bias set point actually changes,

so serpentine (``snake``) ordering naturally produces fewer/shorter moves — the
saving is visible in the compiled list and therefore in the estimate.

Ordering convention at a leaf where several things change: **BiasStep, then
MoveStep, then a settle :class:`WaitStep`, then the action step(s)** — matching
the executor's real ``move -> settle -> acquire`` sequence.  Bias is, by
convention, the outer/slower axis (you set the HV regime, then position within
it), so the HV set point is established first.  The executor (a later step) owns
whether/how to gate these danger steps on confirmation — the compiler only
*marks* them (``requires_confirm=True``, ``danger_kind``).

Effective ``n_averages`` / ``settle_s`` come from :class:`LeafMeta` (the nearest
enclosing loop that sets each field, else the model default), with an action's
own ``params`` overriding for ``n_averages``.  The plan is the single source of
truth for settle timing; the estimate reads the emitted settle ``WaitStep``s
rather than applying its own per-move settle.

Dispatch on :class:`~controller.scan_plan.ActionType` is an explicit if/elif —
never getattr / eval / string dispatch (fail closed on anything unknown).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from controller.scan_plan import ActionType, LeafMeta, ScanPlan


# --------------------------------------------------------------------------- #
# Step records — frozen, hardware-free descriptions of one executor action.    #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MoveStep:
    """Absolute stage move.

    Each axis is either a target coordinate in mm or ``None``.  ``None`` means
    "do not command this axis" — the plan never drives it, so the executor must
    leave it where it is.  Undriven axes are NEVER fabricated as 0.0 (that would
    silently drive a stage to the hard-stop edge in the shipped config).

    ``requires_confirm`` / ``danger_kind`` mark this as a motion step the
    executor must gate behind explicit user confirmation.
    """
    x_mm: float | None = None
    y_mm: float | None = None
    z_mm: float | None = None
    requires_confirm: bool = True
    danger_kind: str = "move"


@dataclass(frozen=True)
class BiasStep:
    """Ramp the bias supply to ``target_V``.

    Marked as an HV-ramp danger step — the executor gates it on confirmation.

    ``ramp_step_V`` / ``ramp_delay_s`` carry optional HV ramp shaping resolved
    from the enclosing ``BIAS_V`` loop (see :class:`LeafMeta`).  Both None (the
    default) means "use the driver's default ramp shape" — byte-for-byte the
    historic behaviour; a set value shapes the ramp the executor applies.  HV
    never steps unshaped when shaping is requested.
    """
    target_V: float
    requires_confirm: bool = True
    danger_kind: str = "hv_ramp"
    ramp_step_V: float | None = None
    ramp_delay_s: float | None = None


@dataclass(frozen=True)
class AcquireStep:
    """Acquire (and average) a waveform.  Wavegen settings ride in ``params``."""
    n_averages: int
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SaveStep:
    """Persist the current point (waveform + coordinate + scalars)."""


@dataclass(frozen=True)
class WaitStep:
    seconds: float


@dataclass(frozen=True)
class ManualPauseStep:
    """Block for a human action (e.g. change laser power) — no PC control."""
    prompt: str


@dataclass(frozen=True)
class ReadSlowControlStep:
    """Sample slow-control sensors (temperature, humidity, …)."""


@dataclass(frozen=True)
class CapturePhotoStep:
    """Grab one camera frame at the current point (survey/mosaic feature).

    ``settle_s`` is a pre-grab dwell (>= 0) so the stage stops ringing before
    the frame is taken; ``label`` is a human tag carried through for provenance.

    Deliberately NOT danger-marked — a camera grab is passive (it drives no HV
    and commands no motion), so unlike :class:`MoveStep` / :class:`BiasStep` it
    carries no ``requires_confirm`` / ``danger_kind`` and is never gated through
    the danger confirmation.  The executor persists the frame straight to the
    writer's ``/camera`` group tagged with the current point index (it does NOT
    route through ``save_point``, which would write a full — and, for a
    photo-only capture, empty — waveforms/points row).
    """
    settle_s: float = 0.0
    label: str = ""


# --------------------------------------------------------------------------- #
# Compiler                                                                     #
# --------------------------------------------------------------------------- #

def compile_plan(plan: ScanPlan) -> list[Step]:
    """Flatten *plan* into an ordered list of :class:`Step` records.

    Walks :meth:`ScanPlan.iter_leaf_contexts_ex` (which handles snake ordering
    and carries the effective :class:`LeafMeta`), tracking the current
    coordinate and bias so a move/bias step is only emitted when something
    changes.  A move only fires when a *driven* axis changes; undriven axes are
    emitted as ``None``.  After a move, a settle :class:`WaitStep` is emitted
    when the effective ``settle_s`` is positive.  Assumes *plan* is already valid
    — run :func:`controller.scan_plan_validator.validate_plan` first; a broken
    loop range will surface here as the ValueError that ``materialize`` raises.
    """
    steps: list[Step] = []
    cur_x: float | None = None
    cur_y: float | None = None
    cur_z: float | None = None
    cur_bias: float | None = None

    # One frozen params snapshot PER LEAF (not per leaf *visit*) — see
    # _snapshot_params.  Deliberately a call-LOCAL dict: it is keyed on
    # id(action), and an id is only unique while its object is alive.  The plan
    # (and therefore every ActionBlock in it) is alive for the whole call, so
    # the keys cannot collide here; a module-level cache could hand a later
    # compile a stale snapshot under a recycled id.  Local also means each
    # compile_plan() call re-reads the live plan — an edit between two compiles
    # is picked up, exactly as before.
    param_snapshots: dict[int, dict] = {}

    for ctx, action, meta in plan.iter_leaf_contexts_ex():
        # --- bias first (outer regime), only on change ---------------------
        if "bias_V" in ctx:
            target = float(ctx["bias_V"])
            if target != cur_bias:
                # Stamp the enclosing BIAS_V loop's ramp shaping (None = the
                # driver's default shape) so a plan-driven HV change ramps
                # shaped; absent shaping stays byte-identical to the historic
                # BiasStep(target_V=...).
                steps.append(BiasStep(
                    target_V=target,
                    ramp_step_V=meta.bias_ramp_step_V,
                    ramp_delay_s=meta.bias_ramp_delay_s,
                ))
                cur_bias = target

        # --- then position, only when a DRIVEN axis changes ----------------
        # Undriven axes stay None ("do not command"); never fabricated as 0.0.
        tx = ctx.get("stage_x")
        ty = ctx.get("stage_y")
        tz = ctx.get("stage_z")
        moved = (
            ("stage_x" in ctx and tx != cur_x)
            or ("stage_y" in ctx and ty != cur_y)
            or ("stage_z" in ctx and tz != cur_z)
        )
        if moved:
            steps.append(MoveStep(x_mm=tx, y_mm=ty, z_mm=tz))
            if "stage_x" in ctx:
                cur_x = tx
            if "stage_y" in ctx:
                cur_y = ty
            if "stage_z" in ctx:
                cur_z = tz
            # settle after the move (move -> settle -> acquire), plan-driven.
            if meta.settle_s > 0.0:
                steps.append(WaitStep(seconds=meta.settle_s))

        # --- then the leaf action (explicit dispatch, fail closed) ---------
        at = action.action
        params = action.params or {}
        if at == ActionType.ACQUIRE_WAVEFORM:
            steps.append(AcquireStep(
                n_averages=_effective_n_averages(params, meta),
                # Deep-copied ONCE per leaf, then reused for every visit of that
                # leaf — the snapshot never aliases the live plan (see
                # _snapshot_params for why sharing it across visits is safe).
                params=_snapshot_params(action, params, param_snapshots),
            ))
        elif at == ActionType.SAVE_POINT:
            steps.append(SaveStep())
        elif at == ActionType.WAIT:
            steps.append(WaitStep(seconds=float(params.get("seconds", 0.0))))
        elif at == ActionType.MANUAL_PAUSE:
            steps.append(ManualPauseStep(prompt=_prompt(params)))
        elif at == ActionType.READ_SLOW_CONTROL:
            steps.append(ReadSlowControlStep())
        elif at == ActionType.CAPTURE_PHOTO:
            steps.append(CapturePhotoStep(
                settle_s=float(params.get("settle_s", 0.0)),
                label=str(params.get("label", "")),
            ))
        else:  # pragma: no cover - ActionType is a closed enum
            raise ValueError(f"unhandled action type: {at!r}")

    return steps


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

def _snapshot_params(action, params: dict, memo: dict[int, dict]) -> dict:
    """Return the frozen deep-copied ``params`` snapshot for *action*.

    **Why a deep copy at all** (the property this must preserve): a shallow
    ``dict(params)`` would leave the nested ``'wavegen'`` mapping shared with the
    live plan object, so a post-validation mutation of
    ``plan.root[...].params['wavegen']`` would silently change the values the
    executor commands to hardware — with no re-validation.  The snapshot is
    therefore still a real :func:`copy.deepcopy` taken from the live plan.

    **Why once per leaf, not once per leaf VISIT** (the perf fix): a leaf inside
    an N-point loop nest is visited N times, and the old code deep-copied on
    every visit.  On a 90k-acquire plan that is ~0.65 s of pure deepcopy, paid on
    the GUI thread (``compile_plan`` runs inside
    ``ScanController.start_plan``), and ``PlanLimits.max_points`` legally admits
    250k visits.  One copy per leaf makes the cost proportional to the plan
    *text*, not to the grid size.

    **Why sharing one snapshot across visits is safe:** nothing mutates
    ``Step.params`` after compile (the executor only reads it — ``.get`` /
    membership), and no code compares step params by identity, so two
    :class:`AcquireStep`\\ s from the same leaf sharing one dict cannot alias the
    LIVE plan — which is the only property the deep copy exists to guarantee.
    If a future consumer ever wants to *write* to ``step.params``, it must copy
    first (or this memo must go).

    *memo* must be local to a single :func:`compile_plan` call: ``id()`` is only
    unique among live objects, and only the in-flight plan is guaranteed alive.
    """
    key = id(action)
    snap = memo.get(key)
    if snap is None:
        snap = copy.deepcopy(params)
        memo[key] = snap
    return snap


def _effective_n_averages(params: dict, meta: LeafMeta) -> int:
    """Effective averages for an acquire: action param overrides loop context.

    Precedence (per the effective-value rule): action ``params['n_averages']`` >
    nearest enclosing loop (``meta.n_averages``) > default (1).  A malformed
    action override falls back to the loop-effective value.  Clamped to >= 1.
    """
    raw = params.get("n_averages", meta.n_averages)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = meta.n_averages
    return n if n >= 1 else 1


def _prompt(params: dict) -> str:
    return str(params.get("prompt") or params.get("message") or "")


# Public union alias so callers can spell the step type in hints.
Step = (
    MoveStep | BiasStep | AcquireStep | SaveStep
    | WaitStep | ManualPauseStep | ReadSlowControlStep | CapturePhotoStep
)
