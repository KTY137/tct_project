"""
PI (Physik Instrumente) GCS motor stage driver.

Communicates via the PI GCS Python binding (pipython).  If pipython is not
installed, import will succeed but connect() will raise DeviceError.

Tested target: three PI **L-836** stages (X/Y/Z).  The L-836 is a 2-phase
stepper linear stage (25 mm standard travel, up to 80 mm on longer strokes,
optional linear encoder) driven by a PI stepper controller (C-663 Mercury Step
single-axis, daisy-chained, or a multi-axis C-884).  Notes that matter here:

* **Referencing**: L-836 has a reference switch, so ``FRF`` (reference move) is
  the correct homing mode.  If your unit only exposes limit switches, set
  ``ref_mode: FNL`` (negative limit) in devices.yaml.
* **Async motion**: GCS ``MOV`` returns immediately — the stage is still moving.
  ``move_to``/``home`` therefore wait for on-target before returning, otherwise a
  scan would acquire mid-move.
* **Travel vs soft limits**: keep ``software_limits`` inside the physical travel
  (e.g. ±12.5 mm for a 25 mm stage referenced at centre), or moves are refused.

Config keys (from devices.yaml → motor_stage section):
    controller:   "C-663" | "C-884" | "C-863" | "E-873" | ... (GCS controller ID)
    serial_port:  "COM3"  (used for USB-serial; ignored if using USB/TCPIP)
    baudrate:     115200
    axes:         [1, 2, 3]   (axis IDs for X, Y, Z respectively)
    velocity:     5.0         (mm/s, applied to all axes at connect time)
    ref_mode:     "FRF"       (reference move; use "FNL"/"FPL" for limit homing)
    move_timeout_s: 60.0
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
        controller: str = "C-663",
        serial_port: str = "COM3",
        baudrate: int = 115200,
        axes: list[int] | None = None,
        velocity_mm_s: float = 5.0,
        ref_mode: str = "FRF",
        move_timeout_s: float = 60.0,
        simulation: bool = False,
        **_kwargs: Any,
    ) -> None:
        super().__init__(simulation=simulation)
        self._controller_id = controller
        self._serial_port = serial_port
        self._baudrate = baudrate
        self._axes: list[int] = axes if axes is not None else [1, 2, 3]
        self._velocity = velocity_mm_s
        self._ref_mode = str(ref_mode).upper()
        self._move_timeout = float(move_timeout_s)
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
        ids = self._axis_ids()
        pos = self._gcs.qPOS(ids)
        # Index by the queried axis id (do NOT rely on dict value ordering, which
        # is not guaranteed to match the physical X/Y/Z axis assignment).
        def _ax(i: int) -> float:
            if i >= len(ids):
                return 0.0
            key = ids[i]
            return float(pos.get(key, pos.get(int(key), 0.0)))
        return Position(x_mm=_ax(0), y_mm=_ax(1), z_mm=_ax(2))

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
            # startup() enables the servo where applicable and runs the reference
            # move (FRF/FNL/FPL) for each axis, then waits until referenced.
            self._pitools.startup(self._gcs, stages=None,
                                  refmodes=[self._ref_mode] * len(ids), axes=ids)
            # Re-apply the configured velocity — startup() can reset it.
            self._gcs.VEL(ids, [self._velocity] * len(ids))
        except Exception as exc:
            raise MotorHomingError(f"Homing failed: {exc}") from exc
        self._homed = True
        logger.info("PI stage homed (ref_mode=%s)", self._ref_mode)

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
        # GCS MOV is asynchronous — block until the axes report on-target, else a
        # scan would acquire while the stage is still moving.
        self._wait_on_target(ids)

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
        """Declare the current position as the origin.

        CAVEAT: this uses GCS ``DFH`` (Define Home), which redefines the home
        position used by a *future* ``FRF`` reference move — so re-homing after a
        "Zero Here" will return to this spot, not the reference switch.  The soft
        limits in ``devices.yaml`` are also expressed in the pre-DFH frame, so
        keep the two consistent.  (If this proves surprising in practice, switch
        to a pure software display offset like GRBLMotorStage._zero, which never
        touches the controller's coordinate system.)

        Sets a USER ORIGIN, **not** machine home: ``_homed`` is deliberately left
        untouched (see ``MotorStageBase.zero_position``).  ``DFH`` only redefines
        where a *future* ``FRF`` reference move lands — it does not perform one,
        so it cannot establish the referencing this stage still needs.  Zeroing an
        un-referenced stage therefore leaves it un-homed and the next move is
        refused by ``_require_homed``.
        """
        self._require_connected()
        if self._gcs is not None:
            for ax in self._axis_ids():
                try:
                    self._gcs.DFH(ax)   # Define home position at current location
                except Exception:
                    pass
        self._pos = Position(0.0, 0.0, 0.0)
        if not self._homed:
            logger.warning(
                "PIMotorStage: zeroed while UN-HOMED — DFH redefined the origin, "
                "but the stage is still un-referenced (no FRF), so moves remain "
                "refused until home() runs.  Home first, then zero."
            )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _wait_on_target(self, ids: list[str]) -> None:
        """Block until every axis in *ids* reports on-target (or timeout).

        Prefers pitools.waitontarget (honours servo-on-target ``qONT?``); falls
        back to polling ``IsMoving`` so it also works for open-loop steppers.
        """
        deadline = time.monotonic() + self._move_timeout
        time.sleep(0.02)   # let the move actually start before polling
        waiton = getattr(self._pitools, "waitontarget", None)
        if waiton is not None:
            try:
                waiton(self._gcs, axes=ids, timeout=self._move_timeout)
                return
            except Exception as exc:
                logger.debug("waitontarget failed, polling IsMoving: %s", exc)
        while time.monotonic() < deadline:
            try:
                if not any(self._gcs.IsMoving(ids).values()):
                    return
            except Exception:
                # Some controllers reject IsMoving mid-move; try qONT? instead.
                try:
                    if all(self._gcs.qONT(ids).values()):
                        return
                except Exception:
                    return
            time.sleep(0.02)
        raise DeviceError(
            f"PI move did not complete within {self._move_timeout:.0f} s "
            "(check servo, referencing and that the target is within travel)."
        )

    def _axis_ids(self) -> list[str]:
        return [str(a) for a in self._axes]

    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError("Motor stage is not connected.")
