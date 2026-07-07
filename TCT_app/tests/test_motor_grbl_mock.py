"""GRBL/Marlin motor-stage tests against a mock serial port (no hardware).

Ports the checks from the legacy test_grbl.py script into pytest and adds a
regression test for the Marlin emergency-stop deadlock: stop() must never
take the command lock (a running move holds it inside _send_wait for up to
120 s).
"""
import logging
import queue
import sys
import threading
import time
import types

import pytest

# ── Mock serial module must be installed before importing the driver ──
class MockSerial:
    """Simulates a GRBL/Marlin serial port."""

    def __init__(self, responses=None):
        self.is_open = True
        self._responses = queue.Queue()
        self._buf = b""
        self.written: list[bytes] = []
        for r in (responses or []):
            self._responses.put(r)

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        if not self._buf:
            try:
                self._buf = self._responses.get(timeout=0.5)
            except queue.Empty:
                return b""
        idx = self._buf.find(b"\n")
        if idx >= 0:
            line, self._buf = self._buf[:idx + 1], self._buf[idx + 1:]
            return line
        line, self._buf = self._buf, b""
        return line

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False


_mock_serial_module = types.ModuleType("serial")
_mock_serial_module.Serial = MockSerial
sys.modules.setdefault("serial", _mock_serial_module)

from devices.motor_base import (  # noqa: E402
    MotorHomingError, MotorLimitError, Position, SoftwareLimits,
)
from devices.motor_grbl import GRBLMotorStage  # noqa: E402


MARLIN_OK = b"ok\n"
MARLIN_POS = b"X:50.00 Y:30.00 Z:5.00 E:0.00 Count X:12800 Y:7680 Z:8000\nok\n"


def _marlin_stage(responses):
    m = GRBLMotorStage(serial_port="MOCK", marlin=True, simulation=False,
                       home_to_center=False)
    m._ser = MockSerial(responses)
    m._connected = True
    m.limits = SoftwareLimits(x_min=0, x_max=235, y_min=0, y_max=235,
                              z_min=0, z_max=250)
    return m


class TestSimulationMode:
    def test_connect_home_move(self):
        m = GRBLMotorStage(simulation=True, home_to_center=False)
        m.connect()
        assert m.connected
        m.limits = SoftwareLimits(0, 235, 0, 235, 0, 250)
        m.home()
        assert m.homed
        m.move_to(10.0, 20.0, 5.0)
        assert m.get_position() == Position(10.0, 20.0, 5.0)
        m.move_relative(1.0, 0.0, 0.0)
        assert m.get_position() == Position(11.0, 20.0, 5.0)

    def test_limit_rejection(self):
        m = GRBLMotorStage(simulation=True, home_to_center=False)
        m.limits = SoftwareLimits(0, 235, 0, 235, 0, 250)
        m.connect()
        m.home()
        with pytest.raises(MotorLimitError):
            m.move_to(300.0, 0.0, 0.0)

    def test_move_before_home_raises(self):
        m = GRBLMotorStage(simulation=True)
        m.connect()
        with pytest.raises(MotorHomingError):
            m.move_to(10.0, 0.0, 0.0)


class TestMarlinMock:
    def test_home_and_position(self):
        m = _marlin_stage([MARLIN_OK, MARLIN_POS])   # G28 ok, M114 reply
        m.home()
        assert m.homed
        # Machine position from mock M114 = (50, 30, 5)
        assert m._pos == Position(50.0, 30.0, 5.0)

    def test_move_within_limits(self):
        m = _marlin_stage([MARLIN_OK, MARLIN_POS,     # home
                           MARLIN_OK, MARLIN_OK])     # G1 ok, M400 ok
        m.home()
        m.move_to(50.0, 30.0, 5.0)                    # user == machine (0-offset)


