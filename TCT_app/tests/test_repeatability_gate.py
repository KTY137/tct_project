"""Safety gate for the camera-based repeatability tester.

The :class:`~controller.repeatability.RepeatabilityTester` drives the stage
(``move_relative`` / ``move_to``), which is a dangerous action under CLAUDE.md
hardware-safety rule 2 and therefore requires explicit operator confirmation via
an injected :class:`~controller.danger_gate.DangerGate`.  These tests pin the
fail-closed contract:

  (a) a confirmation carrying the real motion description is requested BEFORE any
      move is commanded,
  (b) a denied confirmation performs ZERO motion,
  (c) with NO gate injected the tester refuses (raises) and performs zero motion,
  (d) an approved confirmation lets the run proceed to completion on the fully
      simulated motor backend.

Everything is headless and simulated — no Qt, no hardware I/O.
"""
from __future__ import annotations

import numpy as np
import pytest

from controller.danger_gate import AutoConfirmGate, DangerAction, DenyAllGate
from controller.repeatability import RepeatabilityTester
from devices.motor_simulated import SimulatedMotorStage


# --------------------------------------------------------------------------- #
# Test doubles                                                                #
# --------------------------------------------------------------------------- #

class _FakeCamera:
    """Connected camera returning a fixed textured frame every grab.

    A constant frame makes phase correlation return ~zero shift, which is all
    the gate tests need; the numeric repeatability value is irrelevant here.
    """

    connected = True

    def __init__(self) -> None:
        rng = np.random.default_rng(0)
        self._frame = rng.standard_normal((32, 32))

    def get_frame(self) -> np.ndarray:
        return self._frame


class _CountingMotor:
    """Minimal motor double that records every motion command.

    ``get_position`` is read-only (commands no motion) and is NOT counted as a
    move; ``move_relative`` / ``move_to`` are.
    """

    def __init__(self) -> None:
        self.moves: list[tuple] = []
        self._x = self._y = self._z = 0.0

    def get_position(self):
        return _Pos(self._x, self._y, self._z)

    def move_relative(self, dx, dy, dz) -> None:
        self.moves.append(("rel", dx, dy, dz))
        self._x += dx
        self._y += dy
        self._z += dz

    def move_to(self, x, y, z) -> None:
        self.moves.append(("abs", x, y, z))
        self._x, self._y, self._z = x, y, z


class _Pos:
    def __init__(self, x, y, z) -> None:
        self.x_mm, self.y_mm, self.z_mm = x, y, z


class _SpyGate:
    """Records the action it was asked to confirm (and the move count at the
    moment of the call), then answers ``answer``."""

    def __init__(self, answer: bool, motor: _CountingMotor) -> None:
        self._answer = answer
        self._motor = motor
        self.actions: list[DangerAction] = []
        self.moves_at_confirm: list[int] = []

    def confirm(self, action: DangerAction) -> bool:
        self.actions.append(action)
        self.moves_at_confirm.append(len(self._motor.moves))
        return self._answer


# --------------------------------------------------------------------------- #
# (a) confirmation is requested, with a motion description, before any move    #
# --------------------------------------------------------------------------- #

def test_confirm_requested_before_any_move():
    motor = _CountingMotor()
    gate = _SpyGate(answer=True, motor=motor)
    tester = RepeatabilityTester(motor, _FakeCamera(), gate=gate)

    tester.run(n=2, approach_mm=3.0, settle_s=0.0)

    assert len(gate.actions) == 1, "exactly one run-level confirmation expected"
    action = gate.actions[0]
    assert action.kind == "move"
    # Description must carry the real motion facts: cycles, axes, excursion.
    assert "2" in action.summary and "3" in action.summary
    assert action.detail["n_cycles"] == 2
    assert action.detail["excursion_mm"] == 3.0
    assert action.detail["axes"] == ["X", "Y"]
    # The confirmation happened BEFORE any move was commanded.
    assert gate.moves_at_confirm[0] == 0


# --------------------------------------------------------------------------- #
# (b) a denied confirmation performs zero motion                              #
# --------------------------------------------------------------------------- #

