"""Tests for controller.plan_from_config — the pure quick-scan → ScanPlan converter.

Covers the invariants that make "Open in Planner" trustworthy:

* point-count equivalence with ``scan_controller._build_scan_points`` (incl.
  asymmetric ranges and negative envelope coords),
* snake / boustrophedon ORDER equivalence via the compiled MoveStep targets
  (the key alignment test),
* validator-clean output under generous limits, with the correct HV-confirmation
  posture for each converter (quick scan holds bias → no flag; vscan drives bias
  → flag required),
* settle / n_averages propagation into the compiled steps,
* YAML/dict round-trip stability,
* fail-closed ValueError on a degenerate (zero-step) range.
"""
import numpy as np
import pytest

from controller.scan_controller import (
    ScanConfig, VoltageScanConfig, _build_scan_points,
)
from controller.plan_from_config import (
    plan_from_scan_config, plan_from_voltage_scan_config,
)
from controller.scan_plan import ScanPlan, Axis, LoopBlock, ActionType
from controller.plan_compiler import (
    compile_plan, MoveStep, BiasStep, AcquireStep, SaveStep, WaitStep,
)
from controller.scan_plan_validator import validate_plan, errors, PlanLimits


# Generous limits — big enough that a well-formed converted plan raises no ERROR.
GENEROUS = PlanLimits(
    x_min_mm=-500.0, x_max_mm=500.0,
    y_min_mm=-500.0, y_max_mm=500.0,
    z_min_mm=-500.0, z_max_mm=500.0,
    voltage_range_V=1000.0,
    max_points=10_000_000,
)

# A spread of XY configs: default, negative envelope (x -300..0), asymmetric
# step/ranges, a single-column (zero-span x) scan.
XY_CONFIGS = [
    ScanConfig(),  # -1..1 / -1..1 step 0.1  (21x21)
    ScanConfig(x_start_mm=-300.0, x_stop_mm=0.0, x_step_mm=25.0,
               y_start_mm=-2.0, y_stop_mm=2.0, y_step_mm=0.5),
    ScanConfig(x_start_mm=-0.5, x_stop_mm=0.5, x_step_mm=0.05,
               y_start_mm=0.0, y_stop_mm=3.0, y_step_mm=0.3),
    ScanConfig(x_start_mm=0.0, x_stop_mm=0.0, x_step_mm=0.1,  # zero-span X column
               y_start_mm=-1.0, y_stop_mm=1.0, y_step_mm=0.2, z_mm=1.5),
    ScanConfig(x_start_mm=-300.0, x_stop_mm=-100.0, x_step_mm=20.0,
               y_start_mm=-300.0, y_stop_mm=-290.0, y_step_mm=2.0,
               n_averages=4, settle_time_s=0.12, z_mm=-3.0),
]


def _moves(plan):
    return [s for s in compile_plan(plan) if isinstance(s, MoveStep)]


# --------------------------------------------------------------------------- #
# XY raster: count + ordering equivalence with _build_scan_points             #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("cfg", XY_CONFIGS)
def test_total_points_matches_build_scan_points(cfg):
    plan = plan_from_scan_config(cfg)
    assert plan.total_points() == len(_build_scan_points(cfg))


@pytest.mark.parametrize("cfg", XY_CONFIGS)
def test_move_targets_reproduce_boustrophedon_order(cfg):
    """THE key test: compiled MoveStep (x, y) order == _build_scan_points order.

    One MoveStep per grid point (acquire+save share the coordinate), in the exact
    snake order, each carrying the fixed z.  Float values come from
    ``materialize`` (exact-endpoint) vs ``np.arange`` in the classic path, so the
    coordinates are compared with a tolerance — the ORDER and count are exact.
    """
    plan = plan_from_scan_config(cfg)
    moves = _moves(plan)
    pts = _build_scan_points(cfg)
    assert len(moves) == len(pts)
    for m, p in zip(moves, pts):
        assert m.x_mm == pytest.approx(p.x_mm, abs=1e-9)
        assert m.y_mm == pytest.approx(p.y_mm, abs=1e-9)
        assert m.z_mm == pytest.approx(cfg.z_mm, abs=1e-12)