class TestEmergencyStop:
    def test_stop_writes_m410_without_taking_the_lock(self):
        """Regression: stop() must interrupt a move that HOLDS the lock."""
        m = _marlin_stage([])
        m._lock.acquire()                # simulate a move inside _send_wait
        try:
            done = threading.Event()

            def _stop():
                m.stop()
                done.set()

            t = threading.Thread(target=_stop, daemon=True)
            t.start()
            assert done.wait(timeout=1.0), \
                "stop() blocked on the command lock — E-stop deadlock"
        finally:
            m._lock.release()
        assert any(b"M410" in w for w in m._ser.written)

    def test_grbl_stop_sends_jog_cancel(self):
        m = GRBLMotorStage(serial_port="MOCK", marlin=False, simulation=False)
        m._ser = MockSerial([])
        m._connected = True
        m.stop()
        assert b"\x85" in b"".join(m._ser.written)
        assert b"!" not in b"".join(m._ser.written)   # no feed-hold → no Hold trap


class TestFirmwareDetect:
    def test_detects_marlin_from_m115(self):
        m = GRBLMotorStage(serial_port="MOCK", marlin=False, simulation=False)
        m._ser = MockSerial([b"FIRMWARE_NAME:Marlin 2.1.1\nok\n"])
        assert m._detect_firmware() == "marlin"

    def test_detects_grbl_from_error_reply(self):
        m = GRBLMotorStage(serial_port="MOCK", marlin=True, simulation=False)
        m._ser = MockSerial([b"error:20\n"])
        assert m._detect_firmware() == "grbl"

    def test_inconclusive_returns_none(self):
        m = GRBLMotorStage(serial_port="MOCK", marlin=True, simulation=False)
        m._ser = MockSerial([])
        assert m._detect_firmware() is None


class TestSoftwareLimitsGuard:
    """SoftwareLimits must never silently accept an envelope that blocks motion.

    Regression for the shipped soft-limit bug: x_min=300, x_max=0 made
    'min <= pos <= max' false for EVERY position, so every move was refused and
    nothing warned that the envelope was impossible.
    """

    def test_valid_bounds_emit_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="SoftwareLimits"):
            lim = SoftwareLimits(0, 235, 0, 235, 0, 250)
        assert caplog.records == []
        lim.check(Position(10, 10, 10))                 # in range → ok
        with pytest.raises(MotorLimitError):
            lim.check(Position(300, 0, 0))              # out of range → refused

    def test_defaults_stay_valid(self, caplog):
        with caplog.at_level(logging.WARNING, logger="SoftwareLimits"):
            lim = SoftwareLimits()                       # ±50 / ±10 defaults
        assert caplog.records == []
        lim.check(Position(0, 0, 0))

    def test_swapped_bounds_autocorrected_and_warned(self, caplog):
        with caplog.at_level(logging.WARNING, logger="SoftwareLimits"):
            lim = SoftwareLimits(x_min=300, x_max=0,
                                 y_min=0, y_max=235, z_min=0, z_max=250)
        # Corrected in place so check() can trust its bounds …
        assert (lim.x_min, lim.x_max) == (0, 300)
        # … and it was loud, naming the axis + both values.
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "SWAPPED" in msg and "300" in msg and "0" in msg
        lim.check(Position(150, 10, 10))                 # now accepted
        with pytest.raises(MotorLimitError):
            lim.check(Position(400, 10, 10))            # still bounded

    def test_zero_width_axis_warns_but_does_not_raise(self, caplog):
        with caplog.at_level(logging.WARNING, logger="SoftwareLimits"):
            lim = SoftwareLimits(x_min=0, x_max=235, y_min=0, y_max=235,
                                 z_min=7, z_max=7)        # Z pinned to one point
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "ZERO-WIDTH" in msg
        lim.check(Position(10, 10, 7))                    # the one reachable Z
        with pytest.raises(MotorLimitError):
            lim.check(Position(10, 10, 8))               # any other Z refused

    def test_from_config_swapped_is_autocorrected(self):
        lim = SoftwareLimits.from_config({
            "x_min_mm": 300.0, "x_max_mm": 0.0,
            "y_min_mm": 0.0, "y_max_mm": 200.0,
            "z_min_mm": 0.0, "z_max_mm": 400.0,
        })
        assert lim.x_min == 0.0 and lim.x_max == 300.0
        lim.check(Position(150, 100, 200))               # a coherent envelope now