def test_denied_confirmation_performs_no_motion():
    motor = _CountingMotor()
    gate = DenyAllGate()
    tester = RepeatabilityTester(motor, _FakeCamera(), gate=gate)

    result = tester.run(n=5, approach_mm=4.0, settle_s=0.0)

    assert motor.moves == [], "a denied confirmation must command no motion"
    assert result.n == 0, "a denied run yields an empty (no-op) result"


# --------------------------------------------------------------------------- #
# (c) no gate → refuse, perform zero motion                                   #
# --------------------------------------------------------------------------- #

def test_no_gate_refuses_and_performs_no_motion():
    motor = _CountingMotor()
    tester = RepeatabilityTester(motor, _FakeCamera())  # no gate injected

    with pytest.raises(RuntimeError):
        tester.run(n=3, approach_mm=2.0, settle_s=0.0)

    assert motor.moves == [], "without a gate the tester must never move"


def test_no_gate_refuses_calibration():
    motor = _CountingMotor()
    tester = RepeatabilityTester(motor, _FakeCamera())  # no gate injected

    with pytest.raises(RuntimeError):
        tester.calibrate(axis="x", dist_mm=5.0, settle_s=0.0)

    assert motor.moves == [], "without a gate calibration must never move"


# --------------------------------------------------------------------------- #
# (d) approved confirmation → run completes on the simulated backend          #
# --------------------------------------------------------------------------- #

def test_approved_run_completes_on_simulated_backend():
    motor = SimulatedMotorStage()
    motor.connect()
    motor.home()                   # real homing; sim stage is already at origin
    cam = _FakeCamera()
    tester = RepeatabilityTester(motor, cam, gate=AutoConfirmGate())

    result = tester.run(n=3, approach_mm=1.0, settle_s=0.0)

    assert result.n == 3, "an approved run should complete all requested cycles"
    # Stage is returned to the starting (target) point each cycle.
    pos = motor.get_position()
    assert pos.x_mm == pytest.approx(0.0, abs=1e-6)
    assert pos.y_mm == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# Wave-5 step 1: prepare_metrology_roi hookup + quality_min gate               #
# --------------------------------------------------------------------------- #

def _textured_frame(shape=(32, 32), seed=1):
    """A frame with real pixel-to-pixel texture -- clears the default
    quality_min=0.2 comfortably (numerically ~0.69, see test_image_prep.py)."""
    return np.random.default_rng(seed).standard_normal(shape)


def _blank_frame(shape=(32, 32), value=100.0):
    """A perfectly flat frame -- prepare_metrology_roi scores this exactly
    0.0 quality (no contrast, no edge energy survives the high-pass)."""
    return np.full(shape, value, dtype=np.float64)


class _SequencedCamera:
    """Connected camera that returns frames from a fixed list, one per
    ``get_frame()`` call, in order (the last frame repeats if called more
    times than the list has, so a test is not brittle to one extra grab).
    Lets a test script exactly which cycle sees which frame -- the first
    call feeds ``run()``'s reference grab, the rest feed the per-cycle
    grabs in order."""

    connected = True

    def __init__(self, frames: list) -> None:
        self._frames = frames
        self._i = 0

    def get_frame(self):
        frame = self._frames[min(self._i, len(self._frames) - 1)]
        self._i += 1
        return frame


def test_textured_frames_all_pass_quality_min_and_are_recorded():
    motor = _CountingMotor()
    gate = _SpyGate(answer=True, motor=motor)
    tester = RepeatabilityTester(motor, _FakeCamera(), gate=gate)

    result = tester.run(n=4, approach_mm=1.0, settle_s=0.0)

    assert result.n_low_quality == 0
    assert result.quality_flags == [False, False, False, False]
    assert result.n == 4, "every cycle's shift is trusted -> none excluded"


