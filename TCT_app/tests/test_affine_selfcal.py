"""Stage->camera affine self-calibration (Wave-5 step 2, danger-gate class).

Covers the three new pieces in ``controller/repeatability.py``:

* :func:`~controller.repeatability.plan_affine_staircase` -- pure planning
  (grid coverage, determinism, documented order, per-axis both-directions),
* :func:`~controller.repeatability.fit_stage_camera_affine` -- pure fitting
  (affine recovery, per-axis backlash, tolerance pass/fail, mask necessity),
* :meth:`~controller.repeatability.RepeatabilityTester.calibrate_affine` -- the
  danger-gated capture (fit accuracy on a fully simulated stage+camera,
  gate-denial performs zero motion, low-quality frames excluded not fabricated).

Everything is headless and simulated. The synthetic camera renders a fixed
broadband random field Fourier-shifted by a KNOWN ground-truth affine of the
stage position (rotation + shear + anisotropic scale), with per-axis backlash
injected through the sim motor's last-move direction -- so phase correlation
has an unambiguous peak and the recovered geometry can be checked against truth.
"""
from __future__ import annotations

import numpy as np
import pytest

from controller.danger_gate import AutoConfirmGate, DenyAllGate
from controller.repeatability import (
    RepeatabilityTester,
    _forward_mask_from_path,
    fit_stage_camera_affine,
    plan_affine_staircase,
)

# Ground-truth stage->image affine: anisotropic scale + rotation + shear.
_M = np.array([[38.0, -5.0], [4.0, 41.0]])
_SHAPE = (256, 256)


# --------------------------------------------------------------------------- #
# Synthetic, shift-covariant camera + backlash-aware motor                    #
# --------------------------------------------------------------------------- #

def _shift_image(u: float, v: float, base: np.ndarray) -> np.ndarray:
    """Return *base* shifted right by *u* px and down by *v* px via the Fourier
    shift theorem (exact, sub-pixel, broadband -> a unique phase-correlation
    peak). Matches ``cross_correlation_shift``'s (dy, dx) sign convention:
    a positive u/v moves image features toward +x/+y."""
    h, w = base.shape
    ky = np.fft.fftfreq(h)[:, None]
    kx = np.fft.rfftfreq(w)[None, :]
    spectrum = np.fft.rfft2(base) * np.exp(-2j * np.pi * (kx * u + ky * v))
    return np.fft.irfft2(spectrum, s=(h, w))


class _Pos:
    def __init__(self, x, y, z) -> None:
        self.x_mm, self.y_mm, self.z_mm = x, y, z


class _AffineSimMotor:
    """Records every move and models per-axis backlash: the *effective* stage
    position lags the commanded one by +/- backlash/2 depending on the last
    move direction on each axis (so approaching a point from + vs - lands at
    two positions differing by the full backlash)."""

    def __init__(self, backlash_mm: tuple[float, float] = (0.0, 0.0)) -> None:
        self.moves: list[tuple] = []
        self._x = self._y = self._z = 0.0
        self._bx, self._by = backlash_mm
        self._sx = 0.0
        self._sy = 0.0

    def get_position(self) -> _Pos:
        return _Pos(self._x, self._y, self._z)

    def _apply(self, x, y, z) -> None:
        if x > self._x + 1e-12:
            self._sx = 1.0
        elif x < self._x - 1e-12:
            self._sx = -1.0
        if y > self._y + 1e-12:
            self._sy = 1.0
        elif y < self._y - 1e-12:
            self._sy = -1.0
        self._x, self._y, self._z = x, y, z

    def move_to(self, x, y, z) -> None:
        self.moves.append(("abs", x, y, z))
        self._apply(x, y, z)

    def move_relative(self, dx, dy, dz) -> None:
        self.moves.append(("rel", dx, dy, dz))
        self._apply(self._x + dx, self._y + dy, self._z + dz)

    def effective_xy(self) -> tuple[float, float]:
        return (self._x + self._sx * self._bx * 0.5,
                self._y + self._sy * self._by * 0.5)


