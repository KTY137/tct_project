"""Transport-lock contract for the motor drivers (no hardware, no I/O).

Three properties are pinned here, because everything that later reserves a
device (capability spine, scan run-control) will build on them:

  (1) IDENTITY — ``device.transport_lock`` must be ``is``-identical to the lock
      the driver's own I/O actually acquires.  A second, parallel lock over one
      transport is a lie: the caller holds one, the driver takes the other, and
      the exchanges interleave exactly as before.  Asserted *behaviourally*
      (the lock is owned at the moment bytes hit the port / the GCS call runs),
      not by reading the attribute the driver happens to use today.

  (2) NO INTERLEAVING — a poller thread and a mover thread hammering one
      PIMotorStage must never be inside the same GCS exchange at once.  This is
      the live bug this suite was written for: PIMotorStage serialised nothing,
      so ``get_position`` from the GUI poller could land inside the scan
      thread's ``MOV``/``IsMoving`` exchange.

  (3) STOP IS NEVER QUEUED — holding the transport lock must not delay an
      emergency stop.  GRBL's stop is a real-time byte and takes no lock at all;
      PI's stop takes it only with a short timeout and sends STP regardless.
"""
import threading
import time

import pytest

from devices.base import BaseDevice
from devices.motor_base import Position, SoftwareLimits
from devices.motor_grbl import GRBLMotorStage
from devices.motor_pi import PIMotorStage


def held_by_this_thread(lock) -> bool:
    """True if *lock* (an RLock) is currently owned by the calling thread."""
    is_owned = getattr(lock, "_is_owned", None)
    assert is_owned is not None, "transport_lock must be re-entrant (RLock)"
    return bool(is_owned())


def run_with_timeout(fn, timeout: float = 5.0) -> bool:
    """Run *fn* in a daemon thread; return True if it finished in time."""
    done = threading.Event()
    err: list[BaseException] = []

    def _run():
        try:
            fn()
        except BaseException as exc:      # noqa: BLE001 — surfaced below
            err.append(exc)
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True).start()
    finished = done.wait(timeout)
    if err:
        raise err[0]
    return finished


# --------------------------------------------------------------------------- #
# BaseDevice default                                                           #
# --------------------------------------------------------------------------- #

class _PlainDevice(BaseDevice):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...


class TestBaseDeviceDefault:
    def test_default_transport_lock_is_the_io_lock(self):
        dev = _PlainDevice(simulation=True)
        assert dev.transport_lock is dev.io_lock

    def test_default_transport_lock_is_reentrant(self):
        dev = _PlainDevice(simulation=True)
        with dev.transport_lock:
            with dev.transport_lock:          # would deadlock on a plain Lock
                assert held_by_this_thread(dev.transport_lock)


# --------------------------------------------------------------------------- #
# GRBL — transport lock is the private command lock, and STOP bypasses it      #
# --------------------------------------------------------------------------- #

class LockWatchingSerial:
    """Serial stub that records whether the stage's transport lock was owned
    by the writing thread at the moment each byte string was written."""

    def __init__(self, stage, replies=None):
        self._stage = stage
        self.is_open = True
        self.written: list[bytes] = []
        self.lock_held_on_write: list[bool] = []
        self._buf = b""
        self._replies = dict(replies or {})

    def write(self, data: bytes) -> None:
        self.written.append(data)
        self.lock_held_on_write.append(
            held_by_this_thread(self._stage.transport_lock)
        )
        payload = data.strip()
        for key, reply in self._replies.items():
            if payload == key:
                self._buf += reply
                break

    def flush(self) -> None: ...

    def reset_input_buffer(self) -> None:
        self._buf = b""

    def readline(self) -> bytes:
        if not self._buf:
            time.sleep(0.01)
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


def _grbl_stage() -> GRBLMotorStage:
    m = GRBLMotorStage(serial_port="MOCK", marlin=False, simulation=False,
                       home_to_center=False)
    m._ser = LockWatchingSerial(m, replies={
        b"$X": b"ok\n",
        b"?": b"<Idle|MPos:1.000,2.000,3.000|FS:0,0>\n",
    })
    m._connected = True
    m.limits = SoftwareLimits(0, 235, 0, 235, 0, 250)
    return m


