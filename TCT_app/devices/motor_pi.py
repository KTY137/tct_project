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

import threading  # noqa: F401  (used in the transport_lock annotation)
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

    Transport serialisation
    -----------------------
    One GCS session is shared by the GUI position poller and the scan thread.
    Every method that talks to ``self._gcs`` therefore holds
    ``BaseDevice.io_lock`` (== :attr:`transport_lock`) around each exchange, so
    a ``qPOS`` from the poller can never land inside a ``MOV``/``IsMoving``
    exchange from the mover.  The lock is taken PER EXCHANGE and released
    between polls (see :meth:`_wait_on_target`), never held across a whole
    move — otherwise the position display would freeze for the length of every
    move and the stop path would queue behind it.  ``stop()`` is the one
    deliberate exception; read its comment before changing anything here.
    """

    # Emergency-stop lock policy — resolved by
    # docs/research/pi_gcs_stop_semantics.md (supersedes the earlier
    # TODO(manual needed) from commit 4a89647).
    #
    # An emergency stop must never be queued behind the move it is supposed to
    # interrupt.  GRBLMotorStage gets that for free: its stop is a GRBL
    # real-time byte (0x85) the controller acts on straight out of the serial
    # buffer, sent WITHOUT the transport lock.
    #
    # PI/GCS gets the same property via the single-character #24 stop
    # (pipython ``GCSDevice.StopAll()`` == ``chr(24)``): pipython's message
    # layer serialises each exchange with its OWN internal lock, released
    # between polls, so a ``StopAll()`` from the abort thread waits at most one
    # in-flight exchange (~ms), never a whole move.  Therefore ``stop()`` takes
    # NO io_lock (read its comment).  ``StopAll(noraise=True)`` also reads-and-
    # masks GCS error 10 ("controller was stopped by command"), so the next
    # command does not inherit it.  The #24-vs-STP/HLT choice, the error-10
    # latch/clear, and the qONT/qOSN on-target signal are all sourced in the
    # research note.
    #
    # TODO(bench): confirm on the real C-663 Mercury Step + L-836 —
    #   (a) ``StopAll()`` halts a running FRF/MOV with sub-command latency
    #       (should be indistinguishable from instant).  Command-layer facts in
    #       the note are from PI's pipython + the E-727 GCS 2.0 manual; a
    #       C-663-firmware-specific quirk (StopAll / HasqONT / HasqOSN support)
    #       is not individually verified.
    #   (b) a ``MOV`` is accepted after ``StopAll`` + error-clear WITHOUT
    #       re-homing.  #24 latches error 10 but should not disable the servo
    #       (that is the harder #27) — not verbatim-confirmed for C-663
    #       firmware.  Fail-safe either way: a refused MOV surfaces as
    #       DeviceError via _require_homed / the MOV guard.
    #
    # The bounded acquire below belongs to ``disconnect()``'s CloseConnection
    # ONLY (a teardown arriving mid-move must still complete) — NOT to stop().
    _DISCONNECT_LOCK_TIMEOUT_S = 0.25

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
        self._pitools: Any = None   # pipython.pitools module (set in connect)

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    @property
    def transport_lock(self) -> "threading.RLock":
        """The lock every GCS exchange in this driver takes.

        This driver serialises on the inherited :attr:`BaseDevice.io_lock`, so
        the default accessor would already be correct — it is spelled out here
        only so the guarantee is explicit and cannot be silently lost if the
        driver ever grows a private lock.  Re-entrant, so a caller may hold it
        across a sequence of driver calls (each of which locks again).
        ``stop()`` never blocks on it (see the class comment).
        """
        return self.io_lock

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

        with self.io_lock:
            self._gcs = dev
            # Set default velocity on all axes
            axis_ids = [str(a) for a in self._axes]
            self._gcs.VEL(axis_ids, [self._velocity] * len(axis_ids))
            self._connected = True
        logger.info("PI stage connected on %s", self._serial_port)

    def disconnect(self) -> None:
        # Stop FIRST — mirror GRBLMotorStage.disconnect (motor_grbl.py:345).  A
        # disconnect that arrives mid-move must not leave the PI stage moving
        # with no session left to stop it, so we issue the emergency stop while
        # the GCS session is still reachable.  stop() reads self._gcs and gates
        # on it being non-None (it does NOT gate on self._connected), so it must
        # run BEFORE the swap below that nulls self._gcs — nulling first would
        # make the stop a silent no-op.  stop() is now lock-free (issues
        # #24/StopAll without io_lock) and non-raising (it swallows StopAll/qERR
        # failures internally), but we still guard the call so a stop failure can
        # never abort the teardown.
        try:
            self.stop()
        except Exception:
            pass
        gcs, self._gcs = self._gcs, None
        # Mark disconnected before CloseConnection: a poller that is queued on
        # the transport lock must not fire another exchange into a session we
        # are tearing down.
        self._connected = False
        self._homed = False
        if gcs is not None:
            # Bounded acquire, not a blocking one: a disconnect that arrives
            # while a long move holds the transport must still complete (and a
            # blocking one would hang the shutdown path for the whole move).
            got = self.io_lock.acquire(timeout=self._DISCONNECT_LOCK_TIMEOUT_S)
            try:
                gcs.CloseConnection()
            except Exception:
                pass
            finally:
                if got:
                    self.io_lock.release()
        logger.info("PI stage disconnected")

    # ------------------------------------------------------------------ #
    # MotorStageBase interface                                            #
    # ------------------------------------------------------------------ #

    def get_position(self) -> Position:
        self._require_connected()
        ids = self._axis_ids()
        # One exchange, exclusive: the GUI poller calls this while the scan
        # thread is inside MOV / IsMoving on the same GCS session.
        with self.io_lock:
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
            with self.io_lock:
                moving = self._gcs.IsMoving(self._axis_ids())
            return any(moving.values())
        except Exception:
            return False

    def at_limit_switch(self) -> dict[str, bool]:
        self._require_connected()
        result: dict[str, bool] = {}
        # Whole sweep under one acquisition → a coherent snapshot of the three
        # axes, and no other thread's exchange lands between the qLIM queries.
        with self.io_lock:
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
            # pitools.startup() runs its own poll loop inside pipython, so the
            # transport must be held EXCLUSIVELY for the whole referencing move —
            # it cannot be sliced per exchange the way _wait_on_target is.  Cost:
            # a concurrent get_position() blocks until homing finishes (the
            # position display freezes, it does not garble).  stop() is unaffected
            # (bounded acquire + fall-through), which is the property that matters.
            with self.io_lock:
                # startup() enables the servo where applicable and runs the
                # reference move (FRF/FNL/FPL) for each axis, then waits until
                # referenced.
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
        self._check_limits(pos)          # soft-limit gate, unchanged
        ids = self._axis_ids()
        targets = [x_mm, y_mm, z_mm][: len(ids)]
        try:
            # Only the MOV exchange is guarded — NOT the wait below it.  MOV is
            # asynchronous (it returns as soon as the controller accepts it), so
            # the lock is held for one short exchange, not for the whole move.
            with self.io_lock:
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
        # Emergency stop = single-character #24 (GCS "stop all axes", immediate),
        # sent via pipython StopAll().  NOT the STP mnemonic (a normal
        # LF-terminated command line) and — crucially — NOT under io_lock:
        # pipython serialises each exchange with its own internal lock released
        # between polls, so this #24 byte waits at most one in-flight exchange
        # (~ms), never a whole move (the GRBL-0x85-shaped lock-free stop the
        # class comment wants).  StopAll(noraise=True) also reads-and-masks GCS
        # error 10 ("controller was stopped by command") so the next command
        # does not inherit it.  Source: pipython gcscommands.StopAll (chr(24)) /
        # pitools.stopall; see docs/research/pi_gcs_stop_semantics.md.
        gcs = self._gcs
        if gcs is None:
            logger.warning("PI stage STOP requested while not connected — no-op")
            return
        try:
            gcs.StopAll(noraise=True)      # sends chr(24); masks E10_PI_CNTR_STOP
        except Exception as exc:
            # A stop path must never raise.
            logger.debug("PI StopAll raised (swallowed on the stop path): %s", exc)
        # Belt-and-suspenders: if this pipython build has errcheck OFF, StopAll
        # may leave error 10 latched; a best-effort qERR() reports AND clears it
        # (error 10 is cleared by READING it), so the abort's next command does
        # not look like a second fault.  Must never raise.
        try:
            gcs.qERR()
        except Exception:
            pass
        logger.warning("PI stage STOP issued (#24 StopAll)")

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
            with self.io_lock:
                for ax in self._axis_ids():
                    try:
                        self._gcs.DFH(ax)   # Define home at the current location
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

        Polls PI's own ``pitools.ontarget()`` ONE exchange at a time, taking the
        transport lock per poll and releasing it between polls — the same shape
        as ``GRBLMotorStage._grbl_wait_idle``.  The lock is deliberately NOT
        held across the whole wait: that would freeze the GUI position poller
        for the length of every move (up to ``move_timeout_s``) and put every
        other transport user behind it.

        ``pitools.ontarget`` reads the servo state once (``qSVO``) then selects a
        TARGET-RELATIVE arrival signal — ``qONT`` for closed-loop axes,
        ``qOSN`` (steps-left) for open-loop steppers (the L-836 default),
        falling back to ``IsMoving`` only if the controller supports neither.
        ``qONT``/``qOSN`` are defined against the NEWLY commanded target, so they
        cannot falsely read "on-target" in the window right after ``MOV`` is
        accepted but before motion physically starts — the start-race a raw
        ``IsMoving``-first poll would have (that ordering was backwards for
        race-safety).  Source: pipython pitools.ontarget; see
        docs/research/pi_gcs_stop_semantics.md.
        TODO(bench): on the real C-663 + L-836, confirm ontarget() reports
        arrival for a normal MOV.  Open- vs closed-loop default depends on the
        optional linear encoder / configured SVO; pitools.ontarget probes
        HasqONT/HasqOSN so it should degrade safely, but confirm on the bench.
        """
        pit = self._pitools
        if pit is None:
            # Lazy, safe import — no import-time hardware (rule 1).  connect()
            # normally sets self._pitools; this only fires if the wait is
            # reached without it (defensive, keeps the module top import-free).
            from pipython import pitools as pit  # type: ignore[import]
        deadline = time.monotonic() + self._move_timeout
        time.sleep(0.02)   # small "command taken up" guard (cf. pitools.waitonready)
        while time.monotonic() < deadline:
            try:
                with self.io_lock:
                    on_target = pit.ontarget(self._gcs, ids)
                # Empty dict → treat as not-yet-arrived (do not let all({}) == True
                # short-circuit into a false "done").
                if on_target and all(on_target.values()):
                    return
            except Exception:
                # Extremely defensive: if ontarget() itself errors, fall back to
                # a raw IsMoving check rather than spin.
                try:
                    with self.io_lock:
                        moving = self._gcs.IsMoving(ids)
                    if not any(moving.values()):
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