class _AffineSimCamera:
    """Renders the fixed random field shifted by ``_M @ (effective_xy - center)``
    -- the ground-truth stage->image affine. ``center`` keeps the circular
    Fourier shift small so wrap-around stays under the Hann window. Optionally
    returns a flat (quality-zero) frame on specific ``get_frame`` call indices,
    to exercise the low-quality exclusion path."""

    connected = True

    def __init__(self, motor: _AffineSimMotor, matrix, center,
                 shape=_SHAPE, blank_call_indices=()) -> None:
        self._motor = motor
        self._M = np.asarray(matrix, dtype=float)
        self._center = np.asarray(center, dtype=float)
        self._shape = shape
        self._blank = set(blank_call_indices)
        self._calls = 0
        self._base = np.random.default_rng(12345).standard_normal(shape)

    def get_frame(self) -> np.ndarray:
        i = self._calls
        self._calls += 1
        if i in self._blank:
            return np.full(self._shape, 50.0)      # flat -> prepare_* scores 0
        x, y = self._motor.effective_xy()
        d = self._M @ (np.array([x, y]) - self._center)
        return _shift_image(float(d[0]), float(d[1]), self._base)


def _grid_center(nx, ny, step_mm, origin=(0.0, 0.0)):
    return (origin[0] + (nx - 1) * step_mm / 2.0,
            origin[1] + (ny - 1) * step_mm / 2.0)


# --------------------------------------------------------------------------- #
# plan_affine_staircase -- pure planning                                      #
# --------------------------------------------------------------------------- #

def test_plan_covers_grid_deterministic_and_documented_order():
    plan = plan_affine_staircase(3, 3, 0.5, origin_mm=(1.0, 2.0))

    assert plan == plan_affine_staircase(3, 3, 0.5, origin_mm=(1.0, 2.0))  # deterministic
    grid = {(1.0 + i * 0.5, 2.0 + j * 0.5) for i in range(3) for j in range(3)}
    assert set(plan) == grid                                # full coverage
    # Documented order: row 0 forward (+X) then its return (-X, skipping turn pt).
    assert plan[:3] == [(1.0, 2.0), (1.5, 2.0), (2.0, 2.0)]
    assert plan[3:5] == [(1.5, 2.0), (1.0, 2.0)]


def test_plan_rejects_degenerate_grid():
    with pytest.raises(ValueError):
        plan_affine_staircase(1, 3, 0.5)
    with pytest.raises(ValueError):
        plan_affine_staircase(3, 3, 0.0)


def test_plan_interior_point_seen_from_both_x_directions():
    """The whole point of the staircase: an interior grid point is approached
    both moving +X and moving -X (a snake-only raster would give only one)."""
    plan = plan_affine_staircase(3, 3, 0.5)
    approaches = []
    for k in range(1, len(plan)):
        if plan[k] == (0.5, 0.0):
            dx = round(plan[k][0] - plan[k - 1][0], 6)
            dy = round(plan[k][1] - plan[k - 1][1], 6)
            approaches.append((dx, dy))
    assert (0.5, 0.0) in approaches      # arrived moving +X
    assert (-0.5, 0.0) in approaches     # arrived moving -X


def test_plan_steps_are_single_axis_within_a_phase():
    """Consecutive commanded points differ by one step on one axis (keeps
    neighbour overlap high for the chained correlation) -- allowing exactly the
    single documented Phase X -> Phase Y hand-off as a larger jump."""
    plan = plan_affine_staircase(4, 3, 0.5)
    big_jumps = 0
    for k in range(1, len(plan)):
        dx = abs(plan[k][0] - plan[k - 1][0])
        dy = abs(plan[k][1] - plan[k - 1][1])
        single_step = (dx <= 0.5 + 1e-9 and dy <= 1e-9) or (dy <= 0.5 + 1e-9 and dx <= 1e-9)
        if not single_step:
            big_jumps += 1
    assert big_jumps <= 1


# --------------------------------------------------------------------------- #
# fit_stage_camera_affine -- pure fitting                                     #
# --------------------------------------------------------------------------- #

def _grid_points(xs, ys):
    return np.array([(x, y) for y in ys for x in xs], dtype=float)


