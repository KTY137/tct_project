"""Board-transport lock contract for the PSI DRS4 driver (no hardware, no
'drs' C-extension is ever imported).

The DRS4 evaluation board exposes ONE SDK board handle that is shared by the
scan acquisition thread and the scope monitor (ScopeChannelMonitor).  Before
this fix ``read_channel`` ran ``StartDomino``/``TransferWaves``/``GetWave``
with no lock at all, and the settings setters + connect/disconnect touched the
same handle unguarded — so a monitor read could land *inside* an acquisition's
domino exchange.  Same failure class as the pre-fix ``PIMotorStage`` (4a89647).

Three properties are pinned, mirroring ``tests/test_motor_transport_lock.py``:

  (1) IDENTITY — ``transport_lock`` is ``is``-identical to ``io_lock`` (the
      lock the driver's own board I/O actually acquires), asserted behaviourally
      (the lock is owned at the moment every SDK call runs), and re-entrant.
  (2) NO INTERLEAVING — a reader thread and an acquirer thread hammering one
      board never sit inside the same board exchange at once.
  (3) NON-VACUITY — the very same detector, run against an unserialised driver
      (io_lock swapped for a no-op lock), DOES report violations; and the
      detector is shown to catch a deliberately forced interleave.

A scope has no motion to interrupt, so — unlike the motor drivers — there is
no stop/abort path that must bypass the lock.  ``test_scope_has_no_emergency_
stop_path`` guards that assumption.  ``is_alive`` is inherited from BaseDevice
(a flag-return that touches no board and takes no lock), covered below.
"""
import sys
import threading
import time
import types

import numpy as np

from devices.oscilloscope_drs4 import DRS4Oscilloscope

_N = 1024   # DRS4 samples per channel (matches the driver's _N_SAMPLES)


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


class FakeBoard:
    """DRS4 SDK board stub that detects two threads inside one exchange.

    Every SDK call records (a) whether the scope's ``transport_lock`` was owned
    by the calling thread and (b) whether another thread was already inside an
    exchange.  Each call dwells briefly *inside* the exchange so an unserialised
    driver reliably trips the interleave detector rather than passing by luck.
    """

    def __init__(self, scope, dwell: float = 0.002):
        self._scope = scope
        self._dwell = dwell
        self._bookkeeping = threading.Lock()   # protects the test's own state
        self._inside: int | None = None
        self.violations: list[str] = []        # two threads in one exchange
        self.unguarded: list[str] = []         # SDK call without transport_lock
        self.calls: list[str] = []

    # -- exchange bookkeeping ------------------------------------------------
    def _exchange(self, name: str):
        me = threading.get_ident()
        if not held_by_this_thread(self._scope.transport_lock):
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

    # -- DRS4 SDK surface the driver calls -----------------------------------
    def Init(self) -> bool:
        self._exchange("Init")
        return True

    def GetBoardSerialNumber(self) -> int:
        self._exchange("GetBoardSerialNumber")
        return 1234

    def SetFrequency(self, freq, cal) -> None:
        self._exchange("SetFrequency")

    def SetInputRange(self, rng) -> None:
        self._exchange("SetInputRange")

    def SetTriggerSource(self, bits) -> None:
        self._exchange("SetTriggerSource")

    def SetTriggerLevel(self, level) -> None:
        self._exchange("SetTriggerLevel")

    def SetTriggerPolarity(self, negative) -> None:
        self._exchange("SetTriggerPolarity")

    def StartDomino(self) -> None:
        self._exchange("StartDomino")

    def IsBusy(self) -> bool:
        self._exchange("IsBusy")
        return True                            # trigger has arrived → wait exits

    def TransferWaves(self, first, last) -> None:
        self._exchange("TransferWaves")

    def GetTime(self, chip, ch):
        self._exchange("GetTime")
        return np.arange(_N, dtype=float)

    def GetWave(self, chip, ch, cal):
        self._exchange("GetWave")
        return np.zeros(_N, dtype=float)       # no threshold crossing → jitter no-op


def _drs_scope(dwell: float = 0.002, n_averages: int = 1,
               time_correction: bool = True) -> DRS4Oscilloscope:
    """A DRS4 driver wired to a fake board — never imports the 'drs' extension."""
    s = DRS4Oscilloscope(simulation=False, n_averages=n_averages,
                         time_correction=time_correction)
    s._board = FakeBoard(s, dwell=dwell)
    s._connected = True
    return s