def test_snake_order_hand_checked():
    """Small 3x2 grid whose serpentine order is enumerated by hand."""
    cfg = ScanConfig(x_start_mm=0.0, x_stop_mm=2.0, x_step_mm=1.0,
                     y_start_mm=0.0, y_stop_mm=1.0, y_step_mm=1.0, z_mm=5.0)
    got = [(m.x_mm, m.y_mm, m.z_mm) for m in _moves(plan_from_scan_config(cfg))]
    expected = [
        (0.0, 0.0, 5.0), (0.0, 1.0, 5.0),   # x=0 (even): y forward
        (1.0, 1.0, 5.0), (1.0, 0.0, 5.0),   # x=1 (odd):  y reversed
        (2.0, 0.0, 5.0), (2.0, 1.0, 5.0),   # x=2 (even): y forward
    ]
    assert got == expected


def test_fixed_z_is_a_single_value_loop_and_snake_flag_set():
    plan = plan_from_scan_config(ScanConfig(z_mm=2.5))
    z = plan.root[0]
    assert isinstance(z, LoopBlock) and z.axis is Axis.STAGE_Z
    assert z.materialize() == [2.5]
    x = z.children[0]
    assert x.axis is Axis.STAGE_X and x.snake is False
    y = x.children[0]
    assert y.axis is Axis.STAGE_Y and y.snake is True


# --------------------------------------------------------------------------- #
# XY raster: settle / n_averages propagation + validator posture              #
# --------------------------------------------------------------------------- #

def test_settle_and_averages_propagate_into_steps():
    cfg = ScanConfig(x_start_mm=0.0, x_stop_mm=1.0, x_step_mm=0.5,
                     y_start_mm=0.0, y_stop_mm=1.0, y_step_mm=0.5,
                     n_averages=7, settle_time_s=0.2)
    steps = compile_plan(plan_from_scan_config(cfg))
    waits = [s for s in steps if isinstance(s, WaitStep)]
    acqs = [s for s in steps if isinstance(s, AcquireStep)]
    npts = len(_build_scan_points(cfg))
    # one settle WaitStep after every point's move, all == settle_time_s
    assert len(waits) == npts
    assert all(w.seconds == pytest.approx(0.2) for w in waits)
    # n_averages carried onto every AcquireStep
    assert acqs and all(a.n_averages == 7 for a in acqs)


def test_zero_settle_emits_no_wait_steps():
    cfg = ScanConfig(x_start_mm=0.0, x_stop_mm=1.0, x_step_mm=0.5,
                     y_start_mm=0.0, y_stop_mm=1.0, y_step_mm=0.5,
                     settle_time_s=0.0)
    steps = compile_plan(plan_from_scan_config(cfg))
    assert not [s for s in steps if isinstance(s, WaitStep)]


@pytest.mark.parametrize("cfg", XY_CONFIGS)
def test_quick_scan_validates_clean_and_drives_no_hv(cfg):
    plan = plan_from_scan_config(cfg)
    assert errors(validate_plan(plan, GENEROUS)) == []
    # A quick scan HOLDS bias — no bias loop, and (fail-closed check agrees) no
    # require_hv_confirmation is needed for a bias_channel-only plan.
    assert not any(
        isinstance(s, BiasStep) for s in compile_plan(plan)
    )
    assert "require_hv_confirmation" not in plan.safety


def test_quick_scan_carries_bias_channel_in_safety():
    plan = plan_from_scan_config(ScanConfig(bias_channel=1))
    assert plan.safety.get("bias_channel") == 1
    # bias_channel-only plan (no bias loop) still validates clean.
    assert errors(validate_plan(plan, GENEROUS)) == []
    plan0 = plan_from_scan_config(ScanConfig())  # default channel = None
    assert plan0.safety.get("bias_channel") is None


def test_custom_name_is_used():
    assert plan_from_scan_config(ScanConfig(), name="My raster").name == "My raster"


# --------------------------------------------------------------------------- #
# Voltage / IV sweep                                                          #
# --------------------------------------------------------------------------- #

VSCAN_CONFIGS = [
    VoltageScanConfig(),  # 0..-300 step -10 (descending), n_avg 3, hold 1.0
    VoltageScanConfig(v_start_V=0.0, v_stop_V=200.0, v_step_V=25.0,  # ascending
                      n_averages=5, hold_delay_s=0.0),
    VoltageScanConfig(v_start_V=-50.0, v_stop_V=-350.0, v_step_V=-50.0,
                      x_mm=1.0, y_mm=-2.0, z_mm=0.5, bias_channel=2),
]