def test_fit_recovers_ground_truth_affine():
    obj = _grid_points((0.0, 0.5, 1.0), (0.0, 0.5, 1.0))
    offset = np.array([80.0, 70.0])
    measured = obj @ _M.T + offset

    cal = fit_stage_camera_affine(obj, measured)

    assert cal.affine is not None
    assert cal.affine.matrix_px_per_mm == pytest.approx(_M, abs=1e-6)
    assert cal.rms_um < 1e-6
    assert cal.n_points == 9
    assert cal.passes is None                # no tolerance supplied
    assert cal.backlash_mm == (0.0, 0.0)     # no mask -> unmeasured


def _staircase_measured(plan, bx, by, offset=np.array([80.0, 70.0])):
    """Analytic (correlation-free) measured_px for *plan*: applies the same
    last-move-direction backlash model the sim motor uses, then the ground-truth
    affine. Mirrors exactly what ``calibrate_affine`` builds, so the pure fit is
    exercised on real visit-ordered staircase data (not hand-picked pairs)."""
    measured = []
    prev = None
    sx = sy = 0.0
    for (x, y) in plan:
        if prev is not None:
            if x > prev[0] + 1e-12:
                sx = 1.0
            elif x < prev[0] - 1e-12:
                sx = -1.0
            if y > prev[1] + 1e-12:
                sy = 1.0
            elif y < prev[1] - 1e-12:
                sy = -1.0
        eff = np.array([x + sx * bx / 2, y + sy * by / 2])
        measured.append(_M @ eff + offset)
        prev = (x, y)
    return measured


def test_backlash_recovered_per_axis():
    bx, by = 0.020, 0.015
    plan = plan_affine_staircase(3, 3, 0.5)
    measured = _staircase_measured(plan, bx, by)
    fwd = _forward_mask_from_path(plan)

    cal = fit_stage_camera_affine(plan, measured, forward_mask=fwd)

    # Per-axis recovery on clean (correlation-free) staircase data, even though
    # the full grid revisits every point on both a row and a column sweep. Not
    # bit-exact: the affine fit absorbs a little of the backlash residual, so the
    # number read back through image_to_object is ~2% low -- an inherent, honest
    # coupling documented in fit_stage_camera_affine.
    assert cal.backlash_mm[0] == pytest.approx(bx, rel=0.06)
    assert cal.backlash_mm[1] == pytest.approx(by, rel=0.06)


def test_backlash_requires_the_forward_return_mask():
    """Kill-the-mask: without the forward/return labelling the discrepancy is
    unrecoverable, so backlash collapses to (0, 0). The correct mask recovers
    it -- proving the mask is a load-bearing observation, not a convenience."""
    plan = plan_affine_staircase(3, 3, 0.5)
    measured = _staircase_measured(plan, 0.02, 0.015)
    fwd = _forward_mask_from_path(plan)

    no_mask = fit_stage_camera_affine(plan, measured)
    all_forward = fit_stage_camera_affine(
        plan, measured, forward_mask=[True] * len(plan))
    correct = fit_stage_camera_affine(plan, measured, forward_mask=fwd)

    assert no_mask.backlash_mm == (0.0, 0.0)
    assert all_forward.backlash_mm == (0.0, 0.0)   # no return visits -> no pairs
    assert correct.backlash_mm[0] == pytest.approx(0.02, rel=0.06)
    assert correct.backlash_mm[1] == pytest.approx(0.015, rel=0.06)


def test_tolerance_um_flags_pass_and_fail():
    obj = _grid_points((0.0, 0.5, 1.0), (0.0, 0.5, 1.0))
    offset = np.array([80.0, 70.0])
    measured = obj @ _M.T + offset
    measured[0, 0] += 0.5                    # inject a known ~0.5 px error

    loose = fit_stage_camera_affine(obj, measured, tolerance_um=1000.0)
    tight = fit_stage_camera_affine(obj, measured, tolerance_um=0.001)

    assert loose.passes is True
    assert tight.passes is False


# --------------------------------------------------------------------------- #
# RepeatabilityTester.calibrate_affine -- danger-gated capture (simulated)     #
# --------------------------------------------------------------------------- #