class _NullLock:
    """A lock that never actually locks — models the pre-fix (unserialised)
    driver so the detector can be *shown* to fire.  ``with self.io_lock`` runs
    but serialises nothing and is never owned, exactly like having no lock."""

    def acquire(self, blocking=True, timeout=-1):
        return True

    def release(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _is_owned(self):
        return False


# --------------------------------------------------------------------------- #
# (1) identity + re-entrancy                                                   #
# --------------------------------------------------------------------------- #

class TestDRS4TransportLockIdentity:
    def test_transport_lock_is_the_io_lock(self):
        s = _drs_scope()
        assert s.transport_lock is s.io_lock

    def test_every_board_call_runs_under_transport_lock(self):
        """(1) behavioural identity — every SDK call the driver makes across the
        full public surface is issued while transport_lock is owned."""
        s = _drs_scope()
        s.read_channel(1)                       # StartDomino/Transfer/GetWave...
        s.set_frequency(2.0)
        s.set_voltage_range(1)
        s.set_trigger(source="CH1", level_V=-0.1, edge="RISE")

        board = s._board
        assert board.calls, "no board I/O happened — test is vacuous"
        assert board.unguarded == [], (
            f"DRS4 touched the board without transport_lock: {board.unguarded}"
        )

    def test_connect_runs_board_setup_under_the_lock(self, monkeypatch):
        """connect() + _apply_config() push Init/SetFrequency/SetTrigger... to
        the board; all must run under io_lock.  Inject a fake 'drs' module so
        the real C-extension is never imported."""
        s = DRS4Oscilloscope(simulation=False)
        board = FakeBoard(s)
        monkeypatch.setitem(sys.modules, "drs",
                            types.SimpleNamespace(Board=lambda: board))

        s.connect()

        assert s.connected
        assert board.unguarded == [], f"connect touched the board unguarded: {board.unguarded}"
        for expected in ("Init", "SetFrequency", "SetInputRange",
                         "SetTriggerSource", "GetBoardSerialNumber"):
            assert expected in board.calls, f"connect never issued {expected}"

    def test_transport_lock_is_reentrant(self):
        """A caller may hold the lock across a driver call (e.g. a reservation)
        without deadlocking — the Lock→RLock guarantee from BaseDevice."""
        s = _drs_scope()

        def _reenter():
            with s.transport_lock:              # e.g. a reservation
                s.read_channel(1)               # takes the same lock again
                s.set_frequency(3.0)
                assert held_by_this_thread(s.transport_lock)

        assert run_with_timeout(_reenter, timeout=5.0), \
            "DRS4 driver deadlocked against a held transport_lock"

    def test_disconnect_is_serialised_by_the_lock(self):
        """disconnect() nulls the SDK handle; it must take io_lock so it cannot
        run while an exchange is mid-flight on another thread."""
        s = _drs_scope()
        s.io_lock.acquire()                     # simulate an in-flight exchange
        done = threading.Event()

        threading.Thread(
            target=lambda: (s.disconnect(), done.set()), daemon=True
        ).start()

        assert not done.wait(0.2), "disconnect did not block on the held io_lock"
        s.io_lock.release()
        assert done.wait(2.0), "disconnect never completed after lock release"
        assert s._board is None and not s.connected


# --------------------------------------------------------------------------- #
# (2) no interleaving — reader (monitor) vs acquirer (scan) on one board       #
# --------------------------------------------------------------------------- #

class TestDRS4NoInterleaving:
    def test_reader_and_acquirer_never_interleave_inside_one_exchange(self):
        s = _drs_scope(dwell=0.003)
        stop_flag = threading.Event()
        errors: list[BaseException] = []

        def _reader():                          # the scope monitor's live read
            try:
                while not stop_flag.is_set():
                    s.read_channel(1)
            except BaseException as exc:        # noqa: BLE001
                errors.append(exc)

        def _acquirer():                        # the scan thread + settings churn
            try:
                for i in range(15):
                    if stop_flag.is_set():
                        return
                    s.read_channel(2)
                    s.set_trigger(level_V=-0.05 - i * 0.001)
            except BaseException as exc:        # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_reader, daemon=True),
                   threading.Thread(target=_acquirer, daemon=True)]
        for t in threads:
            t.start()
        threads[1].join(timeout=20.0)           # the acquirer finishes its 15 reads
        stop_flag.set()
        for t in threads:
            t.join(timeout=5.0)

        board = s._board
        assert errors == [], f"driver raised under contention: {errors!r}"
        assert not any(t.is_alive() for t in threads), "threads did not finish"
        assert board.violations == [], (
            f"two threads were inside one board exchange: {board.violations[:5]}"
        )
        assert board.unguarded == [], (
            f"board touched without transport_lock: {board.unguarded[:5]}"
        )
        # Both really ran (otherwise the absence of violations proves nothing).
        assert board.calls.count("StartDomino") > 15
        assert board.calls.count("SetTriggerSource") >= 15


