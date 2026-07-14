"""
Scan-planner data model — pure data + logic, ZERO hardware I/O.

A :class:`ScanPlan` is a tree of nested loop / action blocks that describes a
measurement *before* any hardware exists.  It is what the dry-run preview walks
and what the (future) executor will drive; nothing here talks to a device, opens
a file, or spawns a thread.

Design notes
------------
* The only loop axes are the members of :class:`Axis` (three stage axes + bias
  voltage).  Laser *power* and *delay* are deliberately NOT axes — there is no PC
  control of them on this setup — so they are expressed as a ``MANUAL_PAUSE``
  action, never a loop.  Anything that is not a known axis/action string is
  rejected at ``from_dict`` time (fail closed: no ``getattr`` / ``eval`` /
  string dispatch).
* Range materialisation derives the sign from ``start`` vs ``stop`` (descending
  sweeps where ``stop < start`` work), computes the count with ``round()`` and
  lays points out with an exact-endpoint formula — never the fragile
  ``arange(start, stop + step/2, step)`` trick, which drops or doubles the last
  point depending on float rounding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator, Union

import yaml


# --------------------------------------------------------------------------- #
# Frozen vocabularies — these are the ONLY valid values.                       #
# --------------------------------------------------------------------------- #

class Axis(str, Enum):
    """The only loop axes.  Laser power/delay are NOT here on purpose."""
    STAGE_X = "stage_x"
    STAGE_Y = "stage_y"
    STAGE_Z = "stage_z"
    BIAS_V = "bias_V"


class ActionType(str, Enum):
    """The only leaf actions a plan may request.

    ``CAPTURE_PHOTO`` grabs one camera frame at the current point (feeds the
    survey/mosaic feature).  Its ``ActionBlock.params`` are ``settle_s`` (float,
    seconds to dwell before the grab so the stage stops ringing; default 0.0)
    and ``label`` (str, a human tag carried through to the executor; default
    "").  A camera grab is passive — it drives no HV and no motion — so it is
    deliberately NOT a danger step (see ``plan_compiler.CapturePhotoStep``).
    """
    ACQUIRE_WAVEFORM = "acquire_waveform"
    SAVE_POINT = "save_point"
    WAIT = "wait"
    MANUAL_PAUSE = "manual_pause"
    READ_SLOW_CONTROL = "read_slow_control"
    CAPTURE_PHOTO = "capture_photo"


STAGE_AXES: frozenset[Axis] = frozenset(
    {Axis.STAGE_X, Axis.STAGE_Y, Axis.STAGE_Z}
)


def axis_from_str(name: object) -> Axis:
    """Map a string to an :class:`Axis`, failing CLOSED on anything unknown.

    Raises a clear ``ValueError`` — no ``getattr``, no ``eval``, no dispatch on
    arbitrary attribute names.  ``laser_power`` / ``delay`` land here and are
    rejected, because they are not PC-controllable axes on this setup.
    """
    if isinstance(name, Axis):
        return name
    try:
        return Axis(str(name))
    except ValueError:
        valid = ", ".join(a.value for a in Axis)
        raise ValueError(
            f"Unknown scan axis {name!r}. Valid loop axes are: {valid}. "
            "Laser power and delay are not controllable axes on this setup — "
            "express them as a MANUAL_PAUSE action, not a loop."
        ) from None


def action_from_str(name: object) -> ActionType:
    """Map a string to an :class:`ActionType`, failing CLOSED on anything unknown."""
    if isinstance(name, ActionType):
        return name
    try:
        return ActionType(str(name))
    except ValueError:
        valid = ", ".join(a.value for a in ActionType)
        raise ValueError(
            f"Unknown scan action {name!r}. Valid actions are: {valid}."
        ) from None


# --------------------------------------------------------------------------- #
# Blocks                                                                       #
# --------------------------------------------------------------------------- #

class ScanBlock:
    """Marker base for the two block kinds (:class:`LoopBlock`, :class:`ActionBlock`)."""

    def to_dict(self) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    @staticmethod
    def from_dict(d: dict) -> "ScanBlock":
        """Dispatch on the ``type`` tag; fail closed on anything else."""
        if not isinstance(d, dict):
            raise ValueError(f"Scan block must be a mapping, got {type(d).__name__}")
        kind = d.get("type")
        if kind == "loop":
            return LoopBlock.from_dict(d)
        if kind == "action":
            return ActionBlock.from_dict(d)
        raise ValueError(
            f"Unknown scan block type {kind!r}; expected 'loop' or 'action'."
        )


@dataclass
class LoopBlock(ScanBlock):
    """A loop over one :class:`Axis`.

    Values come from either an explicit ``values`` list OR a ``start/stop/step``
    range (range wins only when ``values is None``).  ``children`` are the blocks
    executed once per value of this loop.
    """
    axis: Axis
    values: list[float] | None = None
    start: float | None = None
    stop: float | None = None
    step: float | None = None
    settle_s: float = 0.0
    n_averages: int | None = None
    snake: bool = False
    reduce: str | None = None            # e.g. "max_gradient"; represented, not executed
    # Per-bias-step HV ramp shaping (BIAS_V loops ONLY — ignored on stage axes).
    # Both None (the default) means "use the driver's default ramp shape", which
    # is byte-for-byte the historic plan-executor behaviour; a set value shapes
    # the HV ramp (magnitude / per-step delay) the executor applies at each
    # BiasStep.  ``ramp_step_V`` is a magnitude (> 0); ``ramp_delay_s`` is the
    # per-step dwell (>= 0).  Validated by scan_plan_validator.
    ramp_step_V: float | None = None
    ramp_delay_s: float | None = None
    children: list[ScanBlock] = field(default_factory=list)

    def materialize(self) -> list[float]:
        """Return the concrete axis values, sign derived from start→stop.

        Explicit ``values`` are used verbatim.  For a range, the interval count
        is ``round(|stop - start| / |step|)`` and points are laid out from
        ``start`` toward ``stop`` with an exact final endpoint, so both ascending
        (``stop > start``) and descending (``stop < start``) sweeps are correct.
        """
        if self.values is not None:
            return [float(v) for v in self.values]

        if self.start is None or self.stop is None or self.step is None:
            raise ValueError(
                f"LoopBlock[{_axis_name(self.axis)}] needs either 'values' or "
                "all of start/stop/step."
            )

        start = float(self.start)
        stop = float(self.stop)
        step = abs(float(self.step))
        if step == 0.0:
            raise ValueError(
                f"LoopBlock[{_axis_name(self.axis)}] step must be non-zero."
            )

        span = stop - start
        n_intervals = int(round(abs(span) / step))
        if n_intervals == 0:
            return [start]

        sign = 1.0 if stop >= start else -1.0
        # Exact endpoints for both directions: compute each point as
        # start + sign*i*step (no float accumulation), and pin the last point.
        vals = [start + sign * i * step for i in range(n_intervals + 1)]
        vals[-1] = start + sign * n_intervals * step
        return [float(v) for v in vals]

    def value_count(self) -> int:
        """``len(self.materialize())`` computed in O(1) — WITHOUT allocating.

        The size counterpart of :meth:`materialize`: an ultra-wide range (e.g.
        ``start=-1e6, stop=1e6, step=1e-3`` ≈ 2e9 values, all within the planner
        spinbox ranges) can be SIZED here without ever building the multi-GB
        list, which is what lets the validator / estimator pre-gate a
        loop-SHAPE explosion (the sibling of a deeply-nested one).

        It mirrors :meth:`materialize`'s rules EXACTLY, so
        ``value_count() == len(materialize())`` for every input (pinned by a
        property test):

        * explicit ``values`` → ``len(values)``;
        * a range → ``n_intervals + 1`` with
          ``n_intervals = int(round(|stop - start| / |step|))`` — the identical
          float arithmetic and banker's-rounding ``round`` materialize uses,
          including the zero-span case (``n_intervals == 0`` → materialize
          returns ``[start]``, length 1 = 0 + 1);
        * the SAME :class:`ValueError` as materialize for missing fields / a
          zero step, so an invalid loop is reported by the normal flow and never
          silently counted (an invalid range never allocates — materialize
          raises before building its list).
        """
        if self.values is not None:
            return len(self.values)
        if self.start is None or self.stop is None or self.step is None:
            raise ValueError(
                f"LoopBlock[{_axis_name(self.axis)}] needs either 'values' or "
                "all of start/stop/step."
            )
        step = abs(float(self.step))
        if step == 0.0:
            raise ValueError(
                f"LoopBlock[{_axis_name(self.axis)}] step must be non-zero."
            )
        span = abs(float(self.stop) - float(self.start))
        n_intervals = int(round(span / step))
        return n_intervals + 1

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        d: dict = {"type": "loop", "axis": self.axis.value}
        if self.values is not None:
            d["values"] = [float(v) for v in self.values]
        else:
            d["start"] = self.start
            d["stop"] = self.stop
            d["step"] = self.step
        d["settle_s"] = self.settle_s
        d["n_averages"] = self.n_averages
        d["snake"] = self.snake
        d["reduce"] = self.reduce
        # Only serialise ramp shaping when actually set, so a loop that requests
        # no shaping (the overwhelming majority, incl. every stage loop) stays
        # byte-identical to the pre-shaping serialisation.
        if self.ramp_step_V is not None:
            d["ramp_step_V"] = self.ramp_step_V
        if self.ramp_delay_s is not None:
            d["ramp_delay_s"] = self.ramp_delay_s
        d["children"] = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "LoopBlock":
        return cls(
            axis=axis_from_str(d["axis"]),
            values=(None if d.get("values") is None
                    else [float(v) for v in d["values"]]),
            start=_opt_float(d.get("start")),
            stop=_opt_float(d.get("stop")),
            step=_opt_float(d.get("step")),
            settle_s=float(d.get("settle_s", 0.0)),
            n_averages=(None if d.get("n_averages") is None
                        else int(d["n_averages"])),
            snake=bool(d.get("snake", False)),
            reduce=d.get("reduce"),
            ramp_step_V=_opt_float(d.get("ramp_step_V")),
            ramp_delay_s=_opt_float(d.get("ramp_delay_s")),
            children=[ScanBlock.from_dict(c) for c in (d.get("children") or [])],
        )


@dataclass
class ActionBlock(ScanBlock):
    """A leaf action executed at the current loop coordinate."""
    action: ActionType
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": "action", "action": self.action.value,
                "params": dict(self.params)}

    @classmethod
    def from_dict(cls, d: dict) -> "ActionBlock":
        return cls(action=action_from_str(d["action"]),
                   params=dict(d.get("params") or {}))


@dataclass(frozen=True)
class LeafMeta:
    """Effective loop context carried to each leaf action.

    Fields are resolved by :meth:`ScanPlan.iter_leaf_contexts_ex` to the value of
    the *nearest enclosing loop that sets the field*, else the model default.
    They are LOOP-derived only: an action's own ``params`` (e.g.
    ``ACQUIRE_WAVEFORM``'s ``params['n_averages']``) override them downstream, in
    the compiler — not here.

    * ``n_averages`` — default 1; a loop contributes it when ``n_averages`` is
      not None (matching ``LoopBlock.n_averages: int | None = None``).
    * ``settle_s`` — default 0.0; a loop contributes it when ``settle_s > 0``.
      ``LoopBlock.settle_s`` has no unset sentinel, so 0.0 means "no settle".
    * ``bias_ramp_step_V`` / ``bias_ramp_delay_s`` — HV ramp shaping resolved to
      the nearest enclosing ``BIAS_V`` loop that sets the field, else None
      (= "use the driver's default ramp shape").  Only a ``BIAS_V`` loop
      contributes them — ramp shaping on a stage loop is meaningless and never
      folded (the validator warns about it).  The compiler stamps them onto each
      emitted ``BiasStep`` so a plan-driven HV change ramps shaped.
    """
    n_averages: int = 1
    settle_s: float = 0.0
    bias_ramp_step_V: float | None = None
    bias_ramp_delay_s: float | None = None


# --------------------------------------------------------------------------- #
# Plan                                                                         #
# --------------------------------------------------------------------------- #

@dataclass
class ScanPlan:
    """A complete, hardware-free description of a scan.

    ``safety`` carries plan-level guardrails consumed by the validator / executor
    (e.g. ``{"limits": {...}, "dry_run_required": True,
    "require_hv_confirmation": True}``).
    """
    name: str = ""
    description: str = ""
    root: list[ScanBlock] = field(default_factory=list)
    safety: dict = field(default_factory=dict)

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "root": [b.to_dict() for b in self.root],
            "safety": dict(self.safety),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScanPlan":
        if not isinstance(d, dict):
            raise ValueError("ScanPlan.from_dict expects a mapping.")
        return cls(
            name=str(d.get("name", "")),
            description=str(d.get("description", "")),
            root=[ScanBlock.from_dict(b) for b in (d.get("root") or [])],
            safety=dict(d.get("safety") or {}),
        )

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "ScanPlan":
        return cls.from_dict(yaml.safe_load(text))

    def save_yaml(self, path: str | Path) -> None:
        Path(path).write_text(self.to_yaml(), encoding="utf-8")

    @classmethod
    def load_yaml(cls, path: str | Path) -> "ScanPlan":
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))

    # -- pure traversal ----------------------------------------------------
    def total_leaf_visits(self) -> int:
        """Number of action executions across every loop iteration.

        This is the quantity the validator caps against ``max_points`` — with
        two actions per point (acquire + save) it is twice the grid size.
        """
        return _count_leaves(self.root)

    def total_points(self) -> int:
        """Number of distinct loop-coordinate grid points (actions sharing a
        coordinate count once)."""
        return _count_points(self.root)

    def structural_leaf_visit_bound(self) -> int:
        """``total_leaf_visits()`` computed in O(#blocks) WITHOUT allocating.

        Identical value to :meth:`total_leaf_visits` for any valid plan, but it
        uses :meth:`LoopBlock.value_count` (pure arithmetic) in place of
        ``len(materialize())``, so an ultra-wide range loop is SIZED without
        allocating its value list.  This is the pre-gate the validator and the
        estimator call FIRST, so a loop-shape (or nesting) explosion is rejected
        before any ``materialize()`` / walk allocation.  Raises
        :class:`ValueError` (like ``materialize``) if a loop range is invalid —
        callers fall back to their normal flow, which reports that range error.
        """
        return _count_leaf_bound(self.root)

    def structural_point_bound(self) -> int:
        """``total_points()`` computed in O(#blocks) WITHOUT allocating.

        The point-count analogue of :meth:`structural_leaf_visit_bound` (uses
        :meth:`LoopBlock.value_count`), so the estimator can report an honest
        structural point count on a too-large plan without materializing the
        very loop it is refusing to size."""
        return _count_point_bound(self.root)

    def iter_leaf_contexts(self) -> Iterator[tuple[dict, ActionBlock]]:
        """Yield ``(loop_values, action)`` for every action, in execution order.

        Back-compat 2-tuple view of :meth:`iter_leaf_contexts_ex` (drops the
        per-leaf :class:`LeafMeta`).  ``loop_values`` maps axis-value strings
        (e.g. ``"stage_x"``) to the current coordinate.  Serpentine (``snake``)
        loops reverse on alternate entries; ordering only — counts are
        unaffected.  Pure value generation, no hardware.
        """
        for coords, action, _meta in self.iter_leaf_contexts_ex():
            yield coords, action

    def iter_leaf_contexts_ex(
        self,
    ) -> Iterator[tuple[dict, ActionBlock, LeafMeta]]:
        """Yield ``(loop_values, action, meta)`` for every action, in order.

        Like :meth:`iter_leaf_contexts` but also carries the effective loop
        context (:class:`LeafMeta`: ``n_averages`` / ``settle_s`` resolved to the
        nearest enclosing loop that sets each field, else the default).  The
        compiler consumes ``meta`` so a loop-level ``n_averages`` / ``settle_s``
        is honoured instead of silently dropped.  Pure; no hardware.
        """
        yield from _iter_blocks_ex(self.root, {}, LeafMeta(), {})


# --------------------------------------------------------------------------- #
# Traversal internals                                                          #
# --------------------------------------------------------------------------- #

def _count_leaves(blocks: list[ScanBlock]) -> int:
    total = 0
    for b in blocks:
        if isinstance(b, LoopBlock):
            total += len(b.materialize()) * _count_leaves(b.children)
        elif isinstance(b, ActionBlock):
            total += 1
    return total


def _count_points(blocks: list[ScanBlock]) -> int:
    # A "point" = one distinct loop coordinate at which any action runs.
    has_action = any(isinstance(b, ActionBlock) for b in blocks)
    total = 1 if has_action else 0
    for b in blocks:
        if isinstance(b, LoopBlock):
            total += len(b.materialize()) * _count_points(b.children)
    return total


# Allocation-free twins of the two counters above: identical arithmetic, but
# LoopBlock.value_count() (O(1)) replaces len(b.materialize()) (O(n) + a full
# list), so a plan is SIZED without ever building a loop's value list.  Python
# ints are unbounded, so the multiplication never overflows (never float).
def _count_leaf_bound(blocks: list[ScanBlock]) -> int:
    total = 0
    for b in blocks:
        if isinstance(b, LoopBlock):
            total += b.value_count() * _count_leaf_bound(b.children)
        elif isinstance(b, ActionBlock):
            total += 1
    return total


def _count_point_bound(blocks: list[ScanBlock]) -> int:
    has_action = any(isinstance(b, ActionBlock) for b in blocks)
    total = 1 if has_action else 0
    for b in blocks:
        if isinstance(b, LoopBlock):
            total += b.value_count() * _count_point_bound(b.children)
    return total


def _iter_blocks_ex(
    blocks: list[ScanBlock],
    ctx: dict,
    meta: LeafMeta,
    visit_counts: dict,
) -> Iterator[tuple[dict, ActionBlock, LeafMeta]]:
    for b in blocks:
        if isinstance(b, LoopBlock):
            vals = b.materialize()
            n = visit_counts.get(id(b), 0)
            visit_counts[id(b)] = n + 1
            if b.snake and (n % 2 == 1):
                vals = list(reversed(vals))
            child_meta = _child_meta(meta, b)
            for v in vals:
                child_ctx = {**ctx, b.axis.value: float(v)}
                yield from _iter_blocks_ex(b.children, child_ctx, child_meta,
                                           visit_counts)
        elif isinstance(b, ActionBlock):
            yield dict(ctx), b, meta


def _child_meta(meta: LeafMeta, loop: LoopBlock) -> LeafMeta:
    """Fold *loop*'s effective settings onto *meta* (nearest-set-wins).

    ``n_averages`` is inherited when the loop leaves it None; ``settle_s`` is
    inherited when the loop's value is not positive (0.0 == "no settle" — the
    dataclass has no unset sentinel).  HV ramp shaping is inherited unless *loop*
    is a ``BIAS_V`` loop that sets the field (only a bias loop drives HV, so a
    stage loop never contributes ramp shaping).  Pure and fail-closed: no
    getattr/eval.
    """
    n_avg = meta.n_averages if loop.n_averages is None else int(loop.n_averages)
    loop_settle = float(loop.settle_s)
    settle = loop_settle if loop_settle > 0.0 else meta.settle_s

    ramp_step = meta.bias_ramp_step_V
    ramp_delay = meta.bias_ramp_delay_s
    if loop.axis == Axis.BIAS_V:
        if loop.ramp_step_V is not None:
            ramp_step = float(loop.ramp_step_V)
        if loop.ramp_delay_s is not None:
            ramp_delay = float(loop.ramp_delay_s)

    return LeafMeta(
        n_averages=n_avg,
        settle_s=settle,
        bias_ramp_step_V=ramp_step,
        bias_ramp_delay_s=ramp_delay,
    )


# --------------------------------------------------------------------------- #
# small helpers                                                                #
# --------------------------------------------------------------------------- #

def _opt_float(v: object) -> float | None:
    return None if v is None else float(v)


def _axis_name(axis: object) -> str:
    return axis.value if isinstance(axis, Axis) else str(axis)


# Public alias so callers can spell the union in type hints.
ScanBlockT = Union[LoopBlock, ActionBlock]
