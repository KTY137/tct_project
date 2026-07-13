"""
GRBL-based motor stage backend.

Works with any 3-axis CNC/3D-printer controller running GRBL firmware
(also compatible with Marlin in G-code mode).

Communication is plain G-code over a serial (USB-CDC) connection.

Coordinate system
-----------------
GRBL uses machine coordinates after homing ($H) and work coordinates
otherwise.  We always home first and then use absolute machine coords
(G90 + G53) so the TCT coordinate frame matches the physical stage.

Supported firmwares
-------------------
- GRBL 1.1h (CNC shield / Arduino Uno/Nano)
- GRBL-Mega / GRBL-ESP32 (more axes)
- Marlin 2.x  (3D-printer boards — set marlin: true in YAML)

For Marlin, homing is G28 and position query is M114 instead of '?'.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import serial as _serial  # only for type checker; runtime import is deferred

from .motor_base import MotorStageBase, MotorHomingError, Position, SoftwareLimits
from .base import DeviceError


# Regex for GRBL status report: <Idle|MPos:x,y,z|...>
# Accepts either MPos: (machine, $10 bit0 set — the default) or WPos: (work,
# when $10=0) so the position display keeps working regardless of report mask.
_GRBL_STATUS = re.compile(
    r"<(\w+)[^>]*[MW]Pos:([-\d.]+),([-\d.]+),([-\d.]+)"
)
# Regex for Marlin M114 reply: X:0.00 Y:0.00 Z:0.00
# Anchored to start-of-line and requires a decimal point so the
# "Count X:9360 Y:9360 Z:0" step-count suffix is never matched.
_MARLIN_POS = re.compile(
    r"^X:([-\d]+\.\d+)\s+Y:([-\d]+\.\d+)\s+Z:([-\d]+\.\d+)"
)

# M114 robustness (bench-captured from a real CR-10S / Marlin 2.1.2.8):
#   * The FIRST M114 in a burst is silently dropped — no position line and no
#     'ok' ever arrive — so a single query is unreliable and must be retried.
#   * Retrying (rather than returning a stale cache) is the safety fix: a caller
#     acting on a wrong position drives an absolute move to the wrong place and
#     validates soft limits against a lie.
_MARLIN_M114_ATTEMPTS = 3
_MARLIN_M114_ATTEMPT_TIMEOUT_S = 1.5


class GRBLMotorStage(MotorStageBase):
    """
    3-axis motor stage driven by a GRBL (or Marlin) controller over RS-232/USB.

    Config keys in devices.yaml (under motor_stage):
        serial_port   : e.g. "COM5" or "/dev/ttyUSB0"
        baudrate      : 115200  (GRBL default)
        feed_rate_mm_min : 3000  (mm/min, GRBL uses F parameter)
        marlin        : false   (set true for Marlin firmware)
        poll_interval_s : 0.05  (position poll interval while moving)
    """

    def __init__(
        self,
        serial_port: str = "COM5",
        baudrate: int = 115200,
        feed_rate_mm_min: float = 3000.0,
        marlin: bool = False,
        poll_interval_s: float = 0.05,
        home_to_center: bool = True,
        steps_per_mm: Any = 80.0,
        microsteps: int = 16,
        snap_mode: str = "off",
        push_steps_to_grbl: bool = False,
        simulation: bool = False,
        **_kwargs: Any,
    ) -> None:
        super().__init__(simulation=simulation)
        self._port = serial_port
        self._baud = baudrate
        self._feed = feed_rate_mm_min
        self._marlin = marlin
        self._poll = poll_interval_s
        # Drive the stage to the centre of the soft-limit envelope right after
        # homing, so it parks at a safe, known, in-range location.
        self._home_to_center = home_to_center
        self._ser: _serial.Serial | None = None
        # Serialises the serial link.  RE-ENTRANT: a caller may hold the
        # transport lock (see ``transport_lock``) across a sequence of driver
        # calls, and those calls take it again on the same thread.  Everything
        # else about it is unchanged — every acquisition is a plain
        # ``with self._lock:`` around one exchange, and ``stop()`` still takes
        # it NEVER (see the comment there).
        self._lock = threading.RLock()
        # ``_pos`` is always stored in MACHINE coordinates (what GRBL's MPos
        # reports).  The GUI sees a *user* frame = machine - ``_offset()``.
        self._pos = Position(0.0, 0.0, 0.0)
        # App-side display origin, expressed in machine coordinates.  None means
        # "auto" → use the lower soft-limit corner so the displayed coordinates
        # start out positive (0 … travel).  ``zero_position`` sets it to the
        # current machine position so the live point reads (0, 0, 0).
        # This is purely software: GRBL's own G54/G92 offsets are never touched,
        # and absolute moves are sent in machine coordinates via G53.
        self._zero: Position | None = None

        # ── Microstepping / full-step snapping ───────────────────────────
        # steps_per_mm mirrors GRBL $100/$101/$102 (microsteps per mm).
        self._steps_per_mm = self._norm_axis(steps_per_mm, 80.0)
        self._microsteps = int(microsteps) if microsteps else 16
        self._push_steps = bool(push_steps_to_grbl)
        # "off" → keep full microstep resolution; "full" → quantise every target
        # to the nearest mechanical full-step detent so the motor parks on a
        # stable detent and does not hunt/oscillate (which overheats the A4988).
        self._snap_mode = str(snap_mode or "off").lower()
        # Stall guard: if MPos stops advancing while GRBL still reports motion
        # (driver overheated / lost steps) abort instead of waiting out the move.
        self._stall_eps_mm = 0.01
        self._stall_timeout_s = 5.0

    @staticmethod
    def _norm_axis(val: Any, default: float) -> dict[str, float]:
        """Normalise a scalar | dict | None into an {x, y, z} float dict."""
        if isinstance(val, dict):
            return {a: float(val.get(a, val.get(a.upper(), default)))
                    for a in ("x", "y", "z")}
        v = default if val is None else float(val)
        return {"x": v, "y": v, "z": v}

    def _full_step_mm(self, axis: str) -> float:
        """Mechanical detent spacing for *axis* = microsteps / steps_per_mm.

        Independent of the microstep setting itself (both scale together), so
        this is the true distance between the motor's stable rest positions.
        """
        spm = self._steps_per_mm.get(axis, 80.0)
        return self._microsteps / spm if spm > 0 else 0.0

    def _snap(self, m: Position) -> Position:
        """Round a machine position to the nearest full-step detent per axis
        (only when snap_mode == 'full'; otherwise returned unchanged)."""
        if self._snap_mode != "full":
            return m

        def q(v: float, axis: str) -> float:
            grid = self._full_step_mm(axis)
            return round(v / grid) * grid if grid > 0 else v

        return Position(q(m.x_mm, "x"), q(m.y_mm, "y"), q(m.z_mm, "z"))

    def _snap_relative(self, cur: Position, target: Position,
                       deltas: tuple[float, float, float]) -> Position:
        """Snap *target* to detents, but guarantee any axis with a non-zero
        request still advances at least one full step in its direction — so jog
        clicks smaller than a detent are not silently swallowed."""
        snapped = self._snap(target)
        out = []
        for axis, d, c, s in zip("xyz", deltas, cur, snapped):
            grid = self._full_step_mm(axis)
            if d != 0 and grid > 0 and abs(s - c) < grid / 2.0:
                s = (round(c / grid) + (1 if d > 0 else -1)) * grid
            out.append(s)
        return Position(*out)

    # ------------------------------------------------------------------ #
    # BaseDevice interface                                                 #
    # ------------------------------------------------------------------ #

    @property
    def transport_lock(self) -> "threading.RLock":
        """The lock this driver's I/O actually takes — its serial-command lock.

        NOT ``BaseDevice.io_lock``: every exchange here (``_send``,
        ``_send_wait``, ``_collect``, ``_grbl_status``, the Marlin M114 paths)
        is guarded by ``self._lock``, and ``io_lock`` is never touched.  A
        caller that held ``io_lock`` instead would interleave with the driver
        anyway, so the accessor must return the real one.

        ``stop()`` deliberately does not take this lock and must never be made
        to (see its comment): holding the transport lock therefore blocks
        moves and status polls, but never the emergency stop.
        """
        return self._lock

    def connect(self) -> None:
        if self.simulation:
            self._connected = True
            self.logger.info("GRBLMotorStage: simulation mode")
            return
        try:
            import serial  # pyserial — optional dependency
        except ImportError as exc:
            raise DeviceError(
                "pyserial is not installed. Run: pip install pyserial"
            ) from exc
        try:
            # Both read AND write timeouts are explicit: without write_timeout a
            # write to a wedged/unplugged port blocks forever — which would also
            # hang the emergency stop() (it writes the jog-cancel / M410).  With
            # it, a stuck write raises SerialTimeoutException promptly and the
            # caller fails safe instead of freezing.
            self._ser = serial.Serial(
                self._port, self._baud, timeout=2.0, write_timeout=2.0,
            )
            time.sleep(2.0)          # GRBL sends welcome banner on connect
            # Auto-detect the firmware dialect and let it win over the config —
            # a wrong ``marlin:`` flag otherwise sends the wrong homing /
            # position / stop commands and desyncs the coordinate frame.
            detected = self._detect_firmware()
            if detected is not None:
                detected_marlin = detected == "marlin"
                if detected_marlin != self._marlin:
                    self.logger.warning(
                        "Firmware auto-detect: controller on %s speaks %s but "
                        "devices.yaml says marlin=%s — using %s.  Fix "
                        "motor_stage.marlin AND check that software_limits use "
                        "the matching sign convention (GRBL homes to a negative "
                        "envelope, Marlin to a positive one).",
                        self._port, detected.upper(), self._marlin, detected.upper(),
                    )
                    self._marlin = detected_marlin
            else:
                self.logger.warning(
                    "Firmware auto-detect inconclusive on %s — trusting "
                    "marlin=%s from devices.yaml", self._port, self._marlin,
                )
            self._ser.reset_input_buffer()
            self._connected = True   # set before _send_wait so it is permitted
            if not self._marlin:
                self._grbl_reset_clean()
            else:
                # Spend the known-unreliable first-after-reset M114 now so the
                # first real get_position() is clean (best-effort, never moves).
                self._marlin_prime()
            self.logger.info(
                "GRBLMotorStage connected on %s @ %d baud (marlin=%s)",
                self._port, self._baud, self._marlin,
            )
        except DeviceError:
            self._connected = False
            raise
        except Exception as exc:
            self._connected = False
            raise DeviceError(f"GRBL connect failed: {exc}") from exc

    def _detect_firmware(self) -> str | None:
        """Probe the controller and return "grbl", "marlin", or None.

        Two signals, in order of preference:
          1. The power-up banner already sitting in the input buffer
             ("Grbl 1.1h ..." vs Marlin's "start"/"echo:Marlin ...").
          2. An M115 probe: Marlin answers "FIRMWARE_NAME:Marlin ..." + ok,
             GRBL rejects the unknown command with "error:20".
        Neither probe moves the stage or changes controller state.
        """
        assert self._ser is not None
        try:
            with self._lock:
                waiting = int(getattr(self._ser, "in_waiting", 0) or 0)
                if waiting:
                    banner = self._ser.read(waiting).decode(errors="replace").lower()
                    if "grbl" in banner:
                        return "grbl"
                    if "marlin" in banner:
                        return "marlin"
                self._ser.write(b"M115\n")
                self._ser.flush()
                verdict: str | None = None
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    line = self._ser.readline().decode(errors="replace").strip().lower()
                    if not line:
                        if verdict is not None:
                            break          # reply fully drained
                        continue
                    if "marlin" in line or "firmware_name" in line:
                        verdict = "marlin"  # keep draining until the trailing 'ok'
                    elif line.startswith("grbl"):
                        verdict = "grbl"
                        break
                    elif line.startswith("error"):
                        if verdict is None:
                            verdict = "grbl"   # GRBL rejects M115
                        break
                    elif line.startswith("ok"):
                        break              # end of (possibly unrecognised) reply
                return verdict
        except Exception as exc:
            self.logger.debug("firmware auto-detect failed: %s", exc)
            return None

    def _grbl_reset_clean(self) -> None:
        """Bring GRBL to a known baseline state on connect.

        The app restarting does NOT reset the controller, so a previous session
        (or UGS) can leave behind a G92/G54 work offset or an ALARM lock — which
        is why "same code" could behave differently run to run.  This:

          1. sends a real-time soft-reset (Ctrl-X / 0x18) to abort any leftover
             motion + planner state and re-initialise the parser,
          2. unlocks any resulting ALARM ($X),
          3. clears any residual G92 work-coordinate offset (G92.1),

        so every session starts from the same baseline.  Homing is still
        required afterwards (a soft-reset drops the homing reference).
        """
        assert self._ser is not None
        with self._lock:
            self._ser.write(b"\x18")     # real-time soft-reset
            self._ser.flush()
            time.sleep(2.0)              # allow re-init + welcome banner
            self._ser.reset_input_buffer()
        # $X clears the ALARM a soft-reset raises when homing is required; a
        # no-op (still 'ok') if there was no alarm.
        try:
            self._send_wait("$X")
        except DeviceError as exc:
            self.logger.debug("connect $X: %s", exc)
        # Clear any leftover G92 offset → machine frame == work frame at startup.
        try:
            self._send_wait("G92.1")
        except DeviceError as exc:
            self.logger.debug("connect G92.1: %s", exc)
        # Optionally push steps/mm so firmware $100-102 match the configured
        # microstep jumpers (off by default — non-invasive).
        if self._push_steps:
            for cmd in (f"$100={self._steps_per_mm['x']:.3f}",
                        f"$101={self._steps_per_mm['y']:.3f}",
                        f"$102={self._steps_per_mm['z']:.3f}"):
                try:
                    self._send_wait(cmd)
                except DeviceError as exc:
                    self.logger.debug("connect %s: %s", cmd, exc)
        self._homed = False              # soft-reset invalidates homing
        self._zero = None                # back to positive-display default

    def disconnect(self) -> None:
        self.stop()
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None
        self._connected = False
        self._homed = False
        self.logger.info("GRBLMotorStage disconnected")

    # ------------------------------------------------------------------ #
    # MotorStageBase interface                                             #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # User ↔ machine coordinate frame                                      #
    # ------------------------------------------------------------------ #

    def _offset(self) -> Position:
        """Machine coordinate that is displayed as user (0, 0, 0)."""
        if self._zero is not None:
            return self._zero
        lim = self.limits
        if lim is None:
            return Position(0.0, 0.0, 0.0)
        # Default: lower limit corner → displayed coordinates are positive.
        return Position(lim.x_min, lim.y_min, lim.z_min)

    def _to_user(self, m: Position) -> Position:
        o = self._offset()
        return Position(m.x_mm - o.x_mm, m.y_mm - o.y_mm, m.z_mm - o.z_mm)

    def _to_machine(self, u: Position) -> Position:
        o = self._offset()
        return Position(u.x_mm + o.x_mm, u.y_mm + o.y_mm, u.z_mm + o.z_mm)

    def limits_user_frame(self) -> "SoftwareLimits | None":
        """Machine soft limits translated into the CURRENT user frame.

        The app-facing frame here is the user frame (machine minus
        ``_offset()``): ``get_position`` returns it, ``move_to`` accepts it,
        and ``zero_position`` shifts its origin.  ``self.limits`` however is
        stored in MACHINE coordinates (what GRBL's MPos reports and what
        ``_check_limits`` guards each move against).  The Scan Planner's
        coordinates and the pre-flight validator's ``PlanLimits`` live in the
        user frame, so they must be checked against the machine envelope
        expressed in that same frame — otherwise a plan built around a
        ``zero_position`` origin is rejected against machine-frame bounds it
        never shared (the "Zero Here → planner complains about soft limits"
        bug).

        This subtracts the offset from each bound, so the envelope is only
        SHIFTED, never widened: a user coordinate ``u`` passes here iff
        ``u + offset`` (its machine coordinate) is inside ``self.limits`` —
        exactly the gate ``move_to`` enforces per-move.  Must be re-read
        (and ``PlanLimits`` rebuilt) after home/zero, which move the offset.
        """
        lim = self.limits
        if lim is None:
            return None
        o = self._offset()
        return SoftwareLimits(
            x_min=lim.x_min - o.x_mm, x_max=lim.x_max - o.x_mm,
            y_min=lim.y_min - o.y_mm, y_max=lim.y_max - o.y_mm,
            z_min=lim.z_min - o.z_mm, z_max=lim.z_max - o.z_mm,
        )

    def get_position(self) -> Position:
        # Always report in the user frame; ``_pos`` is machine coordinates.
        if self.simulation or not self._connected:
            return self._to_user(self._pos)
        if self._marlin:
            self._marlin_get_position()
        else:
            self._grbl_get_position()
        return self._to_user(self._pos)

    def is_moving(self) -> bool:
        if self.simulation or not self._connected:
            return False
        if self._marlin:
            # Marlin has no async status; assume idle after ack
            return False
        try:
            status = self._grbl_status()
            return status.lower() not in ("idle", "check")
        except Exception:
            return False

    def at_limit_switch(self) -> dict[str, bool]:
        # GRBL reports limit state in '?' extended status (Pin: field)
        # For now return all-clear; override if you need limit feedback.
        return {k: False for k in ("x_neg", "x_pos", "y_neg", "y_pos", "z_neg", "z_pos")}

    def home(self, axes: list[str] | None = None) -> None:
        self._require_connected()
        if self.simulation:
            self._zero = None                 # reset display origin → positive
            lim = self.limits
            # Emulate the homed corner in machine coordinates (X/Y at the high
            # end ~0, Z at the low end) so the simulated display is plausible.
            self._pos = (Position(lim.x_max, lim.y_max, lim.z_min)
                         if lim is not None else Position(0.0, 0.0, 0.0))
            self._homed = True
        else:
            try:
                if self._marlin:
                    ax = "".join(a.upper() for a in axes) if axes else ""
                    # G28 on a full-size Marlin printer can take 60–120 s
                    self._send_wait(f"G28 {ax}".strip(), timeout=120.0)
                else:
                    self._send_wait("$H", timeout=120.0)   # GRBL homing cycle
                self._zero = None                # reset display origin → positive
                self._homed = True
                # Refresh machine position (updates self._pos in MACHINE coords).
                if self._marlin:
                    self._marlin_get_position()
                else:
                    self._grbl_get_position()
                self.logger.info("GRBLMotorStage homed — machine pos %s", self._pos)
            except Exception as exc:
                # A homing failure (endstop not tripping, ALARM, comms drop) must
                # not leave the stage creeping toward an endstop — halt, then
                # surface the failure clearly to the caller.
                self._fail_safe_halt("home")
                raise MotorHomingError(f"Homing failed: {exc}") from exc

        # Drive to the centre of the soft-limit envelope so the stage parks at a
        # safe, known, in-range location (and well clear of the endstops).
        if self._home_to_center:
            try:
                self.move_to_center()
            except Exception as exc:
                self.logger.warning("Post-home centre move skipped: %s", exc)

    def move_to_center(self) -> None:
        """Centre X/Y in the soft-limit envelope, keeping Z where it is.

        Z is deliberately left at its current height: it is the slow axis
        ($112≈700 mm/min) and after homing the head sits near the top, so a big
        Z dive toward the bed is both slow and undesirable.
        """
        lim = self.limits
        if lim is None:
            return
        if not self.simulation and not self._marlin:
            self._grbl_get_position()          # refresh machine Z
        cx = (lim.x_min + lim.x_max) / 2.0
        cy = (lim.y_min + lim.y_max) / 2.0
        cz = self._pos.z_mm                    # keep current Z (machine frame)
        self.logger.info("Centering X/Y (machine X=%.1f Y=%.1f), keeping Z=%.1f", cx, cy, cz)
        u = self._to_user(Position(cx, cy, cz))
        self.move_to(u.x_mm, u.y_mm, u.z_mm)

    def move_to(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        self._require_connected()
        self._require_homed()
        machine = self._snap(self._to_machine(Position(x_mm, y_mm, z_mm)))
        self._check_limits(machine)            # guard in MACHINE coordinates
        if self.simulation:
            self._pos = machine
            return
        try:
            if self._marlin:
                cmd = (f"G1 X{machine.x_mm:.4f} Y{machine.y_mm:.4f} "
                       f"Z{machine.z_mm:.4f} F{self._feed:.0f}")
                self._send_wait(cmd)
                self._send_wait("M400", timeout=120.0)
            else:
                # Absolute move via GRBL's JOG in MACHINE coordinates ($J=G53 G90):
                #  • G53  → machine frame, immune to any G54/G92 work offset
                #  • G90  → absolute target
                #  • out-of-range target is *refused* (error:15); it does NOT trip
                #    an ALARM that resets/locks the controller
                #  • same jog engine as the (reliable) relative moves.  A plain
                #    "G53 G1" was hanging _grbl_wait_idle on this board right
                #    after homing — the jog form does not.
                cmd = (f"$J=G53 G90 X{machine.x_mm:.4f} Y{machine.y_mm:.4f} "
                       f"Z{machine.z_mm:.4f} F{self._feed:.0f}")
                self._send_wait(cmd)
                self._grbl_wait_idle(timeout=120.0)
        except DeviceError:
            self._fail_safe_halt("move_to")   # already a clear error — just halt
            raise
        except Exception as exc:              # e.g. a raw serial write/read error
            self._fail_safe_halt("move_to")
            raise DeviceError(f"Motor move_to failed: {exc}") from exc
        self._pos = machine

    def move_relative(self, dx_mm: float, dy_mm: float, dz_mm: float) -> None:
        self._require_connected()
        self._require_homed()
        # Refresh the live machine position so the delta is applied to reality.
        if not self.simulation and not self._marlin:
            self._grbl_get_position()
        cur = self._pos
        machine = Position(cur.x_mm + dx_mm, cur.y_mm + dy_mm, cur.z_mm + dz_mm)
        if self._snap_mode == "full":
            # Snap to detents, but keep each jog click moving ≥1 full step.
            machine = self._snap_relative(cur, machine, (dx_mm, dy_mm, dz_mm))
        self._check_limits(machine)            # guard before anything is sent
        if self.simulation:
            self._pos = machine
            return
        if self._marlin:
            u = self._to_user(machine)
            self.move_to(u.x_mm, u.y_mm, u.z_mm)   # Marlin has no $J=
            return
        # GRBL native jog (relative).  A jog that would exceed the soft limits
        # is simply *refused* (error:15) — it does NOT trip an ALARM that
        # resets/locks the controller (which caused the earlier freeze cascade).
        # When snapping is on the actual delta may differ from the request, so
        # derive it from the (possibly snapped) machine target.
        ddx = machine.x_mm - cur.x_mm
        ddy = machine.y_mm - cur.y_mm
        ddz = machine.z_mm - cur.z_mm
        cmd = f"$J=G91 X{ddx:.4f} Y{ddy:.4f} Z{ddz:.4f} F{self._feed:.0f}"
        try:
            self._send_wait(cmd)
            self._grbl_wait_idle()
        except DeviceError:
            self._fail_safe_halt("move_relative")
            raise
        except Exception as exc:
            self._fail_safe_halt("move_relative")
            raise DeviceError(f"Motor move_relative failed: {exc}") from exc
        self._pos = machine

    def stop(self) -> None:
        # Emergency stop: every write here is deliberately made WITHOUT
        # ``self._lock`` — a running move holds that lock inside _send_wait
        # (Marlin M400 blocks up to 120 s), so a locked stop would be queued
        # behind the very move it is supposed to interrupt.
        if self.simulation:
            return
        try:
            if self._ser and self._ser.is_open:
                if self._marlin:
                    # Marlin quickstop.  _send() takes the lock → deadlock;
                    # write the raw line instead (Marlin parses it from the
                    # serial buffer even while executing a move).
                    self._ser.write(b"M410\n")
                else:
                    # GRBL 1.1 real-time jog-cancel (0x85): all our motion is
                    # issued as $J= jogs, and jog-cancel decelerates + flushes
                    # them and returns to Idle.  (A feed-hold '!' would instead
                    # park the controller in Hold, which _grbl_wait_idle treats
                    # as an interrupted move.)
                    self._ser.write(b"\x85")
                self._ser.flush()
        except Exception:
            pass

    def zero_position(self) -> None:
        """Declare the current physical location as the displayed origin (0,0,0).

        Implemented as a pure *software* offset: the displayed user frame is
        shifted so the current machine position reads (0, 0, 0).  GRBL's own
        coordinate systems (G54/G92) are never touched, and absolute moves are
        always sent in machine coordinates via G53 — so the display and the
        hardware can never drift out of sync (the old G92 approach did, which
        is why "Zero Here" appeared to do nothing).

        Sets a USER ORIGIN, **not** machine home: ``_homed`` is deliberately left
        untouched (see ``MotorStageBase.zero_position``).  Only a real homing
        cycle ($H / G28) against the endstops establishes the machine reference
        that G53 absolute moves are issued in — zeroing cannot conjure it.  So
        zeroing an un-homed stage leaves it un-homed, the next move is refused by
        ``_require_homed``, and we say so loudly here rather than fabricating a
        homed flag that would send G53 moves against a reference that never
        existed and check soft limits against the same lie.
        """
        self._require_connected()
        if not self.simulation and not self._marlin:
            self._grbl_get_position()          # refresh machine position
        self._zero = Position(self._pos.x_mm, self._pos.y_mm, self._pos.z_mm)
        if not self._homed:
            self.logger.warning(
                "GRBLMotorStage: 'Zero Here' on an UN-HOMED stage — the display "
                "origin was set, but the stage stays UN-HOMED: there is no machine "
                "reference yet, so moves remain refused until a real homing cycle "
                "($H / G28) runs.  Home first, then zero."
            )
        self.logger.info(
            "GRBLMotorStage: zeroed — display origin set to machine "
            "X=%.3f Y=%.3f Z=%.3f (homed=%s)",
            self._zero.x_mm, self._zero.y_mm, self._zero.z_mm, self._homed,
        )

    def _collect(self, cmd: str, timeout: float = 3.0) -> list[str]:
        """Send *cmd* and collect reply lines until 'ok'/'error'/timeout.

        Real-time commands ('?') get no newline and answer in a single line;
        everything else is newline-terminated and terminated by 'ok'.
        """
        assert self._ser is not None
        realtime = cmd == "?"
        lines: list[str] = []
        with self._lock:
            self._ser.reset_input_buffer()
            self._ser.write(cmd.encode() if realtime else (cmd + "\n").encode())
            self._ser.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                line = self._ser.readline().decode(errors="replace").strip()
                if not line:
                    continue
                lines.append(line)
                if realtime and line.startswith("<"):
                    break
                if not realtime and (line.lower().startswith("ok")
                                     or line.lower().startswith("error")):
                    break
        return lines

    def test_connection(self) -> str:
        """Send a firmware-identity G-code and return the controller's reply.

        Marlin answers M115 with its firmware banner; GRBL answers $I with its
        build-info block.  Either way a non-empty reply confirms the serial
        link, baud rate, and that the board is alive — without moving anything.

        For GRBL the full settings ($$), parser state ($G) and live status (?)
        are additionally dumped to the log so the configuration (soft limits,
        homing, max travel, …) can be inspected from inside the app.
        """
        if self.simulation:
            return "Simulation mode — GRBL/Marlin link not exercised."
        if not self._connected or self._ser is None:
            return "Not connected — click 'Connect All' first."

        cmd = "M115" if self._marlin else "$I"
        lines = self._collect(cmd)
        if not lines:
            return (f"No response to {cmd} on {self._port}.\n"
                    "Check the cable, the COM port, and the baud rate "
                    f"(currently {self._baud}).")

        if not self._marlin:
            # Dump full diagnostics to the log dock for inspection.
            for diag in ("$$", "$G", "?"):
                try:
                    out = self._collect(diag)
                    self.logger.info("GRBL %s on %s:\n%s",
                                     diag, self._port, "\n".join(out))
                except Exception as exc:
                    self.logger.warning("GRBL %s query failed: %s", diag, exc)
            return (f"{cmd} on {self._port} →\n\n" + "\n".join(lines)
                    + "\n\n(Full $$ settings dumped to the Log panel.)")

        return f"{cmd} on {self._port} →\n\n" + "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _check_limits(self, pos: Position) -> None:
        """Validate a MACHINE-coordinate position against the soft limits.

        ``move_to`` / ``move_relative`` convert the user frame to machine
        coordinates first, so this just delegates to the (machine-frame) limits.
        """
        if self.limits is not None:
            self.limits.check(pos)

    def _fail_safe_halt(self, op: str) -> None:
        """Best-effort emergency stop after a comms/motion error mid-operation.

        Safety rule: never continue after a hardware error during motion — try
        to decelerate the stage and surface the failure.  ``stop()`` is itself
        exception-safe (it swallows serial errors and never takes the command
        lock), so this can never mask or delay the original error.
        """
        try:
            self.stop()
        except Exception:
            pass
        self.logger.error("%s failed — issued fail-safe stop.", op)

    def _send(self, cmd: str) -> None:
        """Send a G-code command (no reply wait)."""
        assert self._ser is not None
        with self._lock:
            self._ser.write((cmd.strip() + "\n").encode())
            self._ser.flush()

    def _read_line(self, timeout: float = 5.0) -> str:
        """Read one line, respecting timeout."""
        assert self._ser is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._ser.readline().decode(errors="replace").strip()
            if line:
                return line
        raise DeviceError(f"GRBL timeout waiting for reply to command")

    def _send_wait(self, cmd: str, timeout: float = 30.0) -> str:
        """Send a command and wait until a genuine 'ok' or 'error' is received.

        Marlin sends periodic temperature auto-reports that start with 'ok':
            ok T:20.0 /0.0 B:60.0 /0.0 @:0 B@:0
        These are NOT command acknowledgements and must be skipped, otherwise
        the next _send_wait call picks up a stale 'ok' and returns before
        Marlin has processed the actual command.
        """
        assert self._ser is not None
        with self._lock:
            self._ser.write((cmd.strip() + "\n").encode())
            self._ser.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                line = self._ser.readline().decode(errors="replace").strip()
                if not line:
                    continue
                low = line.lower()
                if low.startswith("ok"):
                    # Skip 'ok T:...' temperature auto-reports — not a command ack
                    rest = low[2:].lstrip()
                    if rest.startswith("t:"):
                        continue
                    return line
                if low.startswith("error"):
                    raise DeviceError(f"GRBL error: {line}")
                if low.startswith("alarm"):
                    # With $20=1 an out-of-range move replies ALARM:x (not ok/
                    # error) and locks the machine.  Surface it immediately
                    # instead of waiting for an 'ok' that will never come.
                    raise DeviceError(
                        f"GRBL {line} — machine locked (soft-limit / out-of-range "
                        f"move). Re-home to clear."
                    )
                if low.startswith("grbl "):
                    # The controller printed its power-up banner mid-command,
                    # i.e. it just reset (typically after a limit ALARM did an
                    # mc_reset).  The command we sent was discarded — don't wait
                    # for an 'ok' that will never come.
                    raise DeviceError(
                        "GRBL reset during command (limit/alarm). "
                        "Re-home ($H) before moving again."
                    )
            raise DeviceError(f"GRBL timeout waiting for 'ok' after: {cmd!r}")

    def _grbl_status(self) -> str:
        """Return GRBL status string (e.g. 'Idle', 'Run')."""
        assert self._ser is not None
        with self._lock:
            self._ser.write(b"?")
            self._ser.flush()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                line = self._ser.readline().decode(errors="replace").strip()
                m = _GRBL_STATUS.match(line)
                if m:
                    self._pos = Position(
                        float(m.group(2)), float(m.group(3)), float(m.group(4))
                    )
                    return m.group(1)
        return "Unknown"

    def _grbl_get_position(self) -> Position:
        self._grbl_status()   # updates self._pos as side-effect
        return self._pos

    def _grbl_wait_idle(self, timeout: float = 120.0) -> None:
        """Block until GRBL finishes the current motion (status == Idle).

        GRBL acknowledges a G1 the moment it is buffered into the planner, not
        when motion completes, so the only reliable "done" signal is the
        real-time status report going back to ``Idle``.  An ``Alarm`` here means
        a limit was tripped (e.g. a soft-limit violation with $20=1) — surface
        it as a clear error instead of letting the caller assume success.
        """
        deadline = time.monotonic() + timeout
        time.sleep(0.05)   # give the planner a moment to start the move
        last_pos = self._pos
        last_move_t = time.monotonic()
        while time.monotonic() < deadline:
            state = self._grbl_status().lower()   # also refreshes self._pos
            if state == "idle":
                return
            if state == "alarm":
                raise DeviceError(
                    "GRBL entered ALARM during move — limit tripped or "
                    "out-of-range target.  Re-home ($H) to clear."
                )
            if state.startswith("hold") or state.startswith("door"):
                # A feed-hold / safety-door interrupted the move (external '!'
                # or door switch — our own STOP uses jog-cancel and ends in
                # Idle).  Neither resolves to Idle on its own, so surface it
                # instead of spinning until the timeout.
                raise DeviceError(
                    f"GRBL is in {state.capitalize()} — motion held "
                    "(feed-hold or safety door).  Send resume (~) or re-home."
                )
            # Stall guard: if GRBL still reports motion (run/jog) but MPos has
            # not advanced for stall_timeout_s, the driver has overheated / lost
            # steps.  Surface it now instead of waiting out the full timeout.
            now = time.monotonic()
            if (abs(self._pos.x_mm - last_pos.x_mm) > self._stall_eps_mm or
                    abs(self._pos.y_mm - last_pos.y_mm) > self._stall_eps_mm or
                    abs(self._pos.z_mm - last_pos.z_mm) > self._stall_eps_mm):
                last_pos = self._pos
                last_move_t = now
            elif state in ("run", "jog") and (now - last_move_t) > self._stall_timeout_s:
                raise DeviceError(
                    f"Motor not advancing (status={state}, position frozen) — "
                    "driver overheated / lost steps?  Check stepper current "
                    "(Vref), cooling, and $1.  Re-home to clear."
                )
            time.sleep(self._poll)
        raise DeviceError(f"GRBL move did not complete within {timeout:.0f} s")

    def _marlin_get_position(self) -> Position:
        """Query Marlin for the live position (M114) and update ``self._pos``.

        Robustness notes from a real CR-10S / Marlin 2.1.2.8 bench capture:

          * The FIRST M114 in a burst is *silently dropped* — no position line
            and no 'ok' arrive.  We therefore RETRY up to
            ``_MARLIN_M114_ATTEMPTS`` times instead of trusting one query.
          * Unsolicited lines (``echo:``/``busy:``/``Cap:``, blanks) are
            interleaved and are skipped while hunting the ``X:.. Y:.. Z:..``
            report (the anchored ``_MARLIN_POS`` regex already ignores the
            ``Count X:..`` step suffix).
          * The acknowledgement is an ADVANCED_OK carrying a suffix
            (``ok P15 B2``), not a bare ``ok``; we consume it (startswith "ok")
            so it is not mistaken for a command ack by the next ``_send_wait``.

        Safety: this NEVER returns a stale cached position on failure.  A caller
        acting on a wrong position moves absolutely to the wrong place and
        checks soft limits against a lie — worse than a clear error.  If every
        attempt fails, it raises ``DeviceError``; ``home()`` fails safe and the
        GUI poller / scan loop already handle the exception.
        """
        assert self._ser is not None
        with self._lock:
            for attempt in range(_MARLIN_M114_ATTEMPTS):
                self._ser.reset_input_buffer()   # drop stale temp/status chatter
                self._ser.write(b"M114\n")
                self._ser.flush()
                found = False
                deadline = time.monotonic() + _MARLIN_M114_ATTEMPT_TIMEOUT_S
                while time.monotonic() < deadline:
                    line = self._ser.readline().decode(errors="replace").strip()
                    if not line:
                        continue
                    if not found:
                        m = _MARLIN_POS.search(line)
                        if m:
                            self._pos = Position(
                                float(m.group(1)), float(m.group(2)),
                                float(m.group(3)),
                            )
                            found = True
                        # else: unsolicited echo:/busy:/Cap:/banner — skip it
                    elif line.lower().startswith("ok"):
                        # Consume the trailing ADVANCED_OK ('ok P.. B..') so it
                        # is not left in the buffer for the next _send_wait.
                        return self._pos
                if found:
                    # Position captured but the trailing 'ok' never arrived
                    # within this attempt — the position itself is valid.
                    return self._pos
                self.logger.warning(
                    "Marlin M114 attempt %d/%d: no position report — retrying",
                    attempt + 1, _MARLIN_M114_ATTEMPTS,
                )
        raise DeviceError(
            f"Marlin M114: no position response after "
            f"{_MARLIN_M114_ATTEMPTS} attempts"
        )

    def _marlin_prime(self) -> None:
        """Fire one throwaway M114 on connect and drain its reply, best-effort.

        The board resets when the serial port opens (DTR toggle), and the first
        command after any reset/idle gap is unreliable — on this CR-10S the
        first M114 of a burst is silently dropped.  Spending that dropped read
        here keeps the first *real* ``get_position()`` clean and off the retry
        path.  A pure read that never moves the stage: safe on the connect path.
        Any failure is swallowed — priming must never fail ``connect()``.
        """
        assert self._ser is not None
        try:
            with self._lock:
                self._ser.reset_input_buffer()
                self._ser.write(b"M114\n")
                self._ser.flush()
                deadline = time.monotonic() + _MARLIN_M114_ATTEMPT_TIMEOUT_S
                while time.monotonic() < deadline:
                    line = self._ser.readline().decode(errors="replace").strip()
                    if line.lower().startswith("ok"):
                        break
        except Exception as exc:
            self.logger.debug("Marlin connect prime skipped: %s", exc)