# --------------------------------------------------------------------------- #
# (3) non-vacuity — the detector fires against the unserialised pattern        #
# --------------------------------------------------------------------------- #

class TestDRS4DetectorNonVacuity:
    def test_unserialised_driver_trips_the_detector(self):
        """Same driver code path, same detector — only io_lock swapped for a
        no-op lock.  Every SDK call is then unguarded (deterministic), proving
        the guard is what makes the fixed driver pass, not a blind detector."""
        s = _drs_scope(dwell=0.003)
        s.io_lock = _NullLock()                 # transport_lock now returns it too

        stop_flag = threading.Event()

        def _reader():
            while not stop_flag.is_set():
                try:
                    s.read_channel(1)
                except BaseException:           # noqa: BLE001 — irrelevant here
                    pass

        def _acquirer():
            for _ in range(10):
                try:
                    s.read_channel(2)
                except BaseException:           # noqa: BLE001
                    pass

        threads = [threading.Thread(target=_reader, daemon=True),
                   threading.Thread(target=_acquirer, daemon=True)]
        for t in threads:
            t.start()
        threads[1].join(timeout=20.0)
        stop_flag.set()
        for t in threads:
            t.join(timeout=5.0)

        board = s._board
        assert board.calls, "no board I/O happened — non-vacuity check is itself vacuous"
        assert board.unguarded, (
            "detector did NOT flag the unserialised driver — the guard check is blind"
        )

    def test_detector_catches_a_forced_interleave(self):
        """The interleave detector is not blind: two threads deliberately
        overlapped inside one exchange are flagged as a violation."""
        s = _drs_scope(dwell=0.05)
        board = s._board
        barrier = threading.Barrier(2)

        def _hit():
            barrier.wait()                      # force both into the exchange together
            board._exchange("StartDomino")      # no lock held → unguarded + overlap

        threads = [threading.Thread(target=_hit, daemon=True) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert board.violations, "detector failed to catch a forced interleave"
        assert board.unguarded, "detector failed to catch unguarded calls"


# --------------------------------------------------------------------------- #
# stop-path ruling + is_alive + simulation parity                             #
# --------------------------------------------------------------------------- #

class TestDRS4LifecycleContracts:
    def test_scope_has_no_emergency_stop_path(self):
        """A digitiser has no motion to interrupt; there is no stop/abort that
        must bypass the lock (unlike the motor drivers).  Guard the assumption
        so a future stop() is forced to decide its own locking explicitly."""
        s = _drs_scope()
        assert not hasattr(s, "stop")
        assert not hasattr(s, "abort")

    def test_is_alive_inherits_base_and_never_touches_the_board(self):
        """DRS4 does not override is_alive; the base flag-return probes no board
        and takes no lock, so the liveness monitor never contends with an
        in-flight domino read — even while the lock is held mid-acquisition."""
        s = _drs_scope()
        with s.io_lock:                         # simulate mid-exchange
            assert s.is_alive() is True
        assert s._board.calls == [], "is_alive performed board I/O — it must not"

    def test_simulation_read_channel_needs_no_board_and_is_unchanged(self):
        """Rule 3/6 — the sim path returns a waveform with no board and no lock
        contention, behaving exactly as before (1024-sample time/voltage pair)."""
        s = DRS4Oscilloscope(simulation=True)
        s.connect()
        assert s.connected
        t, v = s.read_channel(1)
        assert t.shape == v.shape == (_N,)