def test_calibrate_affine_recovers_ground_truth_on_sim():
    motor = _AffineSimMotor(backlash_mm=(0.0, 0.0))
    center = _grid_center(3, 3, 0.5)
    cam = _AffineSimCamera(motor, _M, center)
    tester = RepeatabilityTester(motor, cam, gate=AutoConfirmGate())

    cal = tester.calibrate_affine(nx=3, ny=3, step_mm=0.5, settle_s=0.0,
                                  tolerance_um=50.0)

    assert cal.affine is not None
    assert cal.affine.rms_px < 0.1                       # sub-0.1 px registration
    assert cal.affine.matrix_px_per_mm == pytest.approx(_M, abs=0.3)
    assert cal.n_points == len(plan_affine_staircase(3, 3, 0.5))
    assert cal.passes is True


def test_calibrate_affine_reports_backlash_on_both_axes_on_sim():
    motor = _AffineSimMotor(backlash_mm=(0.030, 0.020))
    center = _grid_center(3, 3, 0.5)
    cam = _AffineSimCamera(motor, _M, center)
    tester = RepeatabilityTester(motor, cam, gate=AutoConfirmGate())

    cal = tester.calibrate_affine(nx=3, ny=3, step_mm=0.5, settle_s=0.0)

    # Full pipeline (motion + phase-correlation chaining) recovers backlash on
    # both axes to ~10% -- a hair lower than the pure fit because of accumulated
    # sub-pixel correlation drift on top of the affine coupling.
    assert cal.backlash_mm[0] == pytest.approx(0.030, abs=0.005)
    assert cal.backlash_mm[1] == pytest.approx(0.020, abs=0.004)


def test_calibrate_affine_denied_at_gate_performs_no_motion():
    motor = _AffineSimMotor()
    cam = _AffineSimCamera(motor, _M, _grid_center(3, 3, 0.5))
    tester = RepeatabilityTester(motor, cam, gate=DenyAllGate())

    cal = tester.calibrate_affine(nx=3, ny=3, step_mm=0.5, settle_s=0.0)

    assert motor.moves == []                 # a denied confirmation moves nothing
    assert cal.affine is None
    assert cal.n_points == 0
    assert cal.backlash_mm == (0.0, 0.0)
    assert "denied" in cal.notes


def test_calibrate_affine_without_gate_refuses_and_performs_no_motion():
    motor = _AffineSimMotor()
    cam = _AffineSimCamera(motor, _M, _grid_center(3, 3, 0.5))
    tester = RepeatabilityTester(motor, cam)   # no gate injected

    with pytest.raises(RuntimeError):
        tester.calibrate_affine(nx=3, ny=3, step_mm=0.5, settle_s=0.0)

    assert motor.moves == []


def test_calibrate_affine_excludes_low_quality_frame_but_still_fits():
    motor = _AffineSimMotor()
    center = _grid_center(3, 3, 0.5)
    # Blank the 4th grabbed frame -> exactly one commanded visit is excluded.
    cam = _AffineSimCamera(motor, _M, center, blank_call_indices={3})
    tester = RepeatabilityTester(motor, cam, gate=AutoConfirmGate())
    n_full = len(plan_affine_staircase(3, 3, 0.5))

    cal = tester.calibrate_affine(nx=3, ny=3, step_mm=0.5, settle_s=0.0)

    assert cal.affine is not None            # fit still valid across the gap
    assert cal.n_points == n_full - 1        # the low-quality visit was dropped
    assert "excluded" in cal.notes
    assert cal.affine.rms_px < 0.2           # bridged correlation stayed sane


def test_forward_mask_from_path_labels_sweeps():
    """The private helper labels forward sweeps (+X/+Y arrivals) True and
    return sweeps (-X/-Y) False -- the labelling calibrate_affine feeds the fit."""
    plan = plan_affine_staircase(3, 3, 0.5)
    mask = _forward_mask_from_path(plan)
    assert len(mask) == len(plan)
    assert mask[0] is True                   # seed
    # plan[1] arrives +X (row 0 forward), plan[3] arrives -X (row 0 return start)
    assert mask[1] is True
    assert mask[3] is False