@pytest.mark.parametrize("cfg", VSCAN_CONFIGS)
def test_vscan_bias_grid_matches_classic_sweep(cfg):
    """The bias set points equal the classic direction-aware np.arange sweep."""
    raw = abs(cfg.v_step_V) or 10.0
    direction = 1 if cfg.v_stop_V >= cfg.v_start_V else -1
    signed = direction * raw
    classic = list(np.arange(cfg.v_start_V, cfg.v_stop_V + signed / 2, signed))

    bias_targets = [s.target_V for s in compile_plan(plan_from_voltage_scan_config(cfg))
                    if isinstance(s, BiasStep)]
    assert len(bias_targets) == len(classic)
    assert np.allclose(bias_targets, classic)


@pytest.mark.parametrize("cfg", VSCAN_CONFIGS)
def test_vscan_validates_clean_and_requires_hv_confirmation(cfg):
    plan = plan_from_voltage_scan_config(cfg)
    assert errors(validate_plan(plan, GENEROUS)) == []
    # A bias-driving plan MUST carry the fail-closed HV flag (validator enforces).
    assert plan.safety.get("require_hv_confirmation") is True
    assert plan.safety.get("bias_channel") == cfg.bias_channel


def test_vscan_positions_once_and_averages_propagate():
    cfg = VoltageScanConfig(x_mm=1.0, y_mm=2.0, z_mm=3.0, n_averages=4,
                            v_start_V=0.0, v_stop_V=-30.0, v_step_V=-10.0,
                            hold_delay_s=1.0)
    steps = compile_plan(plan_from_voltage_scan_config(cfg))
    moves = [s for s in steps if isinstance(s, MoveStep)]
    acqs = [s for s in steps if isinstance(s, AcquireStep)]
    # Fixed position → exactly one move, commanding all three axes.
    assert len(moves) == 1
    assert (moves[0].x_mm, moves[0].y_mm, moves[0].z_mm) == (1.0, 2.0, 3.0)
    assert acqs and all(a.n_averages == 4 for a in acqs)


def test_vscan_hold_delay_becomes_per_step_wait():
    cfg = VoltageScanConfig(v_start_V=0.0, v_stop_V=-20.0, v_step_V=-10.0,
                            hold_delay_s=0.7)
    steps = compile_plan(plan_from_voltage_scan_config(cfg))
    n_bias = sum(1 for s in steps if isinstance(s, BiasStep))
    waits = [s for s in steps if isinstance(s, WaitStep)]
    # one hold WaitStep per bias set point (no settle WaitStep: position is fixed)
    assert len(waits) == n_bias
    assert all(w.seconds == pytest.approx(0.7) for w in waits)


def test_vscan_zero_hold_delay_emits_no_wait():
    cfg = VoltageScanConfig(v_start_V=0.0, v_stop_V=-20.0, v_step_V=-10.0,
                            hold_delay_s=0.0)
    steps = compile_plan(plan_from_voltage_scan_config(cfg))
    assert not [s for s in steps if isinstance(s, WaitStep)]


# --------------------------------------------------------------------------- #
# Fail-closed on degenerate ranges + YAML round-trip                          #
# --------------------------------------------------------------------------- #

def test_zero_step_xy_raises_value_error():
    with pytest.raises(ValueError):
        plan_from_scan_config(
            ScanConfig(x_start_mm=0.0, x_stop_mm=5.0, x_step_mm=0.0))
    with pytest.raises(ValueError):
        plan_from_scan_config(
            ScanConfig(y_start_mm=0.0, y_stop_mm=5.0, y_step_mm=0.0))


def test_zero_step_vscan_raises_value_error():
    # Fail-closed: unlike the classic sweep (which defaults to 10 V), the
    # converter refuses a degenerate bias step.
    with pytest.raises(ValueError):
        plan_from_voltage_scan_config(
            VoltageScanConfig(v_start_V=0.0, v_stop_V=-100.0, v_step_V=0.0))