class TestGRBLTransportLock:
    def test_transport_lock_is_the_lock_the_io_takes(self):
        """(1) identity — behaviourally, not by attribute name."""
        m = _grbl_stage()
        assert m.transport_lock is m._lock          # the lock _send/_send_wait use

        m._send_wait("$X")                          # a command exchange
        m._grbl_status()                            # a real-time status exchange
        m._collect("?")                             # the diagnostic path

        assert m._ser.lock_held_on_write, "no I/O happened — test is vacuous"
        assert all(m._ser.lock_held_on_write), (
            "GRBL wrote to the port without holding transport_lock — the "
            "accessor does not name the lock its I/O actually takes"
        )

    def test_transport_lock_is_reentrant(self):
        """The Lock→RLock change: a caller may hold it across a driver call."""
        m = _grbl_stage()

        def _reenter():
            with m.transport_lock:                  # e.g. a reservation
                m._send_wait("$X")                  # takes the same lock again
                assert held_by_this_thread(m.transport_lock)

        assert run_with_timeout(_reenter, timeout=5.0), \
            "driver deadlocked against a held transport_lock — lock is not re-entrant"

    def test_stop_is_not_queued_behind_a_held_transport_lock(self):
        """(3) E-stop: GRBL's jog-cancel is a real-time byte and takes no lock."""
        m = _grbl_stage()
        m.transport_lock.acquire()                  # simulate a move mid-exchange
        try:
            t0 = time.monotonic()
            assert run_with_timeout(m.stop, timeout=1.0), \
                "stop() blocked on the transport lock — E-stop deadlock"
            assert time.monotonic() - t0 < 1.0
        finally:
            m.transport_lock.release()
        assert b"\x85" in b"".join(m._ser.written)  # jog-cancel really went out
        # …and it went out WITHOUT the lock (that is the whole point).
        assert m._ser.lock_held_on_write[-1] is False


# --------------------------------------------------------------------------- #
# PI — the live gap: an unserialised GCS session shared by poller + mover      #
# --------------------------------------------------------------------------- #

class FakeGCS:
    """GCS session stub that detects two threads inside one exchange.

    Every call dwells briefly *inside* the exchange, so an unserialised driver
    reliably trips the interleave detector rather than passing by luck.
    """

    def __init__(self, stage, dwell: float = 0.002):
        self._stage = stage
        self._dwell = dwell
        self._bookkeeping = threading.Lock()   # protects the test's own state
        self._inside: int | None = None
        self.violations: list[str] = []        # two threads in one exchange
        self.unguarded: list[str] = []         # call made without transport_lock
        self.calls: list[str] = []
        self._moving_polls = 0
        self._pos = {"1": 0.0, "2": 0.0, "3": 0.0}

    # -- exchange bookkeeping ------------------------------------------------
    def _exchange(self, name: str):
        me = threading.get_ident()
        if not held_by_this_thread(self._stage.transport_lock):
            self.unguarded.append(name)
        with self._bookkeeping:
            if self._inside is not None and self._inside != me:
                self.violations.append(name)
            self._inside = me
            self.calls.append(name)
        time.sleep(self._dwell)                # the window an interleave would use
        with self._bookkeeping:
            if self._inside != me:
                self.violations.append(name)
            self._inside = None

    # -- GCS surface used by the driver --------------------------------------
    def qPOS(self, ids):
        self._exchange("qPOS")
        return dict(self._pos)

    def MOV(self, ids, targets):
        self._exchange("MOV")
        for axis, target in zip(ids, targets):
            self._pos[axis] = float(target)
        self._moving_polls = 2                 # two IsMoving polls report motion

    def IsMoving(self, ids):
        self._exchange("IsMoving")
        moving = self._moving_polls > 0
        if moving:
            self._moving_polls -= 1
        return {a: moving for a in ids}

    def qONT(self, ids):
        self._exchange("qONT")
        return {a: True for a in ids}

    def qLIM(self, axis):
        self._exchange("qLIM")
        return {f"{axis}_1": False, f"{axis}_2": False}

    def DFH(self, axis):
        self._exchange("DFH")

    def VEL(self, ids, vels):
        self._exchange("VEL")

    def STP(self):
        self._exchange("STP")

    def CloseConnection(self):
        self._exchange("CloseConnection")


def _pi_stage(dwell: float = 0.002) -> PIMotorStage:
    """A PI stage wired to a fake GCS session — never touches pipython."""
    m = PIMotorStage(simulation=False)
    m._gcs = FakeGCS(m, dwell=dwell)
    m._connected = True
    m._homed = True                             # tests target the transport, not the gate
    m.limits = SoftwareLimits(-20, 20, -20, 20, -20, 20)
    m._move_timeout = 5.0
    return m


