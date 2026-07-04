"""
PI Mercury / GCS motor stage driver.

Communicates via the PI GCS Python binding (pipython).  If pipython is not
installed, import will succeed but connect() will raise DeviceError.

Config keys (from devices.yaml → motor_stage section):
    controller:   "C-863" | "C-884" | "E-873" | ... (GCS controller ID string)
    serial_port:  "COM3"  (used for USB-serial; ignored if using USB/TCPIP)
    baudrate:     115200
    axes:         [1, 2, 3]   (axis IDs for X, Y, Z respectively)
    velocity:     5.0         (mm/s, applied to all axes at connect time)
"""
from __future__ import annotations

import time
import logging
from typing import Any

from .base import DeviceError
from .motor_base import MotorStageBase, MotorLimitError, MotorHomingError, Position

logger = logging.getLogger(__name__)


class PIMotorStage(MotorStageBase):
    """
    Concrete motor stage driver for PI GCS controllers (Mercury C-863,
    C-884, E-873, etc.).

    Replace this class with another MotorStageBase subclass to use a
    different motor system (e.g. Thorlabs APT, Newport SMC100,
    Standa 8SMC) without changing any other module.
    """

    def __init__(
        self,
        controller: str = "C-863",
        serial_port: str = "COM3",
        baudrate: int = 115200,
        axes: list[int] | None = None,
        velocity_mm_s: float = 5.0,
        simulation: bool = False,
    ) -> None:
        super().__init__(simulation=simulation)
        self._controller_id = controller
        self._serial_port = serial_port
        self._baudrate = baudrate
        self._axes: list[int] = axes if axes is not None else [1, 2, 3]
        self._velocity = velocity_mm_s
        self._gcs: Any = None   # pipython GCSDevice instance

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        if self._connected:
            return
        try:
            from pipython import GCSDevice, pitools  # type: ignore[import]
        except ImportError as exc:
            raise DeviceError(
                "pipython is not installed. "
                "Run: pip install pipython"
            ) from exc

        self._pitools = pitools
        dev = GCSDevice(self._controller_id)
        try:
            dev.ConnectRS232(self._serial_port, self._baudrate)
        except Exception as exc:
            raise DeviceError(f"PI connect failed: {exc}") from exc

        self._gcs = dev
        # Set default velocity on all axes
        axis_ids = [str(a) for a in self._axes]
        self._gcs.VEL(axis_ids, [self._velocity] * len(axis_ids))
        self._connected = True
        logger.info("PI stage connected on %s", self._serial_port)

    def disconnect(self) -> None:
        if self._gcs is not None:
            try:
                self._gcs.CloseConnection()
            except Exception:
                pass
        self._gcs = None
        self._connected = False
        self._homed = False
        logger.info("PI stage disconnected")

    # ------------------------------------------------------------------ #
    # MotorStageBase interface                                            #
    # ------------------------------------------------------------------ #

    def get_position(self) -> Position:
        self._require_connected()
        pos = self._gcs.qPOS(self._axis_ids())
        vals = list(pos.values())
        return Position(x_mm=vals[0], y_mm=vals[1], z_mm=vals[2] if len(vals) > 2 else 0.0)

    def is_moving(self) -> bool:
        if not self._connected or self._gcs is None:
            return False
        try:
            moving = self._gcs.IsMoving(self._axis_ids())
            return any(moving.values())
        except Exception:
            return False

    def at_limit_switch(self) -> dict[str, bool]:
        self._require_connected()
        result: dict[str, bool] = {}
        for i, label in zip(self._axes, ["x", "y", "z"]):
            try:
                lim = self._gcs.qLIM(str(i))
                result[f"{label}_neg"] = bool(lim.get(f"{i}_1", False))
                result[f"{label}_pos"] = bool(lim.get(f"{i}_2", False))
            except Exception:
                result[f"{label}_neg"] = False
                result[f"{label}_pos"] = False
        return result

    def home(self, axes: list[str] | None = None) -> None:
        self._require_connected()
        ids = self._axis_ids() if axes is None else axes
        try:
            self._pitools.startup(self._gcs, stages=None, refmodes="FRF", axes=ids)
        except Exception as exc:
            raise MotorHomingError(f"Homing failed: {exc}") from exc
        self._homed = True
        logger.info("PI stage homed")

    def move_to(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        self._require_connected()
        self._require_homed()
        pos = Position(x_mm, y_mm, z_mm)
        self._check_limits(pos)
        ids = self._axis_ids()
        targets = [x_mm, y_mm, z_mm][: len(ids)]
        try:
            self._gcs.MOV(ids, targets)
        except Exception as exc:
            raise DeviceError(f"PI MOV failed: {exc}") from exc

    def move_relative(self, dx_mm: float, dy_mm: float, dz_mm: float) -> None:
        cur = self.get_position()
        self.move_to(cur.x_mm + dx_mm, cur.y_mm + dy_mm, cur.z_mm + dz_mm)

    def stop(self) -> None:
        if self._gcs is not None:
            try:
                self._gcs.STP()
            except Exception:
                pass
        logger.warning("PI stage STOP issued")

    def zero_position(self) -> None:
        """Set current position as the software origin (work-coordinate offset)."""
        self._require_connected()
        if self._gcs is not None:
            # PI GCS: define current position as 0 on all axes
            for ax in self._axis_ids():
                try:
                    self._gcs.DFH(ax)   # Define home position at current location
                except Exception:
                    pass
        self._pos = Position(0.0, 0.0, 0.0)
        self._homed = True

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _axis_ids(self) -> list[str]:
        return [str(a) for a in self._axes]

    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError("Motor stage is not connected.")
