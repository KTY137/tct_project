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
    """The only leaf actions a plan may request."""
    ACQUIRE_WAVEFORM = "acquire_waveform"
    SAVE_POINT = "save_point"
    WAIT = "wait"
    MANUAL_PAUSE = "manual_pause"
    READ_SLOW_CONTROL = "read_slow_control"


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

    def iter_leaf_contexts(self) -> Iterator[tuple[dict, ActionBlock]]:
        """Yield ``(loop_values, action)`` for every action, in execution order.

        ``loop_values`` maps axis-value strings (e.g. ``"stage_x"``) to the
        current coordinate.  Serpentine (``snake``) loops reverse on alternate
        entries; ordering only — counts are unaffected.  Pure value generation,
        no hardware.
        """
        yield from _iter_blocks(self.root, {}, {})


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


def _iter_blocks(
    blocks: list[ScanBlock],
    ctx: dict,
    visit_counts: dict,
) -> Iterator[tuple[dict, ActionBlock]]:
    for b in blocks:
        if isinstance(b, LoopBlock):
            vals = b.materialize()
            n = visit_counts.get(id(b), 0)
            visit_counts[id(b)] = n + 1
            if b.snake and (n % 2 == 1):
                vals = list(reversed(vals))
            for v in vals:
                child_ctx = {**ctx, b.axis.value: float(v)}
                yield from _iter_blocks(b.children, child_ctx, visit_counts)
        elif isinstance(b, ActionBlock):
            yield dict(ctx), b


# --------------------------------------------------------------------------- #
# small helpers                                                                #
# --------------------------------------------------------------------------- #

def _opt_float(v: object) -> float | None:
    return None if v is None else float(v)


def _axis_name(axis: object) -> str:
    return axis.value if isinstance(axis, Axis) else str(axis)


# Public alias so callers can spell the union in type hints.
ScanBlockT = Union[LoopBlock, ActionBlock]
