"""
Abstract interface for motor stages.

To add a new motor controller:
  1. Subclass MotorStageBase.
  2. Implement every abstractmethod.
  3. Register the class in devices/__init__.py and configs/devices.yaml.

The rest of the application (scan controller, GUI) references only
MotorStageBase — no concrete class ever leaks past the device layer.
"""
from __future__ import annotations

import logging
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import NamedTuple

from .base import BaseDevice, DeviceError

_limits_logger = logging.getLogger("SoftwareLimits")


class MotorLimitError(DeviceError):
    """Raised when a requested move would exceed a software or hardware limit."""


class MotorHomingError(DeviceError):
    """Raised when homing fails or is required before the operation."""


class Position(NamedTuple):
    x_mm: float
    y_mm: float
    z_mm: float


@dataclass
class SoftwareLimits:
    x_min: float = -50.0
    x_max: float =  50.0
    y_min: float = -50.0
    y_max: float =  50.0
    z_min: float = -10.0
    z_max: float =  10.0

    def __post_init__(self) -> None:
        # Guarantee ``check()`` can trust its bounds: no dataclass instance —
        # however it was built (defaults, from_config, or a direct call) — is
        # ever left with an envelope that silently blocks all motion.
        self.validate()

    @classmethod
    def from_config(cls, cfg: dict) -> "SoftwareLimits":
        """Build from a devices.yaml software_limits block.

        The resulting instance is run through :meth:`validate` (via
        ``__post_init__``), so a swapped or zero-width envelope is caught and
        loudly logged here instead of silently refusing every move later.
        """
        return cls(
            x_min=cfg.get("x_min_mm", cls.x_min),
            x_max=cfg.get("x_max_mm", cls.x_max),
            y_min=cfg.get("y_min_mm", cls.y_min),
            y_max=cfg.get("y_max_mm", cls.y_max),
            z_min=cfg.get("z_min_mm", cls.z_min),
            z_max=cfg.get("z_max_mm", cls.z_max),
        )

    def validate(self) -> None:
        """Detect and neutralise an incoherent soft-limit envelope.

        Two failure classes silently block motion and must never pass unnoticed:

          * **Swapped bounds** (``min > max``) — ``check()`` refuses *every*
            position, so no move is ever accepted.  This is the exact bug that
            shipped in devices.yaml (x_min=300, x_max=0).  We auto-correct by
            swapping the pair in place and log a loud WARNING.  The real fix
            belongs in devices.yaml, which ``config_validator`` reports as an
            ERROR that blocks ``connect_all`` — auto-correction here only keeps
            the app launchable and the bounds coherent; it never authorises a
            real move on its own (a flagged config never connects).
          * **Zero-width axis** (``min == max``) — only a single point is
            reachable.  There is no correct width to invent, so we leave the
            values untouched but log a loud WARNING (the validator flags it too).

        Chosen behaviour is auto-correct-and-warn rather than *raise* because
        ``SoftwareLimits.from_config`` runs inside ``DeviceManager.__init__``,
        which is not guarded at application startup: raising there would prevent
        the app from launching at all on a bad config, whereas the established
        contract is that config errors are surfaced and *block connect_all*
        while the app still starts and shows what is wrong.
        """
        for lo_attr, hi_attr, axis in (
            ("x_min", "x_max", "X"),
            ("y_min", "y_max", "Y"),
            ("z_min", "z_max", "Z"),
        ):
            lo, hi = getattr(self, lo_attr), getattr(self, hi_attr)
            # Non-numeric bounds are a separate error class handled loudly by
            # config_validator; don't crash __post_init__ trying to compare them.
            if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
                continue
            if lo > hi:
                _limits_logger.warning(
                    "Software limits for %s axis are SWAPPED (min=%s > max=%s) — "
                    "auto-correcting to [%s, %s]. This envelope would otherwise "
                    "refuse EVERY move. Fix motor_stage.software_limits in "
                    "devices.yaml so %s_min_mm < %s_max_mm.",
                    axis, lo, hi, hi, lo, axis.lower(), axis.lower(),
                )
                setattr(self, lo_attr, hi)
                setattr(self, hi_attr, lo)
            elif lo == hi:
                _limits_logger.warning(
                    "Software limits for %s axis are ZERO-WIDTH (min == max == "
                    "%s) — only that single point is reachable, so the axis "
                    "cannot move. Widen motor_stage.software_limits.%s_min_mm / "
                    "%s_max_mm in devices.yaml.",
                    axis, lo, axis.lower(), axis.lower(),
                )

    def check(self, pos: Position) -> None:
        """Raise MotorLimitError if *pos* is outside any limit."""
        checks = [
            (pos.x_mm, self.x_min, self.x_max, "X"),
            (pos.y_mm, self.y_min, self.y_max, "Y"),
            (pos.z_mm, self.z_min, self.z_max, "Z"),
        ]
        for val, lo, hi, axis in checks:
            if not (lo <= val <= hi):
                raise MotorLimitError(
                    f"{axis} = {val:.4f} mm is outside software limits [{lo}, {hi}]"
                )