def test_injected_blank_frame_is_flagged_and_excluded_from_statistics():
    """One cycle out of four grabs a blank (zero-contrast) frame -- it must
    be flagged and dropped from `shifts_px` (and therefore from every
    derived statistic) while the other three cycles are unaffected. The
    stage motion itself is NOT gated on this (see _CountingMotor.moves)."""
    motor = _CountingMotor()
    gate = _SpyGate(answer=True, motor=motor)
    frames = [
        _textured_frame(seed=0),   # reference grab
        _textured_frame(seed=1),   # cycle 0: good
        _blank_frame(),            # cycle 1: LOW QUALITY -> excluded
        _textured_frame(seed=2),   # cycle 2: good
        _textured_frame(seed=3),   # cycle 3: good
    ]
    camera = _SequencedCamera(frames)
    tester = RepeatabilityTester(motor, camera, gate=gate)

    result = tester.run(n=4, approach_mm=1.0, settle_s=0.0)

    assert result.quality_flags == [False, True, False, False]
    assert result.n_low_quality == 1
    assert result.n == 3, "the blank cycle's shift must not reach shifts_px"
    # The move sequence itself is untouched by quality gating: 4 cycles x
    # 2 moves (away, back) = 8 commanded moves regardless of quality.
    assert len(motor.moves) == 8
    assert "excluded" in result.summary()


def test_all_low_quality_frames_exclude_every_cycle_but_still_complete():
    motor = _CountingMotor()
    gate = _SpyGate(answer=True, motor=motor)
    camera = _SequencedCamera([_blank_frame()])  # every grab returns blank
    tester = RepeatabilityTester(motor, camera, gate=gate)

    result = tester.run(n=3, approach_mm=1.0, settle_s=0.0)

    assert result.n_low_quality == 3
    assert result.quality_flags == [True, True, True]
    assert result.n == 0
    # std/p2p/radial-std must degrade to the documented "no data" defaults,
    # not raise, when every cycle was excluded.
    assert result.std_px() == (0.0, 0.0)
    assert result.p2p_px() == (0.0, 0.0)
    assert result.radial_std_px() == 0.0


def test_low_quality_reference_frame_warns_but_does_not_block_the_run(caplog):
    motor = _CountingMotor()
    gate = _SpyGate(answer=True, motor=motor)
    frames = [_blank_frame()] + [_textured_frame(seed=i) for i in range(3)]
    camera = _SequencedCamera(frames)
    tester = RepeatabilityTester(motor, camera, gate=gate)

    with caplog.at_level("WARNING"):
        result = tester.run(n=3, approach_mm=1.0, settle_s=0.0)

    assert result.n == 3, "a low-quality REFERENCE frame does not abort the run"
    assert any("reference frame quality" in r.message for r in caplog.records)


def test_quality_min_is_overridable():
    """A caller that lowers quality_min accepts frames the default would
    have excluded (the blank frame's quality is exactly 0.0, so
    quality_min=0.0 is the one value that admits it -- anything > 0.0 still
    excludes a perfectly flat frame)."""
    motor = _CountingMotor()
    gate = _SpyGate(answer=True, motor=motor)
    camera = _SequencedCamera([_blank_frame()])
    tester = RepeatabilityTester(motor, camera, gate=gate)

    result = tester.run(n=2, approach_mm=1.0, settle_s=0.0, quality_min=0.0)

    assert result.n_low_quality == 0
    assert result.n == 2


def test_roi_and_sigma_ctor_kwargs_are_applied_to_every_grab():
    """highpass_sigma_px/roi are per-instance overrides applied by _grab on
    every call (module docstring: "make sigma/ROI overridable via
    RepeatabilityTester ctor kwargs") -- verified via the returned
    PreparedROI shape (roi crops) rather than reaching into private state."""
    motor = _CountingMotor()
    gate = _SpyGate(answer=True, motor=motor)
    camera = _SequencedCamera([_textured_frame(shape=(32, 32), seed=s) for s in range(3)])
    tester = RepeatabilityTester(
        motor, camera, gate=gate, roi=(4, 4, 16, 16), highpass_sigma_px=5.0,
    )

    prepared = tester._grab(settle_s=0.0)

    assert prepared.image.shape == (16, 16)
