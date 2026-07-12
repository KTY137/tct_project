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

Only numpy + scipy are required (no OpenCV / scikit-image).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

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
    """

    def __init__(self, motor, camera, logger: logging.Logger | None = None,
                 *, gate: DangerGate | None = None) -> None:
        self._motor = motor
        self._camera = camera
        self.logger = logger or logging.getLogger(__name__)
        self._gate = gate

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

    def _grab(self, settle_s: float) -> np.ndarray:
        if settle_s > 0:
            time.sleep(settle_s)
        return np.asarray(self._camera.get_frame())

    def calibrate(self, axis: str = "x", dist_mm: float = 5.0,
                  settle_s: float = 0.4) -> float:
        """Command one known move on *axis* and return px/mm from the measured
        pixel shift.  Returns to the start position afterwards."""
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
        dy, dx = cross_correlation_shift(ref, moved)
        shift_px = float(np.hypot(dx, dy))
        # The shift must stay within the frame or phase correlation aliases.
        # Warn if it is close to half the frame (the wrap-around limit).
        limit = 0.45 * min(moved.shape[:2])
        if shift_px > limit:
            self.logger.warning(
                "Calibration shift %.0f px exceeds %.0f px (≈half the %d×%d frame) "
                "— move too large for this magnification; reduce dist_mm.",
                shift_px, limit, moved.shape[1], moved.shape[0])
        px_per_mm = shift_px / abs(dist_mm) if dist_mm else 0.0
        self.logger.info("Calibration: %.1f mm on %s → %.1f px  (%.2f px/mm)",
                         dist_mm, axis.upper(), shift_px, px_per_mm)
        return px_per_mm

    def run(self, n: int = 20, approach_mm: float = 5.0, settle_s: float = 0.4,
            px_per_mm: float | None = None,
            progress: Callable[[int, int], None] | None = None,
            should_stop: Callable[[], bool] | None = None) -> RepeatabilityResult:
        """Run *n* return-to-target cycles and return the measured scatter.

        Each cycle moves away by ``approach_mm`` (the direction cycles through
        +X, +Y, -X, -Y so the target is approached from all sides) then back.
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
            dy, dx = cross_correlation_shift(ref, frame)
            result.shifts_px.append((dx, dy))
            self.logger.debug("rep %d/%d: dx=%.2f dy=%.2f px", i + 1, n, dx, dy)
            if progress:
                progress(i + 1, n)

        self.logger.info("Repeatability done:\n%s", result.summary())
        return result