class MotorStageBase(BaseDevice):
    """
    Backend-agnostic interface for a 3-axis (X/Y/Z) motor stage.

    Concrete implementations:
        PIMotorStage        — PI Mercury / GCS serial controllers
        SimulatedMotorStage — software simulation for testing without hardware
    """

    def __init__(self, simulation: bool = False) -> None:
        super().__init__(simulation=simulation)
        self._homed = False
        self.limits = SoftwareLimits()

    # ------------------------------------------------------------------ #
    # State queries                                                        #
    # ------------------------------------------------------------------ #

    @property
    def homed(self) -> bool:
        return self._homed

    @abstractmethod
    def get_position(self) -> Position:
        """Return current (x, y, z) position in mm."""

    @abstractmethod
    def is_moving(self) -> bool:
        """Return True while any axis is in motion."""

    @abstractmethod
    def at_limit_switch(self) -> dict[str, bool]:
        """Return dict with keys like 'x_neg', 'x_pos', 'y_neg', etc."""

    # ------------------------------------------------------------------ #
    # Motion commands                                                      #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def home(self, axes: list[str] | None = None) -> None:
        """
        Home the specified axes (or all if *axes* is None).
        Sets self._homed = True on success.
        """

    @abstractmethod
    def move_to(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        """
        Command an absolute move.  Checks software limits before issuing
        the command and raises MotorLimitError / MotorHomingError as needed.
        """

    @abstractmethod
    def move_relative(self, dx_mm: float, dy_mm: float, dz_mm: float) -> None:
        """Command a relative move from the current position."""

    @abstractmethod
    def stop(self) -> None:
        """Immediately halt all axes.  Safe to call at any time."""

    @abstractmethod
    def zero_position(self) -> None:
        """
        Declare the current physical position as (0, 0, 0) in software
        without moving the stage.  Equivalent to G92 X0 Y0 Z0 in G-code.
        Useful for setting a local scan origin after homing.
        """

    # ------------------------------------------------------------------ #
    # Convenience helpers (concrete, may be overridden)                   #
    # ------------------------------------------------------------------ #

    def move_to_center(self) -> None:
        """Centre X/Y in the soft-limit envelope, keeping Z where it is.

        Backends with their own coordinate frame (e.g. GRBL's user/machine
        split) override this; the default centres X/Y at the midpoint of
        ``limits`` and leaves Z unchanged.
        """
        if self.limits is None:
            return
        lim = self.limits
        cur = self.get_position()
        self.move_to(
            (lim.x_min + lim.x_max) / 2.0,
            (lim.y_min + lim.y_max) / 2.0,
            cur.z_mm,
        )

    def test_connection(self) -> str:
        """Probe the controller and return a human-readable status line.

        Used by the GUI's "Test Connection" button to confirm the link before
        homing.  Backends that speak G-code override this with a real firmware
        handshake (e.g. M115 / $I); the default only reports connection state.
        """
        if self.simulation:
            return "Simulation mode — no hardware to query."
        if not self._connected:
            return "Not connected."
        return "Connected (no firmware query implemented for this backend)."

    def wait_until_ready(self, timeout_s: float = 30.0, poll_s: float = 0.05) -> None:
        """Block until all axes have stopped moving or *timeout_s* elapses."""
        deadline = time.monotonic() + timeout_s
        while self.is_moving():
            if time.monotonic() > deadline:
                raise DeviceError(
                    f"Motor stage did not reach target within {timeout_s:.1f} s"
                )
            time.sleep(poll_s)

    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError("Motor stage is not connected.")

    def _require_homed(self) -> None:
        if not self._homed:
            raise MotorHomingError("Stage must be homed before issuing moves.")

    def _check_limits(self, pos: Position) -> None:
        self.limits.check(pos)
