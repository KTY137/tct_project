"""
Arm-envelope model for the plan executor's danger gate (design-system law 5 /
DECISIONS 2026-07-12).

The council-ratified "two-step arm" latch authorizes, ONCE per run, a *bounded,
enumerated* envelope of dangerous actions — the bias channel(s), the signed HV
range, the ramp shape, and the per-axis motion bounds the plan will command.
The GUI renders that envelope over the Arm→Execute latch (Noah's later beat);
here we provide the pure, hardware-free pieces the controller and the GUI share:

* :class:`ArmedEnvelope` — the frozen, enumerated authorization (with a real
  human-readable :attr:`~ArmedEnvelope.summary`, DangerAction-style, carrying
  the actual numbers).
* :func:`derive_envelope` / :func:`envelope_from_plan` — build the envelope from
  a compiled plan (bias extremes per channel, motion extents per axis), reusing
  exactly the seams :meth:`ScanController._move_action` and
  :mod:`controller.plan_estimate` already use so the armed bounds are *identical*
  to what the executor will present at run time.
* :class:`ArmedEnvelopeGate` — a :class:`~controller.danger_gate.DangerGate`
  armed once with an envelope: it AUTO-APPROVES any live :class:`DangerAction`
  provably inside the envelope and DENIES (fail-closed, returns ``False``)
  anything outside it — wrong channel, out-of-range HV, out-of-bounds / un-armed
  motion, or an un-enumerated danger kind.  A deny is a clean return value, so
  the executor treats it exactly like a user deny today (abort + fail-safe).
  The gate is set-membership law at RUN TIME; it does NOT re-check expiry per
  ramp — a stale arm is refused LOUDLY once, at :meth:`ScanController.start_plan`
  (arm→start), never silently mid-run (arm→every-ramp).  See :meth:`ArmedEnvelope.is_expired`.

This module is pure: no Qt, no hardware I/O, no threads, no files.  It never
imports a widget or a device backend — the gate only ever inspects a
:class:`DangerAction`'s ``kind`` / ``detail``, which the executor already
populates with the real channel, target voltage and motion envelope.

Fallback discipline (see task brief): the per-action confirm path is unchanged.
An :class:`~controller.danger_gate.AutoConfirmGate` (tests/sim) or a future
per-action GUI dialog gate is still a valid ``DangerGate`` for
:meth:`ScanController.start_plan` — the ArmedEnvelopeGate is an *additional*
gate the GUI chooses to build once the two-step latch exists.  Nothing in the
executor changes; the gate seam is the point.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from controller.danger_gate import DangerAction
from controller.plan_compiler import BiasStep, MoveStep, Step, compile_plan
from controller.scan_plan import ScanPlan

logger = logging.getLogger(__name__)

# Absolute float slop when checking a live value against an armed bound.  The
# envelope is derived from the SAME compiled steps the executor presents, so an
# in-envelope action matches exactly; the epsilon only absorbs float re-derivation
# noise, never widens the authorization in any operationally meaningful way.
_EPS = 1e-6

# Danger kinds this gate understands.  Anything else (a future laser/scan_start
# kind) is DENIED fail-closed — an armed HV/motion envelope never silently
# authorizes a class of danger it does not enumerate.
_KIND_HV = "hv_ramp"
_KIND_MOVE = "move"


@dataclass(frozen=True)
class ArmedEnvelope:
    """One two-step-armed authorization: the full enumerated danger envelope.

    Every field carries REAL numbers derived from the plan, never a generic
    "danger" flag:

    * ``channels`` — the bias-supply channel indices the plan will command
      (empty when the plan drives no HV).
    * ``hv_min_V`` / ``hv_max_V`` — the signed HV range (min/max of the commanded
      set points); both ``None`` when no HV is driven.  A live HV ramp is
      approved iff its channel is armed AND its target is within ``[hv_min_V,
      hv_max_V]`` (inclusive).
    * ``ramp_step_V`` / ``ramp_delay_s`` — the ramp shape the plan requested
      (``None`` == the driver's default shape, or "mixed" across bias loops).
      Carried for the summary / audit; the executor applies each step's own
      shape, so the gate does not re-validate the rate.
    * ``x_bounds`` / ``y_bounds`` / ``z_bounds`` — signed per-axis motion bounds
      in mm, ``(min, max)`` or ``None`` for an axis the plan never drives.  A
      live move is approved iff every driven axis' span lies within the armed
      bound for that axis; a move on an axis the envelope did not authorize is
      DENIED.
    * ``expiry_monotonic`` — an optional ``time.monotonic()`` deadline bounding
      the interval **arm → start** (freshness of the authorization at the moment
      a run is launched), NEVER arm → every-ramp.  It is checked ONCE, fail-
      closed, in :meth:`ScanController.start_plan`'s pre-flight (a stale arm is
      refused LOUDLY where the operator can re-arm), and never again mid-run: a
      run that outlives its expiry keeps ramping the setpoints it was authorized
      for.  This is the same rationale :func:`envelope_from_plans` documents for
      an overnight queue — runtime set-membership re-validation is the safety
      backstop, not a wall-clock that would strand a mid-run ramp.  ``None`` ==
      no expiry (the GUI arm→Execute latch timeout, design law 5, is a separate
      GUI concern — see the module note and the handoff).
    * ``summary`` — the human sentence shown over the Arm latch.
    * ``routine_names`` — the ordered names of the routines this envelope was
      armed over.  Empty ``()`` for a single-plan arm (the historic case);
      non-empty only for a combined SEQUENCE envelope (a routine QUEUE armed
      with ONE envelope, DECISIONS 2026-07-13).  Every name appears in
      ``summary`` — the ratified requirement that the operator sees exactly
      which routines the single hold-3s authorizes.
    """
    channels: frozenset[int]
    hv_min_V: Optional[float]
    hv_max_V: Optional[float]
    ramp_step_V: Optional[float]
    ramp_delay_s: Optional[float]
    x_bounds: Optional[tuple[float, float]]
    y_bounds: Optional[tuple[float, float]]
    z_bounds: Optional[tuple[float, float]]
    expiry_monotonic: Optional[float] = None
    n_bias_setpoints: int = 0
    n_moves: int = 0
    summary: str = ""
    routine_names: tuple[str, ...] = ()

    # -- expiry --------------------------------------------------------------
    def is_expired(self, now: Optional[float] = None) -> bool:
        """True when the armed authorization has lapsed (fail-closed default).

        Consumed ONCE, at :meth:`ScanController.start_plan`'s pre-flight, to
        refuse a stale arm→start loudly.  It is deliberately NOT consulted by
        :meth:`ArmedEnvelopeGate.confirm`: an expiry that bounded every ramp
        would silently abort a run that merely outlived its clock (the exact
        overnight-queue failure :func:`envelope_from_plans` warns against).
        ``expiry_monotonic is None`` (the no-timeout default) never expires."""
        if self.expiry_monotonic is None:
            return False
        return (now if now is not None else time.monotonic()) >= self.expiry_monotonic

    # -- membership predicates (pure) ---------------------------------------
    @property
    def drives_hv(self) -> bool:
        return bool(self.channels) and self.hv_min_V is not None

    def hv_in_range(self, channel: object, target_V: object) -> bool:
        """True iff a live HV ramp is PROVABLY inside the armed HV envelope."""
        if not self.drives_hv:
            return False
        try:
            ch = int(channel)  # type: ignore[arg-type]
            v = float(target_V)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        if ch not in self.channels:
            return False
        assert self.hv_min_V is not None and self.hv_max_V is not None
        return (self.hv_min_V - _EPS) <= v <= (self.hv_max_V + _EPS)

    def _axis_bound(self, axis_key: str) -> Optional[tuple[float, float]]:
        return {"x_mm": self.x_bounds, "y_mm": self.y_bounds,
                "z_mm": self.z_bounds}.get(axis_key)

    def move_in_bounds(self, move_env: object) -> bool:
        """True iff a live move envelope is PROVABLY inside the armed bounds.

        *move_env* is the ``detail['envelope']`` the executor's
        :meth:`ScanController._move_action` builds: ``{"x_mm": (min, max) | None,
        …}``.  A move that drives an axis the envelope did not authorize (armed
        bound ``None``) is DENIED — fail closed.
        """
        if not isinstance(move_env, dict):
            return False
        for axis_key in ("x_mm", "y_mm", "z_mm"):
            span = move_env.get(axis_key)
            if span is None:
                continue
            armed = self._axis_bound(axis_key)
            if armed is None:
                return False  # motion on an un-armed axis
            try:
                lo, hi = float(span[0]), float(span[1])
            except (TypeError, ValueError, IndexError):
                return False
            if lo < armed[0] - _EPS or hi > armed[1] + _EPS:
                return False
        # Every driven axis lay within its armed bound (a move that commands no
        # axis is a harmless no-op and is likewise approved).
        return True


class ArmedEnvelopeGate:
    """A :class:`~controller.danger_gate.DangerGate` armed once with an envelope.

    ``confirm(action)`` returns ``True`` only when *action* is provably inside
    the armed :class:`ArmedEnvelope`; otherwise it returns ``False`` (fail-
    closed).  Set membership is the run-time law — channel, signed HV range,
    per-axis motion bounds, enumerated danger kind — NOT a clock: a stale arm is
    refused once at :meth:`ScanController.start_plan` (arm→start), so ``confirm``
    never re-checks :meth:`ArmedEnvelope.is_expired` (an expiry bounding every
    ramp would silently abort a run that merely outlived its authorization).  A
    ``False`` is a clean return value, so the executor treats an out-of-envelope
    action exactly like a user deny today: :meth:`ScanController._deny_abort`
    sets the abort event, surfaces the reason, runs the HV fail-safe if the run
    energized HV, and the run stops ABORTED.

    ``on_deny`` (optional) is an audit hook ``(action, reason)`` for logging the
    specific breach.  The specific reason of the most recent deny is also kept on
    :attr:`last_deny_reason` — audit-only state that never affects a gate
    decision — so the executor can fold the REAL cause ("outside armed range
    […]") into its operator-facing abort message rather than a generic "not
    confirmed".  The gate never talks to hardware and holds no run-control state.
    """

    def __init__(self, envelope: ArmedEnvelope, on_deny=None) -> None:
        self._env = envelope
        self._on_deny = on_deny
        # Audit-only: the reason of the most recent deny, so the executor can
        # surface the REAL cause in its operator-facing abort message (a plain
        # QtDangerGate has no such attribute — the executor reads it via getattr
        # and falls back to its generic message, fail-safe).  Never consulted by
        # confirm(); never a gate decision input.
        self._last_deny_reason: Optional[str] = None

    @property
    def envelope(self) -> ArmedEnvelope:
        return self._env

    @property
    def last_deny_reason(self) -> Optional[str]:
        """Reason string of the most recent :meth:`confirm` deny, or ``None``."""
        return self._last_deny_reason

    def confirm(self, action: DangerAction) -> bool:
        env = self._env
        # NB: expiry is NOT checked here — a stale arm is refused loudly at
        # start_plan (arm→start), never silently per ramp (arm→every-ramp).
        kind = getattr(action, "kind", None)
        detail = getattr(action, "detail", None) or {}

        if kind == _KIND_HV:
            if env.hv_in_range(detail.get("channel"), detail.get("target_V")):
                return True
            return self._deny(
                action,
                f"HV ramp CH{detail.get('channel')} to "
                f"{detail.get('target_V')} V outside armed range "
                f"[{env.hv_min_V}, {env.hv_max_V}] V on channels "
                f"{sorted(env.channels)}")

        if kind == _KIND_MOVE:
            if env.move_in_bounds(detail.get("envelope")):
                return True
            return self._deny(
                action,
                f"move envelope {detail.get('envelope')} outside armed motion "
                f"bounds x={env.x_bounds} y={env.y_bounds} z={env.z_bounds}")

        # Unknown danger class → fail closed.  An HV/motion arm never authorizes
        # a danger kind it does not enumerate.
        return self._deny(action, f"unknown/un-armed danger kind {kind!r}")

    def _deny(self, action: DangerAction, reason: str) -> bool:
        logger.warning("ArmedEnvelopeGate DENY: %s", reason)
        self._last_deny_reason = reason   # audit-only; read by the executor's message
        if self._on_deny is not None:
            try:
                self._on_deny(action, reason)
            except Exception:  # pragma: no cover - audit hook must never break the gate
                logger.exception("ArmedEnvelopeGate on_deny hook failed")
        return False


# --------------------------------------------------------------------------- #
# Derivation                                                                   #
# --------------------------------------------------------------------------- #

def envelope_from_plan(
    plan: ScanPlan,
    channel: int,
    *,
    timeout_s: Optional[float] = None,
    now: Optional[float] = None,
) -> ArmedEnvelope:
    """Derive the :class:`ArmedEnvelope` for *plan* on bias *channel*.

    Compiles *plan* once (the same ``compile_plan`` the executor uses) and reads
    the bias/motion extremes off the compiled steps, so the armed bounds match
    what the run will present byte-for-byte.  *channel* is the resolved bias
    channel index (``BiasChannel.channel``); the HV envelope is attributed to it.
    """
    return derive_envelope(compile_plan(plan), channel,
                           timeout_s=timeout_s, now=now)


def envelope_from_plans(
    plans: Sequence[ScanPlan],
    channel: int,
    *,
    plan_names: Sequence[str] = (),
    timeout_s: Optional[float] = None,
    now: Optional[float] = None,
) -> ArmedEnvelope:
    """Derive ONE combined :class:`ArmedEnvelope` for a whole routine QUEUE.

    Council-ratified (DECISIONS 2026-07-13): an armed queue carries a SINGLE
    combined envelope — max HV, total travel, every routine named in the arm
    text, one hold-3s for an unattended overnight run — while the executor
    still re-validates every step at run time.  This is the pure derivation of
    that envelope; the queue engine/coordinator arrive in later beats.

    Each plan is compiled with the SAME :func:`compile_plan` the single-plan
    path uses; the compiled step lists are CONCATENATED and fed to the existing
    :func:`derive_envelope`, so the union falls straight out of the existing
    logic: HV ``(min, max)`` = the global extremes across all plans, per-axis
    motion bounds = the global ``(min, max)``, and the setpoint/move counts are
    summed.  Ramp shape follows the same uniform-else-``None`` rule already
    applied within a plan: a uniform shape across every plan is preserved, and
    a mix of shapes collapses to ``None`` ("mixed").  That is safe because the
    gate NEVER re-validates ramp rate — the HV branch of
    :meth:`ArmedEnvelopeGate.confirm` checks only channel + target voltage, and
    the executor applies each step's own shape at run time.

    *plan_names* (optional) names the routines in queue order; when supplied,
    every name is embedded in :attr:`ArmedEnvelope.summary` behind the
    ``Arm SEQUENCE envelope (...)`` prefix (the ratified "operator sees which
    routines the single hold authorizes" requirement).  Left empty, the result
    is an ordinary combined envelope with the plain ``Arm envelope:`` summary.

    *timeout_s* defaults to ``None`` (no expiry) DELIBERATELY: an overnight
    queue must not have a hard wall-clock expiry that would strand a 2 a.m.
    entry mid-run.  Runtime re-validation of every step is the safety backstop,
    not a stale-arm timer.  A GUI-side Arm→Execute latch timeout (design law 5)
    remains a separate concern and can still pass an explicit *timeout_s*.

    Single-channel discipline: every plan must resolve to the given bias
    *channel* (the caller is responsible for that resolution).  A multi-channel
    union is OUT OF SCOPE here — the HV envelope is attributed to the one armed
    *channel*, and the gate stays fail-closed for any un-armed channel.

    Raises :class:`ValueError` on an empty *plans* sequence — fail-closed, so an
    empty queue can never be armed with an empty (vacuously permissive-looking)
    envelope.
    """
    plans = list(plans)
    if not plans:
        raise ValueError(
            "envelope_from_plans requires at least one plan; refusing to arm "
            "an empty routine sequence (fail-closed)."
        )
    all_steps: list[Step] = []
    for plan in plans:
        all_steps.extend(compile_plan(plan))

    env = derive_envelope(all_steps, channel, timeout_s=timeout_s, now=now)

    names = tuple(str(n) for n in plan_names)
    if names:
        # Frozen dataclass: attach the routine names, then rebuild the summary
        # so the SEQUENCE prefix + every routine name appear in the arm text.
        object.__setattr__(env, "routine_names", names)
        object.__setattr__(env, "summary", _summarize(env, timeout_s))
    return env


def derive_envelope(
    steps: Iterable[Step],
    channel: int,
    *,
    timeout_s: Optional[float] = None,
    now: Optional[float] = None,
) -> ArmedEnvelope:
    """Derive the :class:`ArmedEnvelope` from an already-compiled *steps* list.

    HV range = ``(min, max)`` of the ``BiasStep`` target set points on *channel*
    (mirroring :func:`controller.plan_estimate.estimate_plan`'s ``hv_range_V``);
    ramp shape = the loop-requested ``(ramp_step_V, ramp_delay_s)`` when uniform
    across bias steps, else ``None`` (mixed).  Motion bounds = per-axis
    ``(min, max)`` of the non-``None`` ``MoveStep`` coordinates (mirroring
    :meth:`ScanController._move_action`).  Pure; no hardware.
    """
    steps = list(steps)
    bias_steps = [s for s in steps if isinstance(s, BiasStep)]
    move_steps = [s for s in steps if isinstance(s, MoveStep)]

    # -- HV envelope --------------------------------------------------------
    channels: frozenset[int] = frozenset()
    hv_min = hv_max = None
    ramp_step_V = ramp_delay_s = None
    if bias_steps:
        channels = frozenset({int(channel)})
        targets = [float(s.target_V) for s in bias_steps]
        hv_min, hv_max = min(targets), max(targets)
        step_shapes = {s.ramp_step_V for s in bias_steps}
        delay_shapes = {s.ramp_delay_s for s in bias_steps}
        ramp_step_V = next(iter(step_shapes)) if len(step_shapes) == 1 else None
        ramp_delay_s = next(iter(delay_shapes)) if len(delay_shapes) == 1 else None

    # -- motion envelope (per axis; None = un-driven) -----------------------
    acc: dict[str, list[float]] = {"x_mm": [], "y_mm": [], "z_mm": []}
    for m in move_steps:
        for key, val in (("x_mm", m.x_mm), ("y_mm", m.y_mm), ("z_mm", m.z_mm)):
            if val is not None:
                acc[key].append(float(val))
    bounds = {
        key: ((min(vals), max(vals)) if vals else None)
        for key, vals in acc.items()
    }

    expiry = None
    if timeout_s is not None:
        base = now if now is not None else time.monotonic()
        expiry = base + float(timeout_s)

    env = ArmedEnvelope(
        channels=channels,
        hv_min_V=hv_min,
        hv_max_V=hv_max,
        ramp_step_V=ramp_step_V,
        ramp_delay_s=ramp_delay_s,
        x_bounds=bounds["x_mm"],
        y_bounds=bounds["y_mm"],
        z_bounds=bounds["z_mm"],
        expiry_monotonic=expiry,
        n_bias_setpoints=len(bias_steps),
        n_moves=len(move_steps),
    )
    # Frozen dataclass: build the summary against the finished fields, then
    # attach it via object.__setattr__ (still immutable to callers).
    object.__setattr__(env, "summary", _summarize(env, timeout_s))
    return env


def _summarize(env: ArmedEnvelope, timeout_s: Optional[float]) -> str:
    """A DangerAction-style one-liner carrying the REAL numbers (never generic)."""
    parts: list[str] = []
    if env.drives_hv:
        ch_txt = "CH" + "/".join(str(c) for c in sorted(env.channels))
        seg = f"{ch_txt} HV {env.hv_min_V:g}..{env.hv_max_V:g} V"
        if env.ramp_step_V is not None or env.ramp_delay_s is not None:
            step = "default" if env.ramp_step_V is None else f"{env.ramp_step_V:g} V"
            delay = "default" if env.ramp_delay_s is None else f"{env.ramp_delay_s:g} s"
            seg += f" (ramp {step}/{delay})"
        seg += f", {env.n_bias_setpoints} setpoint(s)"
        parts.append(seg)
    else:
        parts.append("no HV")

    motion: list[str] = []
    for axis, key in (("X", "x_bounds"), ("Y", "y_bounds"), ("Z", "z_bounds")):
        span = getattr(env, key)
        if span is not None:
            motion.append(f"{axis} {span[0]:g}..{span[1]:g} mm")
    if motion:
        parts.append("stage " + ", ".join(motion) + f" ({env.n_moves} move(s))")
    else:
        parts.append("no stage motion")

    if timeout_s is not None:
        parts.append(f"valid {timeout_s:g} s")

    body = " | ".join(parts)
    # A combined SEQUENCE envelope names every routine the single hold-3s
    # authorizes (ratified 2026-07-13); a single-plan arm keeps the historic
    # "Arm envelope:" prefix byte-for-byte.
    if env.routine_names:
        names = ", ".join(env.routine_names)
        return (f"Arm SEQUENCE envelope ({len(env.routine_names)} routines: "
                f"{names}): {body}")
    return "Arm envelope: " + body