class TestWaitIdleHoldState:
    def test_hold_state_raises_instead_of_spinning(self):
        m = GRBLMotorStage(serial_port="MOCK", marlin=False, simulation=False)
        # '?' status replies reporting Hold — _grbl_wait_idle must fail fast.
        m._ser = MockSerial([b"<Hold:0|MPos:1.000,2.000,3.000|FS:0,0>\n"] * 5)
        m._connected = True
        from devices.base import DeviceError
        t0 = time.monotonic()
        with pytest.raises(DeviceError, match="[Hh]old"):
            m._grbl_wait_idle(timeout=10.0)
        assert time.monotonic() - t0 < 5.0


# --------------------------------------------------------------------------- #
# Marlin M114 position-readback regression (real CR-10S / Marlin 2.1.2.8)      #
# --------------------------------------------------------------------------- #
#
# Ground truth captured from the physical bench (used VERBATIM below):
#   * M114 answers with `X:.. Y:.. Z:.. Count X:.. Y:.. Z:..` then an
#     ADVANCED_OK line `ok P15 B2` (the 'ok' carries a ` P<planner> B<block>`
#     suffix — NOT a bare 'ok').
#   * The FIRST M114 in a burst is SILENTLY DROPPED (no position line, no ok).
#   * Unsolicited lines (e.g. `echo:SD card released`) are interleaved.
#
# The bug: after a real G28, the single post-home M114 was dropped, the old
# reader timed out and RETURNED THE STALE cached position (54/52) while the
# stage was physically at (4,2,0).  A wrong internal position sends absolute
# moves to the wrong place and validates soft limits against a lie.

# Verbatim bench captures ---------------------------------------------------
CR10S_M114_LINE = b"X:4.00 Y:2.00 Z:0.00 Count X:320 Y:160 Z:0\n"
CR10S_ADVANCED_OK = b"ok P15 B2\n"
CR10S_M114_REPLY = CR10S_M114_LINE + CR10S_ADVANCED_OK
CR10S_ECHO = b"echo:SD card released\n"

# The stale position the bug used to return — physically wrong after homing.
STALE_POS = Position(54.0, 52.0, 0.0)
HOMED_POS = Position(4.0, 2.0, 0.0)


class FakeMarlinSerial:
    """Duck-typed serial that replays real CR-10S / Marlin 2.1.2.8 captures.

    ``m114_replies`` scripts the reply pushed into the read buffer for each
    successive ``M114`` write: ``b""`` models the silently-dropped first burst,
    and any write past the end of the list also pushes nothing (dropped).  Every
    other non-empty write (e.g. ``G28``/``G1``/``M400``) pushes ``other_reply``
    (Marlin's bare ``ok``).  ``reset_input_buffer`` clears the read buffer, just
    like the real port — the driver calls it before each M114 attempt.
    """

    def __init__(self, m114_replies, other_reply=b"ok\n", timeout=0.02):
        self._m114_replies = list(m114_replies)
        self._other_reply = other_reply
        self.timeout = timeout          # real pyserial attribute the driver reads
        self.is_open = True
        self.written: list[bytes] = []
        self._buf = b""
        self._m114_count = 0

    def write(self, data: bytes) -> None:
        self.written.append(data)
        payload = data.strip()
        if payload == b"M114":
            if self._m114_count < len(self._m114_replies):
                self._buf += self._m114_replies[self._m114_count]
            self._m114_count += 1
        elif payload and self._other_reply is not None:
            self._buf += self._other_reply

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        self._buf = b""

    def readline(self) -> bytes:
        if not self._buf:
            time.sleep(self.timeout)     # emulate a read that hits its timeout
            return b""
        idx = self._buf.find(b"\n")
        if idx >= 0:
            line, self._buf = self._buf[:idx + 1], self._buf[idx + 1:]
            return line
        line, self._buf = self._buf, b""
        return line

    def close(self) -> None:
        self.is_open = False

    @property
    def in_waiting(self) -> int:
        return len(self._buf)

    def _m114_writes(self) -> int:
        return sum(1 for w in self.written if w.strip() == b"M114")


