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