class TestPITransportLock:
    def test_transport_lock_is_the_lock_the_io_takes(self):
        """(1) identity — every GCS exchange runs under transport_lock."""
        m = _pi_stage()
        assert m.transport_lock is m.io_lock

        m.get_position()
        m.is_moving()
        m.at_limit_switch()
        m.move_to(1.0, 2.0, 3.0)
        m.zero_position()

        gcs = m._gcs
        assert gcs.calls, "no GCS traffic happened — test is vacuous"
        assert gcs.unguarded == [], (
            f"PI touched the GCS session without transport_lock: {gcs.unguarded}"
        )

    def test_transport_lock_is_reentrant(self):
        m = _pi_stage()

        def _reenter():
            with m.transport_lock:              # e.g. a reservation
                m.get_position()                # takes the same lock again
                m.move_to(1.0, 1.0, 1.0)

        assert run_with_timeout(_reenter, timeout=5.0), \
            "PI driver deadlocked against a held transport_lock"

    def test_poller_and_mover_never_interleave_inside_one_exchange(self):
        """(2) the live gap: GUI poller vs scan thread on one GCS session."""
        m = _pi_stage(dwell=0.003)
        stop_flag = threading.Event()
        errors: list[BaseException] = []

        def _poller():                          # the GUI position poll
            try:
                while not stop_flag.is_set():
                    m.get_position()
                    m.is_moving()
            except BaseException as exc:        # noqa: BLE001
                errors.append(exc)

        def _mover():                           # the scan thread
            try:
                for i in range(12):
                    if stop_flag.is_set():
                        return
                    m.move_to(float(i % 5), float((i + 1) % 5), 0.0)
            except BaseException as exc:        # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_poller, daemon=True),
                   threading.Thread(target=_mover, daemon=True)]
        for t in threads:
            t.start()
        threads[1].join(timeout=20.0)           # the mover finishes its 12 moves
        stop_flag.set()
        for t in threads:
            t.join(timeout=5.0)

        gcs = m._gcs
        assert errors == [], f"driver raised under contention: {errors!r}"
        assert not any(t.is_alive() for t in threads), "threads did not finish"
        assert gcs.violations == [], (
            f"two threads were inside one GCS exchange: {gcs.violations[:5]}"
        )
        assert gcs.unguarded == [], (
            f"GCS touched without the transport lock: {gcs.unguarded[:5]}"
        )
        # Both really ran (otherwise the absence of violations proves nothing).
        assert gcs.calls.count("MOV") == 12
        assert gcs.calls.count("qPOS") > 1

    def test_position_poll_is_not_starved_by_a_move(self):
        """The wait loop must release the lock BETWEEN polls, not hold it for
        the whole move — otherwise the GUI position display freezes per move."""
        m = _pi_stage(dwell=0.002)
        m._gcs._moving_polls = 0

        polls: list[Position] = []
        stop_flag = threading.Event()

        def _poller():
            while not stop_flag.is_set():
                polls.append(m.get_position())
                time.sleep(0.001)

        t = threading.Thread(target=_poller, daemon=True)
        t.start()
        try:
            for i in range(6):
                m.move_to(float(i), 0.0, 0.0)   # each move runs the wait loop
        finally:
            stop_flag.set()
            t.join(timeout=5.0)
        assert len(polls) > 1, "poller made no progress while moves were running"


class TestPIStopIsNeverQueued:
    def test_stop_takes_the_lock_when_the_transport_is_free(self):
        m = _pi_stage()
        m.stop()
        assert m._gcs.calls == ["STP"]
        assert m._gcs.unguarded == [], "an idle-transport stop should be guarded"

    def test_stop_is_not_queued_behind_a_held_transport_lock(self):
        """(3) E-stop: bounded acquire, then STP goes out UNGUARDED rather than
        waiting for a 60 s move to release the transport."""
        m = _pi_stage()
        holder_released = threading.Event()

        def _hold():                            # a mover holding the transport
            with m.transport_lock:
                holder_released.wait(timeout=10.0)

        holder = threading.Thread(target=_hold, daemon=True)
        holder.start()
        time.sleep(0.05)                        # let the holder take the lock
        try:
            t0 = time.monotonic()
            assert run_with_timeout(m.stop, timeout=3.0), \
                "PI stop() never completed while the transport was held"
            elapsed = time.monotonic() - t0
        finally:
            holder_released.set()
            holder.join(timeout=5.0)

        # It fell through the bounded acquire quickly — never behind the move.
        assert elapsed < 3.0
        assert elapsed >= PIMotorStage._STOP_LOCK_TIMEOUT_S * 0.5
        assert m._gcs.calls == ["STP"], "the stop never reached the controller"
        assert m._gcs.unguarded == ["STP"], (
            "STP should have been sent unguarded after the bounded acquire failed"
        )

    def test_stop_while_not_connected_is_a_noop(self):
        m = PIMotorStage(simulation=False)       # no GCS session at all
        m.stop()                                 # must not raise


class TestPINoHardwareOnConstruction:
    def test_constructor_opens_no_session(self):
        m = PIMotorStage(simulation=False)
        assert m._gcs is None
        assert not m.connected
        assert not m.homed