def _marlin_stage_with(ser):
    m = GRBLMotorStage(serial_port="MOCK", marlin=True, simulation=False,
                       home_to_center=False)
    m._ser = ser
    m._connected = True
    m.limits = SoftwareLimits(x_min=0, x_max=235, y_min=0, y_max=235,
                              z_min=0, z_max=250)
    return m


class TestMarlinM114Robustness:
    def test_first_m114_dropped_retries_and_returns_fresh(self):
        """(a) 1st M114 drops, 2nd answers — retry, return (4,2,0) not stale."""
        ser = FakeMarlinSerial([b"", CR10S_M114_REPLY])
        m = _marlin_stage_with(ser)
        m._pos = STALE_POS                      # the ghost the bug returned
        pos = m._marlin_get_position()
        assert pos == HOMED_POS
        assert m._pos == HOMED_POS
        assert ser._m114_writes() == 2          # proof it retried

    def test_unsolicited_echo_before_position_is_skipped(self):
        """(b) `echo:SD card released` interleaved — position still parsed."""
        ser = FakeMarlinSerial([CR10S_ECHO + CR10S_M114_REPLY])
        m = _marlin_stage_with(ser)
        assert m._marlin_get_position() == HOMED_POS

    def test_advanced_ok_is_consumed_so_next_send_wait_is_clean(self):
        """(c) ADVANCED_OK `ok P15 B2` consumed — buffer empty afterwards."""
        ser = FakeMarlinSerial([CR10S_M114_REPLY])
        m = _marlin_stage_with(ser)
        assert m._marlin_get_position() == HOMED_POS
        assert ser.in_waiting == 0              # 'ok P15 B2' was drained
        # A following command gets its OWN ack, not a stale leftover 'ok'.
        assert m._send_wait("G1 X4 Y2 Z0 F3000").lower().startswith("ok")

    def test_all_attempts_dropped_raises_not_stale(self, monkeypatch):
        """(d) every M114 dropped — raise DeviceError, never return stale."""
        import devices.motor_grbl as mg
        monkeypatch.setattr(mg, "_MARLIN_M114_ATTEMPT_TIMEOUT_S", 0.1)
        from devices.base import DeviceError
        ser = FakeMarlinSerial([b"", b"", b""])
        m = _marlin_stage_with(ser)
        m._pos = STALE_POS
        with pytest.raises(DeviceError, match="no position response"):
            m._marlin_get_position()
        assert ser._m114_writes() == mg._MARLIN_M114_ATTEMPTS

    def test_home_recovers_from_dropped_post_g28_m114(self):
        """The exact bench bug: G28 ok, post-home M114 dropped once, then the
        homed corner arrives — home() must end at (4,2,0), NOT the stale cache."""
        ser = FakeMarlinSerial([b"", CR10S_M114_REPLY])   # M114 #1 dropped
        m = _marlin_stage_with(ser)
        m._pos = STALE_POS
        m.home()                                 # G28 -> M114(drop) -> retry
        assert m.homed
        assert m._pos == HOMED_POS               # not (54,52,0)


class TestMarlinConnectPrime:
    def test_prime_fires_one_m114_and_drains_reply(self):
        ser = FakeMarlinSerial([CR10S_M114_REPLY])
        m = _marlin_stage_with(ser)
        m._marlin_prime()
        assert ser._m114_writes() == 1
        assert ser.in_waiting == 0               # reply fully drained, clean

    def test_prime_swallows_errors_and_releases_lock(self):
        class Boom(FakeMarlinSerial):
            def write(self, data):               # port wedged mid-prime
                raise OSError("port wedged")

        m = _marlin_stage_with(Boom([]))
        m._marlin_prime()                        # must NOT raise
        assert m._lock.acquire(blocking=False)   # lock was released
        m._lock.release()