@pytest.mark.parametrize("plan", [
    plan_from_scan_config(ScanConfig()),
    plan_from_scan_config(ScanConfig(bias_channel=1, z_mm=-2.0, n_averages=3)),
    plan_from_voltage_scan_config(VoltageScanConfig()),
    plan_from_voltage_scan_config(VoltageScanConfig(bias_channel=2, hold_delay_s=0.0)),
])
def test_dict_and_yaml_round_trip_unchanged(plan):
    d = plan.to_dict()
    assert ScanPlan.from_dict(d).to_dict() == d
    assert ScanPlan.from_yaml(plan.to_yaml()).to_dict() == d


# --------------------------------------------------------------------------- #
# G1: per-BiasStep HV ramp shaping survives the conversion (no longer dropped) #
# --------------------------------------------------------------------------- #

def _bias_loop(plan):
    """The single BIAS_V LoopBlock in a converted vscan plan (x→y→z→bias)."""
    x = plan.root[0]
    y = x.children[0]
    z = y.children[0]
    bias = z.children[0]
    assert bias.axis is Axis.BIAS_V
    return bias


def _iter_loops(blocks):
    for b in blocks:
        if isinstance(b, LoopBlock):
            yield b
            yield from _iter_loops(b.children)


def test_vscan_carries_ramp_shaping_into_bias_loop_and_steps():
    """The two VoltageScanConfig ramp knobs reach the BIAS_V loop AND every
    compiled BiasStep — they are no longer silently dropped."""
    cfg = VoltageScanConfig(v_start_V=0.0, v_stop_V=-30.0, v_step_V=-10.0,
                            ramp_step_V=7.5, ramp_delay_s=0.25, hold_delay_s=0.0)
    plan = plan_from_voltage_scan_config(cfg)

    bias = _bias_loop(plan)
    assert bias.ramp_step_V == 7.5
    assert bias.ramp_delay_s == 0.25

    bias_steps = [s for s in compile_plan(plan) if isinstance(s, BiasStep)]
    assert bias_steps
    assert all(s.ramp_step_V == 7.5 for s in bias_steps)
    assert all(s.ramp_delay_s == 0.25 for s in bias_steps)


def test_vscan_ramp_step_stored_as_magnitude():
    """ramp_step_V is stored as a magnitude (abs), matching the classic
    bias.ramp_to(step_V=abs(cfg.ramp_step_V)) call."""
    cfg = VoltageScanConfig(v_start_V=0.0, v_stop_V=-20.0, v_step_V=-10.0,
                            ramp_step_V=-7.5, ramp_delay_s=0.1)
    bias = _bias_loop(plan_from_voltage_scan_config(cfg))
    assert bias.ramp_step_V == 7.5


def test_default_vscan_carries_default_ramp_shaping():
    """The default VoltageScanConfig ramp shape (5 V / 0.1 s) reaches the steps,
    so a plan-driven default sweep ramps the same way the classic default did."""
    plan = plan_from_voltage_scan_config(VoltageScanConfig())
    bias_steps = [s for s in compile_plan(plan) if isinstance(s, BiasStep)]
    assert bias_steps
    assert all(s.ramp_step_V == 5.0 and s.ramp_delay_s == 0.1 for s in bias_steps)


def test_quick_scan_loops_carry_no_ramp_shaping():
    """An XY raster holds bias — no loop requests HV ramp shaping (absent = the
    driver default; leaves existing quick-scan plans byte-identical)."""
    plan = plan_from_scan_config(ScanConfig())
    loops = list(_iter_loops(plan.root))
    assert loops
    assert all(l.ramp_step_V is None and l.ramp_delay_s is None for l in loops)


def test_ramp_shaping_survives_yaml_round_trip():
    """The ramp knobs survive a full YAML serialise/deserialise into the steps."""
    cfg = VoltageScanConfig(v_start_V=0.0, v_stop_V=-20.0, v_step_V=-10.0,
                            ramp_step_V=7.5, ramp_delay_s=0.25, hold_delay_s=0.0)
    plan = ScanPlan.from_yaml(plan_from_voltage_scan_config(cfg).to_yaml())
    bias_steps = [s for s in compile_plan(plan) if isinstance(s, BiasStep)]
    assert bias_steps
    assert all(s.ramp_step_V == 7.5 and s.ramp_delay_s == 0.25 for s in bias_steps)
