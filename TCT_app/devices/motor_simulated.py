"""
Software simulation of a 3-axis motor stage.

Used for development, testing, and GUI iteration without any hardware.
Plug it in wherever a MotorStageBase is expected.
"""
from __future__ import annotations

import time
import threading

from .motor_base import MotorStageBase, MotorHomingError, Position


class SimulatedMotorStage(MotorStageBase):
    """
    Drop-in simulation for any MotorStageBase consumer.

    Simulates realistic move timing by sleeping for a duration
    proportional to the requested distance.
    """

    SPEED_MM_S = 10.0   # simulated stage speed

    def __init__(self, simulation: bool = True) -> None:
        super().__init__(simulation=simulation)
        self._pos = Position(0.0, 0.0, 0.0)
        self._target = Position(0.0, 0.0, 0.0)
        self._moving = False
        self._move_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        self._connected = True
        self.logger.info("SimulatedMotorStage connected")

    def disconnect(self) -> None:
        self.stop()
        self._connected = False
        self._homed = False
        self.logger.info("SimulatedMotorStage disconnected")

    # ------------------------------------------------------------------ #
    # MotorStageBase interface                                            #
    # ------------------------------------------------------------------ #

    def get_position(self) -> Position:
        return self._pos

    def is_moving(self) -> bool:
        return self._moving

    def at_limit_switch(self) -> dict[str, bool]:
        return {k: False for k in ("x_neg", "x_pos", "y_neg", "y_pos", "z_neg", "z_pos")}

    def home(self, axes: list[str] | None = None) -> None:
        self._require_connected()
        # Simulate move-to-origin
        self._blocking_move(Position(0.0, 0.0, 0.0))
        self._homed = True
        self.logger.info("SimulatedMotorStage homed")

    def move_to(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        self._require_connected()
        self._require_homed()
        target = Position(x_mm, y_mm, z_mm)
        self._check_limits(target)
        self._start_async_move(target)

    def move_relative(self, dx_mm: float, dy_mm: float, dz_mm: float) -> None:
        cur = self._pos
        self.move_to(cur.x_mm + dx_mm, cur.y_mm + dy_mm, cur.z_mm + dz_mm)

    def stop(self) -> None:
        self._stop_event.set()
        if self._move_thread and self._move_thread.is_alive():
            self._move_thread.join(timeout=1.0)
        self._moving = False

    def zero_position(self) -> None:
        """Declare current position as origin without moving.

        USER ORIGIN only — never machine home (see
        ``MotorStageBase.zero_position``).  ``_homed`` is deliberately left
        untouched so this twin keeps the SAME contract as the real backends:
        zeroing an un-homed stage leaves it un-homed and the next ``move_to``
        raises ``MotorHomingError``.
        """
        self._pos = Position(0.0, 0.0, 0.0)
        if not self._homed:
            self.logger.warning(
                "SimulatedMotorStage: zeroed while UN-HOMED — origin set, but the "
                "stage stays un-homed and moves remain refused until home()."
            )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _require_connected(self) -> None:
        if not self._connected:
            from .base import DeviceError
            raise DeviceError("SimulatedMotorStage is not connected.")

    def _distance(self, a: Position, b: Position) -> float:
        return ((b.x_mm - a.x_mm)**2 + (b.y_mm - a.y_mm)**2 + (b.z_mm - a.z_mm)**2) ** 0.5

    def _blocking_move(self, target: Position) -> None:
        dist = self._distance(self._pos, target)
        time.sleep(dist / self.SPEED_MM_S)
        self._pos = target

    def _start_async_move(self, target: Position) -> None:
        self._stop_event.clear()
        self._target = target

        def _run() -> None:
            self._moving = True
            dist = self._distance(self._pos, target)
            duration = dist / self.SPEED_MM_S
            start = time.monotonic()
            while True:
                if self._stop_event.is_set():
                    break
                elapsed = time.monotonic() - start
                if elapsed >= duration:
                    self._pos = target
                    break
                frac = elapsed / max(duration, 1e-9)
                self._pos = Position(
                    self._pos.x_mm + frac * (target.x_mm - self._pos.x_mm),
                    self._pos.y_mm + frac * (target.y_mm - self._pos.y_mm),
                    self._pos.z_mm + frac * (target.z_mm - self._pos.z_mm),
                )
                time.sleep(0.02)
            self._moving = False

        self._move_thread = threading.Thread(target=_run, daemon=True)
        self._move_thread.start()
