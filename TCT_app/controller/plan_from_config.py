"""
Pure converter: classic quick-scan configs → :class:`~controller.scan_plan.ScanPlan`.

This is the bridge that lets the GUI offer **"Open in Planner"**: the Scan panel
stays the quick-scan surface, and this module turns its ``ScanConfig`` /
``VoltageScanConfig`` into the equivalent :class:`ScanPlan` tree that the Planner
edits and the executor drives.

It is **pure**: it imports only the plan data model (:mod:`controller.scan_plan`),
never Qt, never a device backend, never :mod:`controller.scan_controller` at
runtime (the config dataclasses are referenced only for type hints under
``TYPE_CHECKING`` — the functions read attributes duck-typed, so importing this
module pulls in nothing heavy).

Faithfulness contract
---------------------
The emitted plan reproduces the classic scan the config describes:

* **XY raster** (:func:`plan_from_scan_config`) — a fixed-Z single-value loop
  wrapping an X loop (outer) wrapping a snake Y loop (inner), whose leaves are
  ``ACQUIRE_WAVEFORM`` + ``SAVE_POINT``.  The snake (boustrophedon) ordering and
  the per-axis point counts match ``scan_controller._build_scan_points`` for
  every ascending range (verified in the tests).  The XY scan **holds** bias — it
  drives none — so no bias loop is emitted and ``require_hv_confirmation`` is NOT
  set (a bias-driving flag would be a lie; the validator agrees a
  ``bias_channel``-only plan needs no HV confirmation).
* **IV / CCE sweep** (:func:`plan_from_voltage_scan_config`) — single-value X/Y/Z
  loops (fix the position) wrapping a BIAS_V loop wrapping ``ACQUIRE_WAVEFORM`` +
  ``SAVE_POINT`` (with an optional per-step settle ``WAIT`` for ``hold_delay_s``).
  Because it *drives* HV, ``safety`` carries ``require_hv_confirmation = True``
  (fail-closed — the validator refuses a bias-driving plan without it).

Both converters are deterministic and eagerly validate their range loops by
calling :meth:`LoopBlock.materialize`, so a nonsensical range (e.g. zero step
between distinct endpoints) raises the model's own ``ValueError`` at conversion
time rather than surfacing later in the compiler.

Divergences from the classic path (documented, intentional)
----------------------------------------------------------
* **Descending XY ranges** (``start > stop`` with the shipped positive step):
  the classic ``_build_scan_points`` uses ``np.arange`` with a positive step, so
  it yields an *empty* scan (a silent footgun).  The plan model's ``materialize``
  derives the sign from ``start → stop`` and produces a proper descending sweep,
  so the converter follows the model — it emits the sweep the operator clearly
  intended instead of nothing.  (The vscan already used a direction-aware step,
  so it matches ``materialize`` in both directions.)
* **Zero bias step** (``v_step_V == 0``): the classic voltage scan silently
  defaults the magnitude to 10 V.  The converter instead follows the plan model
  and *raises* — fail-closed for HV: an ambiguous bias step is refused, not
  guessed.
* **Bias ramp shaping** (``ramp_step_V`` / ``ramp_delay_s``): carried onto the
  emitted ``BIAS_V`` loop (``LoopBlock.ramp_step_V`` / ``ramp_delay_s``), so the
  compiled ``BiasStep`` ramps with the same shape the classic sweep used and the
  executor honours it — no longer dropped.  ``ramp_step_V`` is stored as a
  magnitude (``abs``), matching the classic ``bias.ramp_to(step_V=abs(...))``
  call.  (Fail-closed divergence: a zero ``ramp_step_V`` — which the classic
  path would pass verbatim to ``ramp_to`` — is refused by the plan validator,
  not silently accepted.)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from controller.scan_plan import (
    ActionBlock,
    ActionType,
    Axis,
    LoopBlock,
    ScanPlan,
)

if TYPE_CHECKING:  # pragma: no cover - hints only, no runtime import
    from controller.scan_controller import ScanConfig, VoltageScanConfig


__all__ = ["plan_from_scan_config", "plan_from_voltage_scan_config"]


# --------------------------------------------------------------------------- #
# small builders                                                              #
# --------------------------------------------------------------------------- #

def _acquire(n_averages: int) -> ActionBlock:
    """An ``ACQUIRE_WAVEFORM`` leaf carrying the per-point average count.

    ``n_averages`` rides in the action's own ``params`` (a KNOWN acquire param),
    so the compiler's effective-averages rule takes it verbatim.
    """
    return ActionBlock(
        action=ActionType.ACQUIRE_WAVEFORM,
        params={"n_averages": int(n_averages)},
    )


def _save() -> ActionBlock:
    return ActionBlock(action=ActionType.SAVE_POINT)


def _fixed(axis: Axis, value: float) -> LoopBlock:
    """A degenerate single-value loop — the clean way to pin a fixed coordinate.

    ``materialize`` returns ``[value]`` verbatim, so the compiler commands the
    axis exactly once; the classic scans set X/Y/Z explicitly, so representing
    them as single-value loops (rather than dropping them to ``None`` = "do not
    command") is the faithful mapping.
    """
    return LoopBlock(axis=axis, values=[float(value)])


# --------------------------------------------------------------------------- #
# public converters                                                           #
# --------------------------------------------------------------------------- #

def plan_from_scan_config(cfg: "ScanConfig", *, name: str = "Quick scan") -> ScanPlan:
    """Convert a classic XY raster :class:`ScanConfig` into a :class:`ScanPlan`.

    Structure (outer → inner)::

        loop STAGE_Z values=[z_mm]          # fix the focal plane, set once
          loop STAGE_X start/stop/step       # outer raster axis
            loop STAGE_Y start/stop/step snake=True settle_s=settle_time_s
              ACQUIRE_WAVEFORM(n_averages)
              SAVE_POINT

    The snake Y loop reproduces ``_build_scan_points``'s boustrophedon order, and
    ``settle_time_s`` rides on the Y loop so the compiler emits a settle
    ``WaitStep`` after every point's move.  ``bias_channel`` is recorded in
    ``safety`` but no bias loop is emitted — a quick scan holds bias, so
    ``require_hv_confirmation`` is deliberately absent.

    Raises ``ValueError`` (from :meth:`LoopBlock.materialize`) if either stage
    range is degenerate (e.g. a zero step between distinct endpoints).
    """
    y = LoopBlock(
        axis=Axis.STAGE_Y,
        start=cfg.y_start_mm, stop=cfg.y_stop_mm, step=cfg.y_step_mm,
        snake=True,
        settle_s=float(cfg.settle_time_s),
        children=[_acquire(cfg.n_averages), _save()],
    )
    x = LoopBlock(
        axis=Axis.STAGE_X,
        start=cfg.x_start_mm, stop=cfg.x_stop_mm, step=cfg.x_step_mm,
        children=[y],
    )
    z = _fixed(Axis.STAGE_Z, cfg.z_mm)
    z.children = [x]

    # Eagerly surface a bad range as the model's OWN ValueError (mirror, don't
    # pre-empt): a zero step between distinct endpoints raises here, at convert
    # time, instead of deep in the compiler.
    x.materialize()
    y.materialize()

    return ScanPlan(
        name=name,
        description=(
            f"Quick XY raster: X {cfg.x_start_mm:g}..{cfg.x_stop_mm:g} "
            f"step {cfg.x_step_mm:g} mm, Y {cfg.y_start_mm:g}..{cfg.y_stop_mm:g} "
            f"step {cfg.y_step_mm:g} mm at Z {cfg.z_mm:g} mm "
            f"(x{int(cfg.n_averages)} avg). Converted from the Scan panel."
        ),
        root=[z],
        safety={"bias_channel": cfg.bias_channel},
    )


def plan_from_voltage_scan_config(
    cfg: "VoltageScanConfig", *, name: str = "IV / CCE sweep"
) -> ScanPlan:
    """Convert a classic :class:`VoltageScanConfig` (IV / CCE sweep) into a plan.

    Structure (outer → inner)::

        loop STAGE_X values=[x_mm]
          loop STAGE_Y values=[y_mm]
            loop STAGE_Z values=[z_mm]        # fix the beam position, set once
              loop BIAS_V start=v_start/stop=v_stop/step=v_step
                WAIT seconds=hold_delay_s      # only if hold_delay_s > 0
                ACQUIRE_WAVEFORM(n_averages)
                SAVE_POINT

    The direction-aware bias step matches the classic sweep in both polarities
    (``materialize`` derives the sign from ``v_start → v_stop`` and uses
    ``|v_step|`` for the magnitude — the same result as the classic signed-step
    ``np.arange``).  Because the plan *drives* HV, ``safety`` carries
    ``require_hv_confirmation = True`` (fail-closed) alongside ``bias_channel``.

    Raises ``ValueError`` (from :meth:`LoopBlock.materialize`) if the bias range
    is degenerate (e.g. ``v_step_V == 0`` between distinct endpoints) — the
    converter refuses rather than guess a bias step (unlike the classic scan,
    which silently defaults to 10 V).
    """
    children: list = []
    if float(cfg.hold_delay_s) > 0.0:
        # Faithful per-step settle: the classic sweep waits hold_delay_s after
        # each ramp, before acquiring.  As a WAIT child of the bias loop it fires
        # once per bias value (after the BiasStep), matching that timing.
        children.append(ActionBlock(
            action=ActionType.WAIT,
            params={"seconds": float(cfg.hold_delay_s)},
        ))
    children.extend([_acquire(cfg.n_averages), _save()])

    bias = LoopBlock(
        axis=Axis.BIAS_V,
        start=cfg.v_start_V, stop=cfg.v_stop_V, step=cfg.v_step_V,
        # Carry the per-run HV ramp shaping onto the bias loop so the compiled
        # BiasStep ramps with the same shape the classic sweep used (magnitude
        # for step, matching bias.ramp_to(step_V=abs(...))).
        ramp_step_V=abs(float(cfg.ramp_step_V)),
        ramp_delay_s=float(cfg.ramp_delay_s),
        children=children,
    )
    z = _fixed(Axis.STAGE_Z, cfg.z_mm); z.children = [bias]
    y = _fixed(Axis.STAGE_Y, cfg.y_mm); y.children = [z]
    x = _fixed(Axis.STAGE_X, cfg.x_mm); x.children = [y]

    # Eagerly surface a degenerate bias range as the model's OWN ValueError.
    bias.materialize()

    return ScanPlan(
        name=name,
        description=(
            f"Bias sweep: V {cfg.v_start_V:g}..{cfg.v_stop_V:g} step "
            f"{cfg.v_step_V:g} V at ({cfg.x_mm:g}, {cfg.y_mm:g}, {cfg.z_mm:g}) mm "
            f"(x{int(cfg.n_averages)} avg). Converted from the Scan panel."
        ),
        root=[x],
        safety={
            "require_hv_confirmation": True,
            "bias_channel": cfg.bias_channel,
        },
    )
