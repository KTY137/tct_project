"""
Camera-based positioning-repeatability test for the motor stage.

GRBL (and any stepper stage) is *open loop*: the position it reports is the
position it was *told* to go to, so reading it back can never reveal belt
backlash, lost steps or microstep hunting.  The only way to measure the real
mechanical repeatability is to watch the stage with an external sensor — here
the Blackfly camera looking at a textured target (the printed µm line strips or
the calibration bar).

Method
------
1. Park at a target point, grab a *reference* frame.
2. N times: move AWAY by ``approach_mm`` (direction cycles so we approach the
   target from different sides), move BACK to the target, settle, grab a frame,
   and measure its shift versus the reference by sub-pixel phase correlation.
3. The spread (std, peak-to-peak) of those shifts *is* the repeatability.

Calibration (px → mm) is optional: ``calibrate()`` commands one known move and
measures the resulting pixel shift, so results can be reported in µm.  The
repeatability *scatter* is meaningful even in raw pixels without it.

Frame preprocessing (Wave-5 step 1)
------------------------------------
Every grabbed frame is piped through
``analysis.image_prep.prepare_metrology_roi`` (see
:meth:`RepeatabilityTester._grab`) before correlation: a static vignette /
bright rim otherwise correlates at zero shift and biases
:func:`cross_correlation_shift`'s peak toward ``(0, 0)``, under-reporting
real motion (``docs/design/camera_survey_metrology.md`` §B.0 point 5 / §D).
:meth:`RepeatabilityTester.run` also gains a ``quality_min`` gate: a frame
``prepare_metrology_roi`` scores below it is flagged and excluded from the
repeatability statistics rather than silently folded in — see that method's
docstring. :func:`cross_correlation_shift` itself is UNCHANGED and stays a
pure image-in/shift-out function; it has no idea preprocessing happened.

Only numpy is required (no scipy / OpenCV / scikit-image).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np

from analysis.camera_calibration import AffineFit, fit_affine, residual_summary
from analysis.image_prep import PreparedROI, prepare_metrology_roi
from controller.danger_gate import DangerAction, DangerGate


# --------------------------------------------------------------------------- #
# Sub-pixel phase correlation (numpy only)                                     #
# --------------------------------------------------------------------------- #

def _hann2d(shape: tuple[int, int]) -> np.ndarray:
    wy = np.hanning(shape[0])
    wx = np.hanning(shape[1])
    return np.outer(wy, wx)


def _parabolic_peak(corr: np.ndarray, peak: tuple[int, int], axis: int) -> float:
    """Refine an integer peak index to sub-pixel with a 3-point parabola fit."""
    n = corr.shape[axis]
    i = peak[axis]

    def val(k: int) -> float:
        idx = list(peak)
        idx[axis] = k % n
        return float(corr[tuple(idx)])

    ym1, y0, yp1 = val(i - 1), val(i), val(i + 1)
    denom = ym1 - 2.0 * y0 + yp1
    delta = 0.5 * (ym1 - yp1) / denom if denom != 0.0 else 0.0
    return i + delta


def cross_correlation_shift(ref: np.ndarray, img: np.ndarray) -> tuple[float, float]:
    """Return the sub-pixel (dy, dx) displacement of *img* relative to *ref*.

    i.e. if ``img`` is ``ref`` shifted down by dy and right by dx, the result is
    ``(+dy, +dx)``.  Uses windowed FFT phase correlation with parabolic peak
    interpolation; robust to uniform brightness changes (mean removed, magnitude
    normalised).  Sign is irrelevant to the repeatability *scatter* but this
    convention makes ``calibrate()`` and debugging intuitive.
    """
    ref = np.asarray(ref, dtype=np.float64)
    img = np.asarray(img, dtype=np.float64)
    if ref.ndim == 3:
        ref = ref.mean(axis=2)
    if img.ndim == 3:
        img = img.mean(axis=2)
    if ref.shape != img.shape:               # crop to common region
        h = min(ref.shape[0], img.shape[0])
        w = min(ref.shape[1], img.shape[1])
        ref, img = ref[:h, :w], img[:h, :w]

    win = _hann2d(ref.shape)
    a = (ref - ref.mean()) * win
    b = (img - img.mean()) * win

    F = np.fft.rfft2(a)
    G = np.fft.rfft2(b)
    R = F * np.conj(G)
    R /= np.abs(R) + 1e-12                    # phase-only → sharp peak
    corr = np.fft.irfft2(R, s=ref.shape)

    peak = np.unravel_index(int(np.argmax(corr)), corr.shape)
    dy = _parabolic_peak(corr, peak, axis=0)
    dx = _parabolic_peak(corr, peak, axis=1)

    H, W = corr.shape                         # wrap to signed displacement
    if dy > H / 2:
        dy -= H
    if dx > W / 2:
        dx -= W
    # Phase correlation of conj(G) locates the shift that maps img→ref; negate
    # so the result is the displacement of img *relative to* ref.
    return -dy, -dx


# --------------------------------------------------------------------------- #
# Result container                                                            #
# --------------------------------------------------------------------------- #

@dataclass
class RepeatabilityResult:
    shifts_px: list[tuple[float, float]] = field(default_factory=list)  # (dx, dy)
    px_per_mm: float | None = None
    target_user: tuple[float, float, float] | None = None
    # Quality gating (Wave-5 step 1, RepeatabilityTester.run's `quality_min`):
    # a cycle whose grabbed frame scores below quality_min is excluded from
    # `shifts_px` -- and therefore from every statistic below
    # (std_px/p2p_px/radial_std_px) -- rather than silently folded in.
    # `quality_flags` has one entry per cycle actually EXECUTED (a frame was
    # grabbed), True = excluded; `n_low_quality` is the same information as a
    # plain count.  Both are `0`/`[]` for a denied/unconfirmed run (no cycle
    # ever executed) and for a pre-Wave-5 caller that never sees a low-quality
    # frame.
    n_low_quality: int = 0
    quality_flags: list[bool] = field(default_factory=list)

    def _arr(self) -> np.ndarray:
        return np.asarray(self.shifts_px, dtype=float).reshape(-1, 2)

    @property
    def n(self) -> int:
        return len(self.shifts_px)

    def std_px(self) -> tuple[float, float]:
        a = self._arr()
        return (float(a[:, 0].std(ddof=1)) if len(a) > 1 else 0.0,
                float(a[:, 1].std(ddof=1)) if len(a) > 1 else 0.0)

    def p2p_px(self) -> tuple[float, float]:
        a = self._arr()
        if len(a) == 0:
            return (0.0, 0.0)
        return (float(np.ptp(a[:, 0])), float(np.ptp(a[:, 1])))

    def radial_std_px(self) -> float:
        """Std of the radial distance from the mean point — a single number."""
        a = self._arr()
        if len(a) < 2:
            return 0.0
        c = a - a.mean(axis=0)
        r = np.hypot(c[:, 0], c[:, 1])
        return float(r.std(ddof=1))

    def _to_um(self, v: float) -> float | None:
        return v / self.px_per_mm * 1000.0 if self.px_per_mm else None

    def summary(self) -> str:
        sx, sy = self.std_px()
        px, py = self.p2p_px()
        rad = self.radial_std_px()
        lines = [
            f"Repeatability over {self.n} return moves:",
            f"  std    : X={sx:.2f} px   Y={sy:.2f} px",
            f"  peak-pk: X={px:.2f} px   Y={py:.2f} px",
            f"  radial std: {rad:.2f} px",
        ]
        if self.n_low_quality:
            lines.append(
                f"  excluded: {self.n_low_quality} low-quality frame(s) "
                f"(quality < quality_min) -- NOT included above"
            )
        if self.px_per_mm:
            lines.append(f"  scale  : {self.px_per_mm:.2f} px/mm "
                         f"({1000.0/self.px_per_mm:.3f} µm/px)")
            lines.append(f"  std    : X={self._to_um(sx):.1f} µm   "
                         f"Y={self._to_um(sy):.1f} µm")
            lines.append(f"  radial std: {self._to_um(rad):.1f} µm")
        else:
            lines.append("  (no px/mm calibration — run calibrate() for µm)")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Stage -> camera affine self-calibration (Wave-5 step 2)                      #
# --------------------------------------------------------------------------- #

def plan_affine_staircase(
    nx: int = 3,
    ny: int = 3,
    step_mm: float = 0.5,
    *,
    origin_mm: tuple[float, float] = (0.0, 0.0),
) -> list[tuple[float, float]]:
    """Commanded XY positions for a stage->camera affine-calibration staircase.

    The path covers an ``nx x ny`` grid (spacing ``step_mm``, lower-left corner
    ``origin_mm``) and is built so that **every interior grid point is
    approached from opposite directions on each axis** -- the raw observation
    backlash needs (approach a point moving +X vs -X, and +Y vs -Y; the
    forward-minus-return image discrepancy *is* the backlash, see
    :func:`fit_stage_camera_affine` and
    ``docs/design/camera_survey_metrology.md`` sections B/C, "step the stage ...
    both directions ... forward-return offset ... = backlash").

    Deterministic visit order (documented so the pairing in
    :func:`fit_stage_camera_affine`, the ``_forward_mask_from_path`` labelling,
    and the sim tests can rely on it)::

        Phase X -- one row at a time, j = 0 .. ny-1 (bottom to top):
            forward sweep : (x0,yj) (x1,yj) ... (x_{nx-1},yj)   [+X arrivals]
            return  sweep : (x_{nx-2},yj) ...   (x0,yj)         [-X arrivals]
        Phase Y -- one column at a time, i = 0 .. nx-1 (left to right):
            forward sweep : (xi,y0) (xi,y1) ... (xi,y_{ny-1})   [+Y arrivals]
            return  sweep : (xi,y_{ny-2}) ...   (xi,y0)         [-Y arrivals]

    Phase X exercises X backlash (X reverses between each row's forward and
    return sweep) and already visits every grid point; Phase Y exercises Y
    backlash. Consecutive commanded points differ by a single ``step_mm``
    (except the one Phase X -> Phase Y hand-off), so neighbour-to-neighbour
    image overlap stays high for the chained correlation in
    :meth:`RepeatabilityTester.calibrate_affine`.

    Pure planning only: NO device access, NO motion -- returns the commanded
    list for a caller (the tester) to drive under a danger gate.
    """
    if nx < 2 or ny < 2:
        raise ValueError(f"need at least a 2x2 grid; got nx={nx}, ny={ny}")
    if step_mm <= 0.0:
        raise ValueError(f"step_mm must be positive; got {step_mm}")
    ox, oy = float(origin_mm[0]), float(origin_mm[1])
    xs = [ox + i * float(step_mm) for i in range(nx)]
    ys = [oy + j * float(step_mm) for j in range(ny)]

    path: list[tuple[float, float]] = []
    # Phase X: each row forward (+X) then return (-X); the return skips the
    # turn point (x_{nx-1}) it just left, so interior x's are the ones seen
    # from both directions.
    for j in range(ny):
        for i in range(nx):
            path.append((xs[i], ys[j]))
        for i in range(nx - 2, -1, -1):
            path.append((xs[i], ys[j]))
    # Phase Y: each column forward (+Y) then return (-Y).
    for i in range(nx):
        for j in range(ny):
            path.append((xs[i], ys[j]))
        for j in range(ny - 2, -1, -1):
            path.append((xs[i], ys[j]))
    return path


def _forward_mask_from_path(path: list[tuple[float, float]]) -> list[bool]:
    """Label each visit forward(+)/return(-) by the sign of its arrival move
    along the dominant axis -- the staircase's forward sweeps arrive +X/+Y and
    its return sweeps -X/-Y (see :func:`plan_affine_staircase`). The very first
    visit has no arrival move and is labelled forward by convention (it seeds
    the chain and forms no pair)."""
    mask: list[bool] = [True]
    for k in range(1, len(path)):
        dx = path[k][0] - path[k - 1][0]
        dy = path[k][1] - path[k - 1][1]
        if abs(dx) >= abs(dy):
            mask.append(dx > 0.0)
        else:
            mask.append(dy > 0.0)
    return mask


@dataclass(frozen=True)
class StageCameraCal:
    """Stage->camera affine self-calibration result (Wave-5 step 2).

    ``affine`` is a real :class:`~analysis.camera_calibration.AffineFit` for
    every genuine fit; it is ``None`` ONLY for an aborted capture (gate denied,
    or fewer than three usable points) -- :func:`fit_stage_camera_affine`
    itself always returns a real fit. ``backlash_mm`` is the per-axis mean
    forward-minus-return discrepancy in stage mm (see
    :func:`fit_stage_camera_affine`); ``(0.0, 0.0)`` when no forward/return
    pairs were available. ``rms_um`` is the affine residual rms (linearity).
    ``passes`` is ``None`` unless a ``tolerance_um`` was supplied, else the
    :func:`~analysis.camera_calibration.residual_summary` pass/fail. ``notes``
    is a human one-liner (point count, rms, backlash, any exclusions)."""

    affine: AffineFit | None
    backlash_mm: tuple[float, float]
    rms_um: float
    passes: bool | None
    n_points: int
    notes: str


def _reduce_backlash(
    commanded: np.ndarray,
    measured: np.ndarray,
    affine: AffineFit,
    forward_mask: np.ndarray,
) -> tuple[tuple[float, float], int]:
    """Per-axis mean |forward-return| discrepancy in stage mm, plus the pair
    count. See :func:`fit_stage_camera_affine` for the derivation contract.

    The *approach axis* of each visit is read from the visit-ordered path (the
    dominant component of ``commanded[i] - commanded[i-1]``), and forward/return
    visits are paired **within the same axis**. This keeps X and Y backlash
    separate even when a commanded point is visited on both a row sweep and a
    column sweep (as the full staircase does) -- pairing all-forward against
    all-return there would blend the two axes and halve each number."""
    forward = np.asarray(forward_mask, dtype=bool).reshape(-1)
    obj = affine.image_to_object(measured)  # measured px -> apparent stage mm

    arrivals = np.zeros_like(commanded)
    if len(commanded) > 1:
        arrivals[1:] = commanded[1:] - commanded[:-1]
    approach_axis = np.argmax(np.abs(arrivals), axis=1)  # 0 (X) or 1 (Y) per visit

    groups: dict[tuple[float, float], list[int]] = {}
    for i, key in enumerate(map(tuple, np.round(commanded, 6))):
        groups.setdefault(key, []).append(i)

    sums = [0.0, 0.0]
    counts = [0, 0]
    for idxs in groups.values():
        for axis in (0, 1):
            on_axis = [i for i in idxs
                       if approach_axis[i] == axis and abs(arrivals[i][axis]) > 1e-9]
            fwd = [i for i in on_axis if forward[i]]
            ret = [i for i in on_axis if not forward[i]]
            if not fwd or not ret:
                continue
            # forward-minus-return in stage mm; the affine inverse already turned
            # the pixel offset into an mm offset via the fitted scale/rotation.
            dd = obj[fwd].mean(axis=0) - obj[ret].mean(axis=0)
            sums[axis] += abs(float(dd[axis]))
            counts[axis] += 1

    bx = sums[0] / counts[0] if counts[0] else 0.0
    by = sums[1] / counts[1] if counts[1] else 0.0
    return (bx, by), counts[0] + counts[1]


def fit_stage_camera_affine(
    commanded_mm,
    measured_px,
    *,
    tolerance_um: float | None = None,
    forward_mask=None,
) -> StageCameraCal:
    """Fit the stage->camera affine and derive per-axis backlash (pure).

    *commanded_mm* ``(N, 2)`` are the commanded stage XY (mm) in **visit
    order**; *measured_px* ``(N, 2)`` the registered image positions ``(u, v)``
    (px) of those visits (built by chaining sub-pixel correlations, see
    :meth:`RepeatabilityTester.calibrate_affine`). The affine (scale, rotation,
    shear), its residual metrics, and the pass/fail flag are delegated verbatim
    to :func:`analysis.camera_calibration.fit_affine` /
    :func:`~analysis.camera_calibration.residual_summary` -- this function only
    adds the backlash reduction. No device access; safe to unit-test.

    Backlash derivation
    -------------------
    A point commanded twice -- once on a forward (+) approach and once on a
    return (-) approach along the SAME axis -- images at two slightly different
    pixel positions; that offset is the mechanical backlash on that axis. Each
    visit's approach axis is read from the visit-ordered path (the dominant
    component of ``commanded[i] - commanded[i-1]``, hence *commanded_mm* must be
    in visit order); for every commanded position, forward and return visits are
    paired **within each axis**, mapped back to stage mm through the fitted
    affine inverse (:meth:`AffineFit.image_to_object`), and differenced. The
    per-axis magnitude is averaged into ``backlash_mm``. Pairing per axis (not
    all-forward against all-return) keeps X and Y separate even when a point is
    visited on both a row and a column sweep. With no *forward_mask* -- or a mask
    that yields no forward/return pair -- backlash is ``(0.0, 0.0)``: it is
    genuinely unmeasurable without the approach labelling, which is why the mask
    is a required observation rather than a convenience.
    """
    commanded = np.asarray(commanded_mm, dtype=np.float64).reshape(-1, 2)
    measured = np.asarray(measured_px, dtype=np.float64).reshape(-1, 2)
    n = len(commanded)
    affine = fit_affine(commanded, measured)

    passes: bool | None = None
    if tolerance_um is not None:
        summary = residual_summary(
            affine.residuals_px, affine.mean_px_per_mm, tolerance_um=tolerance_um,
        )
        passes = bool(summary["passes"])

    backlash: tuple[float, float] = (0.0, 0.0)
    if forward_mask is None:
        backlash_note = "backlash unmeasured (no forward/return mask)"
    else:
        backlash, n_pairs = _reduce_backlash(commanded, measured, affine, forward_mask)
        if n_pairs:
            backlash_note = (
                f"backlash {n_pairs} pair(s): X={backlash[0] * 1000.0:.2f} um, "
                f"Y={backlash[1] * 1000.0:.2f} um"
            )
        else:
            backlash_note = "backlash unmeasured (no matched forward/return pair)"

    notes = (
        f"{n} pts; rms {affine.rms_px:.3f} px ({affine.rms_um:.2f} um); "
        f"{backlash_note}"
    )
    return StageCameraCal(
        affine=affine,
        backlash_mm=backlash,
        rms_um=affine.rms_um,
        passes=passes,
        n_points=n,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Orchestrator                                                                #
# --------------------------------------------------------------------------- #

class RepeatabilityTester:
    """Drive the motor through a return-to-target pattern and measure the
    scatter of the camera image, i.e. the real mechanical repeatability.

    *motor* must implement ``get_position``, ``move_to``, ``move_relative``;
    *camera* must implement ``get_frame() -> np.ndarray`` and be connected.

    Stage motion is dangerous (CLAUDE.md hardware-safety rule 2), so this tester
    is fail-closed: it will not command a single move without an explicit
    operator confirmation obtained through an injected
    :class:`~controller.danger_gate.DangerGate`.  A single confirmation covers
    the whole run — carrying the real cycle count, axes and excursion — mirroring
    the plan executor's one-confirm-per-run stance in ``scan_controller``.  If no
    gate is supplied (*gate* is ``None``) the tester REFUSES to move: it raises
    rather than silently running ungated.

    *highpass_sigma_px* / *roi* configure the ``analysis.image_prep.
    prepare_metrology_roi`` preprocessing every grabbed frame goes through
    (see :meth:`_grab`, module docstring "Frame preprocessing"). ``roi=None``
    (default) uses the whole frame -- the closest match to pre-Wave-5
    behaviour, which never cropped; ``highpass_sigma_px`` defaults to
    ``prepare_metrology_roi``'s own default (15.0 px).
    """

    def __init__(self, motor, camera, logger: logging.Logger | None = None,
                 *, gate: DangerGate | None = None,
                 highpass_sigma_px: float = 15.0,
                 roi: tuple[int, int, int, int] | None = None) -> None:
        self._motor = motor
        self._camera = camera
        self.logger = logger or logging.getLogger(__name__)
        self._gate = gate
        self._highpass_sigma_px = highpass_sigma_px
        self._roi = roi

    # -- helpers ----------------------------------------------------------- #

    def _confirm_motion(self, action: DangerAction) -> bool:
        """Obtain the ONE operator confirmation that authorises this tester to
        move the stage.

        Fail-closed: with no gate injected the tester must never drive the
        stage, so a missing gate is a hard refusal (``RuntimeError``), not a
        silent no-op.  A gate that *denies* is a clean user abort and returns
        ``False`` (never raises) so callers can surface it gracefully.
        """
        if self._gate is None:
            raise RuntimeError(
                "RepeatabilityTester has no DangerGate — refusing to move the "
                "stage without operator confirmation.")
        return bool(self._gate.confirm(action))

    def _grab(self, settle_s: float) -> PreparedROI:
        """Grab one frame and run it through ``prepare_metrology_roi``
        (Wave-5 step 1) so a static vignette/illumination gradient cannot
        bias :func:`cross_correlation_shift`'s peak toward ``(0, 0)`` — see
        the module docstring "Frame preprocessing" section.

        Returns the full :class:`~analysis.image_prep.PreparedROI`, not just
        its ``.image``: callers use ``.image`` for correlation and ``.quality``
        for :meth:`run`'s quality gate.
        """
        if settle_s > 0:
            time.sleep(settle_s)
        frame = np.asarray(self._camera.get_frame())
        return prepare_metrology_roi(
            frame, roi=self._roi, highpass_sigma_px=self._highpass_sigma_px,
        )

    def calibrate(self, axis: str = "x", dist_mm: float = 5.0,
                  settle_s: float = 0.4) -> float:
        """Command one known move on *axis* and return px/mm from the measured
        pixel shift.  Returns to the start position afterwards.

        This is the quick *scalar* sanity check (one axis, one move); for
        placement-grade geometry -- rotation/shear/anisotropic scale, linearity
        residuals and per-axis backlash -- use :meth:`calibrate_affine`."""
        axis = axis.lower()
        d = {"x": (dist_mm, 0, 0), "y": (0, dist_mm, 0), "z": (0, 0, dist_mm)}[axis]
        # Fail-closed: this commands a real stage move, so confirm BEFORE any
        # motion (grabbing the reference frame does not move the stage).
        action = DangerAction(
            kind="move",
            summary=(f"Repeatability calibration: move the stage {dist_mm:g} mm "
                     f"on {axis.upper()} and back."),
            detail={"axis": axis.upper(), "dist_mm": dist_mm},
        )
        if not self._confirm_motion(action):
            raise RuntimeError(
                "Repeatability calibration not confirmed — no motion performed.")
        ref = self._grab(settle_s)
        self._motor.move_relative(*d)
        moved = self._grab(settle_s)
        self._motor.move_relative(-d[0], -d[1], -d[2])     # back to start
        dy, dx = cross_correlation_shift(ref.image, moved.image)
        shift_px = float(np.hypot(dx, dy))
        # The shift must stay within the frame or phase correlation aliases.
        # Warn if it is close to half the frame (the wrap-around limit).
        limit = 0.45 * min(moved.image.shape[:2])
        if shift_px > limit:
            self.logger.warning(
                "Calibration shift %.0f px exceeds %.0f px (≈half the %d×%d frame) "
                "— move too large for this magnification; reduce dist_mm.",
                shift_px, limit, moved.image.shape[1], moved.image.shape[0])
        px_per_mm = shift_px / abs(dist_mm) if dist_mm else 0.0
        self.logger.info("Calibration: %.1f mm on %s → %.1f px  (%.2f px/mm)",
                         dist_mm, axis.upper(), shift_px, px_per_mm)
        return px_per_mm

    def run(self, n: int = 20, approach_mm: float = 5.0, settle_s: float = 0.4,
            px_per_mm: float | None = None,
            quality_min: float = 0.2,
            progress: Callable[[int, int], None] | None = None,
            should_stop: Callable[[], bool] | None = None) -> RepeatabilityResult:
        """Run *n* return-to-target cycles and return the measured scatter.

        Each cycle moves away by ``approach_mm`` (the direction cycles through
        +X, +Y, -X, -Y so the target is approached from all sides) then back.

        *quality_min* (Wave-5 step 1) gates each cycle's
        ``prepare_metrology_roi`` quality score (0-1, see :meth:`_grab`): a
        cycle whose frame scores below it is FLAGGED
        (``RepeatabilityResult.quality_flags``) and EXCLUDED from
        ``shifts_px`` — and therefore from every statistic derived from it
        (``std_px``/``p2p_px``/``radial_std_px``) — rather than silently
        folded in; ``RepeatabilityResult.n_low_quality`` counts the
        exclusions. If every frame belonging to a cycle scores below
        *quality_min* (today, that is just the cycle's one frame — see the
        module docstring), the WHOLE cycle is excluded this way. This never
        changes the danger-gate / motion behaviour: the excluded cycle's move
        still happens exactly as commanded: only its (untrusted) correlation
        measurement is dropped from the statistics.
        """
        if not getattr(self._camera, "connected", False):
            raise RuntimeError("Camera is not connected — cannot measure repeatability.")

        target = self._motor.get_position()  # read-only, commands no motion
        target_user = (target.x_mm, target.y_mm, target.z_mm)

        # ONE confirmation covers the whole run (not one per cycle — a per-cycle
        # dialog would be unusable).  It carries the real numbers the operator
        # needs: cycle count, the axes exercised, and the max excursion.  This
        # happens BEFORE any move; the reference-frame grab below does not move.
        action = DangerAction(
            kind="move",
            summary=(f"Repeatability test: {n} return-to-target cycles on "
                     f"X/Y, max excursion {approach_mm:g} mm from the current "
                     f"point."),
            detail={"n_cycles": n, "axes": ["X", "Y"],
                    "excursion_mm": approach_mm, "target_user": target_user},
        )
        if not self._confirm_motion(action):
            self.logger.info(
                "Repeatability run not confirmed — no motion performed.")
            return RepeatabilityResult(px_per_mm=px_per_mm,
                                       target_user=target_user)

        ref = self._grab(settle_s)
        if ref.quality < quality_min:
            self.logger.warning(
                "Repeatability reference frame quality %.3f is below "
                "quality_min %.3f — every cycle is measured against this "
                "low-quality reference; consider re-focusing/re-illuminating "
                "before trusting this run's numbers.", ref.quality, quality_min)

        dirs = [(approach_mm, 0, 0), (0, approach_mm, 0),
                (-approach_mm, 0, 0), (0, -approach_mm, 0)]
        result = RepeatabilityResult(px_per_mm=px_per_mm,
                                     target_user=target_user)

        for i in range(n):
            if should_stop and should_stop():
                break
            dx_a, dy_a, dz_a = dirs[i % len(dirs)]
            self._motor.move_relative(dx_a, dy_a, dz_a)            # away
            self._motor.move_to(target.x_mm, target.y_mm, target.z_mm)  # back
            frame = self._grab(settle_s)

            low_quality = frame.quality < quality_min
            result.quality_flags.append(low_quality)
            if low_quality:
                result.n_low_quality += 1
                self.logger.debug(
                    "rep %d/%d: quality %.3f < quality_min %.3f — cycle "
                    "EXCLUDED from repeatability statistics (motion still "
                    "happened)", i + 1, n, frame.quality, quality_min)
                if progress:
                    progress(i + 1, n)
                continue

            dy, dx = cross_correlation_shift(ref.image, frame.image)
            result.shifts_px.append((dx, dy))
            self.logger.debug("rep %d/%d: dx=%.2f dy=%.2f px", i + 1, n, dx, dy)
            if progress:
                progress(i + 1, n)

        self.logger.info("Repeatability done:\n%s", result.summary())
        return result

    def calibrate_affine(self, *, nx: int = 3, ny: int = 3, step_mm: float = 0.5,
                         settle_s: float = 0.5, tolerance_um: float | None = None,
                         quality_min: float = 0.2) -> StageCameraCal:
        """Drive a danger-gated staircase and fit the stage->camera affine.

        Placement-grade companion to :meth:`calibrate` (which measures a single
        scalar px/mm). Plans an ``nx x ny`` staircase *around the current stage
        point* (:func:`plan_affine_staircase`); then -- after ONE operator
        confirmation covering the whole staircase -- visits each commanded
        position, settles, grabs a frame through the Wave-5 preprocessing
        pipeline (:meth:`_grab`), and chains neighbour-to-neighbour sub-pixel
        correlations into a cumulative pixel position versus the FIRST frame.
        The ``(commanded_mm, measured_px)`` pairs are fitted by
        :func:`fit_stage_camera_affine` (affine + linearity residuals + per-axis
        backlash).

        Safety -- identical fail-closed stance to :meth:`run`:

        * No gate injected -> refuse (``RuntimeError``); the stage never moves.
        * Gate DENIES -> clean abort: the stage is left exactly where it is, no
          motion is commanded, and a no-data :class:`StageCameraCal`
          (``affine is None``, ``n_points == 0``) is returned -- never raised.
        * Every move is a planned staircase position; nothing moves outside the
          confirmed extent. On success the stage is left at the last staircase
          point (this method does not auto-home or auto-return).

        A position whose grabbed frame scores below *quality_min* is EXCLUDED
        from the fit (never fabricated into a pair), counted in the returned
        ``notes``, and the chained correlation bridges the gap to the next good
        frame. If fewer than three usable points remain, a no-data result is
        returned rather than a meaningless fit.
        """
        if not getattr(self._camera, "connected", False):
            raise RuntimeError(
                "Camera is not connected — cannot calibrate the stage->camera affine.")

        start = self._motor.get_position()  # read-only, commands no motion
        origin = (start.x_mm, start.y_mm)
        z0 = start.z_mm
        path = plan_affine_staircase(nx=nx, ny=ny, step_mm=step_mm, origin_mm=origin)
        forward_mask_full = _forward_mask_from_path(path)
        # TODO(bench): confirm on the real stage+camera that step_mm keeps each
        # neighbour image shift well under half a frame at the actual
        # magnification (phase correlation aliases past that), and that the DUT
        # target has enough texture to correlate; both are optics-dependent and
        # only verifiable on hardware (docs/design/camera_survey_metrology.md D).
        x_extent = (nx - 1) * step_mm
        y_extent = (ny - 1) * step_mm

        # ONE confirmation for the whole staircase (mirrors run() / the plan
        # executor), carrying the real extent, step and move count. This is
        # BEFORE any move; the origin read above commands no motion.
        action = DangerAction(
            kind="move",
            summary=(f"Stage->camera affine calibration: {nx}x{ny} staircase, "
                     f"{step_mm:g} mm steps ({x_extent:g}x{y_extent:g} mm extent), "
                     f"{len(path)} moves from the current point."),
            detail={"nx": nx, "ny": ny, "step_mm": step_mm,
                    "x_extent_mm": x_extent, "y_extent_mm": y_extent,
                    "n_positions": len(path), "origin_mm": origin},
        )
        if not self._confirm_motion(action):
            self.logger.info(
                "Affine calibration not confirmed — no motion performed.")
            return StageCameraCal(
                affine=None, backlash_mm=(0.0, 0.0), rms_um=0.0, passes=None,
                n_points=0,
                notes="affine calibration denied at the danger gate — no motion performed",
            )

        commanded: list[tuple[float, float]] = []
        measured: list[tuple[float, float]] = []
        fwd_flags: list[bool] = []
        last_image: np.ndarray | None = None
        last_px = (0.0, 0.0)
        n_excluded = 0

        for k, (px_mm, py_mm) in enumerate(path):
            self._motor.move_to(px_mm, py_mm, z0)
            prepared = self._grab(settle_s)
            if prepared.quality < quality_min:
                n_excluded += 1
                self.logger.debug(
                    "affine cal: position %d (%.3f, %.3f) quality %.3f < %.3f "
                    "— EXCLUDED (motion still happened)",
                    k, px_mm, py_mm, prepared.quality, quality_min)
                continue
            if last_image is None:
                cur_px = (0.0, 0.0)                       # first good frame = origin
            else:
                dy, dx = cross_correlation_shift(last_image, prepared.image)
                cur_px = (last_px[0] + dx, last_px[1] + dy)
            commanded.append((px_mm, py_mm))
            measured.append(cur_px)
            fwd_flags.append(forward_mask_full[k])
            last_image = prepared.image
            last_px = cur_px

        if len(commanded) < 3:
            return StageCameraCal(
                affine=None, backlash_mm=(0.0, 0.0), rms_um=0.0, passes=None,
                n_points=len(commanded),
                notes=(f"affine calibration aborted: only {len(commanded)} usable "
                       f"point(s) after {n_excluded} low-quality exclusion(s) — "
                       f"need at least 3"),
            )

        cal = fit_stage_camera_affine(
            commanded, measured, tolerance_um=tolerance_um, forward_mask=fwd_flags,
        )
        if n_excluded:
            cal = replace(
                cal,
                notes=f"{n_excluded} low-quality position(s) excluded; {cal.notes}",
            )
        self.logger.info("Affine calibration done: %s", cal.notes)
        return cal
