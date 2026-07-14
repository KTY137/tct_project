"""Structural ceiling on :func:`controller.plan_estimate.estimate_plan`.

The gate-red "estimate explosion": a plan with a billion-plus structural leaf
visits used to send the estimate worker into a multi-minute leaf walk that
overran its shutdown-join budget.  ``estimate_plan`` now short-circuits above
:data:`ESTIMATE_MAX_LEAF_VISITS` and returns the cheap structural counts with
explicit not-estimated sentinels (``estimated=False``; runtime/data/travel/HV
are ``None``, NOT zeros) plus a too-large warning.

Proven here, hardware-free:
  (i)   a ~2e9-leaf-visit plan is estimated in well under a second and the leaf
        walk (``ScanPlan.iter_leaf_contexts_ex``) is never entered;
  (ii)  the boundary is exact -- a plan AT the ceiling still estimates fully
        (real runtime, no too-large warning); one over it does not;
  (iii) the planner panel renders the too-large state honestly: the structural
        point count shows, the warning text lands in the UI, and no sentinel is
        ever formatted as a real "0 s".
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from controller.plan_estimate import (
    ESTIMATE_MAX_LEAF_VISITS,
    PlanEstimate,
    estimate_plan,
)
from controller.scan_plan import (
    ActionBlock,
    ActionType,
    Axis,
    LoopBlock,
    ScanPlan,
)


def _acq() -> ActionBlock:
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={})


def _save() -> ActionBlock:
    return ActionBlock(action=ActionType.SAVE_POINT, params={})


def _range_loop(axis: Axis, n: int, children) -> LoopBlock:
    """A loop that materializes exactly *n* values via start/stop/step.

    ``materialize`` builds one *n*-element list; nested, the total leaf count is
    the PRODUCT of the levels while each level's materialize stays O(n), so a
    billion-visit plan is built (and counted) from three tiny lists.
    """
    return LoopBlock(axis=axis, start=0.0, stop=float(n - 1), step=1.0,
                     children=children)


def _huge_plan() -> ScanPlan:
    """~1000^3 grid x (acquire+save) = ~2e9 structural leaf visits."""
    x = _range_loop(Axis.STAGE_X, 1000, [_acq(), _save()])
    y = _range_loop(Axis.STAGE_Y, 1000, [x])
    z = _range_loop(Axis.STAGE_Z, 1000, [y])
    return ScanPlan(root=[z], safety={"require_hv_confirmation": True})


def _tiny_plan() -> ScanPlan:
    """x[0,1] x (acquire+save) = 4 structural leaf visits (fast to walk)."""
    x = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0], children=[_acq(), _save()])
    b = LoopBlock(axis=Axis.BIAS_V, values=[-50.0], children=[x])
    return ScanPlan(root=[b], safety={"require_hv_confirmation": True})


# --------------------------------------------------------------------------- #
# (i) the huge plan short-circuits BEFORE any leaf walk                        #
# --------------------------------------------------------------------------- #

def test_huge_plan_short_circuits_without_leaf_walk(monkeypatch):
    plan = _huge_plan()
    assert plan.total_leaf_visits() > ESTIMATE_MAX_LEAF_VISITS

    # Spy: the too-large path must never enter the per-leaf generator.  A real
    # walk of ~2e9 visits would take minutes; catching a single call here is the
    # explicit proof the walk was skipped, independent of the wall-clock bound.
    calls = {"n": 0}
    orig = ScanPlan.iter_leaf_contexts_ex

    def spy(self):
        calls["n"] += 1
        return orig(self)

    monkeypatch.setattr(ScanPlan, "iter_leaf_contexts_ex", spy)

    t0 = time.monotonic()
    est = estimate_plan(plan)
    elapsed = time.monotonic() - t0

    assert calls["n"] == 0, "estimate_plan walked the leaf stream for a huge plan"
    assert elapsed < 1.0, f"structural short-circuit took {elapsed:.3f}s"
    # Structural counts are real; the cost fields are honest not-estimated
    # sentinels (None), never misleading zeros.
    assert est.estimated is False
    assert est.total_leaf_visits == plan.total_leaf_visits()
    assert est.total_points == plan.total_points()
    assert est.est_runtime_s is None
    assert est.est_data_bytes is None
    assert est.stage_travel_mm is None
    assert est.hv_range_V is None
    assert est.warnings and "too large" in est.warnings[0].lower()
    assert str(est.total_leaf_visits) in est.warnings[0].replace(",", "")


# --------------------------------------------------------------------------- #
# (ii) the ceiling boundary is exact                                           #
# --------------------------------------------------------------------------- #

def test_plan_at_ceiling_still_estimates_fully(monkeypatch):
    """A plan whose leaf count equals the ceiling is estimated fully; one over
    it short-circuits.  Uses a tiny plan with the ceiling monkeypatched to its
    exact leaf count, so the boundary (``>`` not ``>=``) is exercised without a
    slow walk."""
    plan = _tiny_plan()
    n = plan.total_leaf_visits()
    assert n == 4

    # AT the ceiling: n is not > n, so the full estimate runs.
    monkeypatch.setattr("controller.plan_estimate.ESTIMATE_MAX_LEAF_VISITS", n)
    est = estimate_plan(plan)
    assert est.estimated is True
    assert est.est_runtime_s is not None and est.est_runtime_s > 0.0
    assert est.stage_travel_mm is not None
    assert not any("too large" in w.lower() for w in est.warnings)

    # One BELOW the ceiling: n > n-1, so it short-circuits.
    monkeypatch.setattr("controller.plan_estimate.ESTIMATE_MAX_LEAF_VISITS", n - 1)
    est_over = estimate_plan(plan)
    assert est_over.estimated is False
    assert est_over.est_runtime_s is None
    assert est_over.warnings and "too large" in est_over.warnings[0].lower()


def test_normal_plan_is_unaffected():
    """The real (unpatched) ceiling leaves a normal plan fully estimated."""
    est = estimate_plan(_tiny_plan())
    assert est.estimated is True
    assert est.est_runtime_s is not None
    assert isinstance(est.stage_travel_mm, dict)


# --------------------------------------------------------------------------- #
# (iii) the panel renders the too-large state honestly                         #
# --------------------------------------------------------------------------- #

def test_render_too_large_estimate_is_honest():
    from PySide6.QtWidgets import QApplication

    from gui.planner_panel import PlannerPanel

    app = QApplication.instance() or QApplication([])
    assert app is not None

    too_large = PlanEstimate(
        total_points=1_000_000_000,
        total_leaf_visits=2_000_000_000,
        est_runtime_s=None,
        est_data_bytes=None,
        stage_travel_mm=None,
        hv_range_V=None,
        warnings=["Plan too large to estimate precisely "
                  "(2,000,000,000 leaf visits) — reduce loop ranges."],
        estimated=False,
    )

    panel = PlannerPanel()
    try:
        panel._render_estimate(too_large)

        # Structural point count is shown honestly (real number, not "—").
        assert panel._tile_points.value() == "1,000,000,000"

        # No sentinel is ever formatted as a real reading (esp. NOT "0 s").
        for tile in (panel._tile_runtime, panel._tile_data,
                     panel._tile_travel, panel._tile_hv):
            assert tile.value() == "—"
            assert tile.value() != "0 s"

        # The too-large warning text lands in the UI (each sentinel tile's
        # stale caption carries it).
        caption = panel._tile_runtime._caption.text()
        assert "too large" in caption.lower()
        assert panel._tile_runtime.is_stale()
    finally:
        panel.shutdown()


def test_ceiling_constant_is_pinned():
    """ESTIMATE_MAX_LEAF_VISITS is a safety-tied knob: it bounds the estimate
    walk to (approximately) the estimate worker's 3 s shutdown-join budget.
    A silent bump would widen the QThread-teardown window with a green suite
    (Mary rider on 44e17d4) — raising it must be a deliberate, test-touching
    act that revisits the join-budget math in the constant's docstring."""
    from controller.plan_estimate import ESTIMATE_MAX_LEAF_VISITS

    assert ESTIMATE_MAX_LEAF_VISITS <= 1_000_000
