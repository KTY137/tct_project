"""Connect / disconnect lifecycle & cross-thread concurrency regressions for
the VISA waveform-generator driver.

Bug beat (2026-07-14, Kaya): connecting to the real Rigol wavegen sometimes
froze the GUI, then crashed intermittently.  Two driver-side root causes are
pinned here (the GUI-thread half of the freeze/crash lives in the tct_gui.py /
device_panel.py _run_bg workers and is fixed separately):

  * The liveness monitor (gui.liveness.LivenessMonitor) polls ``is_alive()``
    from ITS OWN thread and touches the shared VISA session under ``io_lock``.
    Closing / re-opening that session on the connect worker thread must be
    serialized on the SAME ``io_lock`` — otherwise a ``*STB?`` probe and a
    session ``close()`` race on one handle, which is a Windows access violation
    (the intermittent connect / reconnect crash).
  * ``is_alive()`` must stay NON-contending: while a connect/teardown holds
    ``io_lock`` it must report "presumed alive" immediately, never block the
    monitor thread and never touch the half-open handle.

No hardware: a fake pyvisa resource exercised across real Python threads.
"""
import threading
import time

from devices.waveform_generator import WaveformGenerator


class _FakeInstr:
    """Minimal pyvisa-resource stand-in for lifecycle tests."""

    def __init__(self) -> None:
        self.timeout = 5000
        self.closed = False

    def query(self, cmd: str) -> str:
        return "RIGOL TECHNOLOGIES,DG4162,DG4E000000000,00.01.14\n"

    def write(self, cmd: str) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def _wired() -> WaveformGenerator:
    """A real-mode wavegen with a fake session injected as if connected."""
    wfg = WaveformGenerator(simulation=False, vendor="rigol")
    wfg._instr = _FakeInstr()
    wfg._connected = True
    return wfg


def test_teardown_session_serialized_on_io_lock() -> None:
    """_teardown_session() must hold io_lock across the close, so a liveness
    probe holding io_lock can never use the handle teardown is destroying.

    Proof: a helper thread holds io_lock; a teardown started from a DIFFERENT
    thread must block on it (io_lock is an RLock — cross-thread it blocks) and
    only close the handle once the lock is released."""
    wfg = _wired()
    lock_held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with wfg.io_lock:
            lock_held.set()
            release.wait(2.0)

    holder_t = threading.Thread(target=holder)
    holder_t.start()
    assert lock_held.wait(1.0), "holder never acquired io_lock"

    done = threading.Event()

    def teardown() -> None:
        wfg._teardown_session()
        done.set()

    td = threading.Thread(target=teardown)
    td.start()
    time.sleep(0.15)
    # Holder still owns io_lock → teardown (a different thread) is blocked.
    assert not done.is_set(), "teardown ran without holding io_lock (the race)"
    assert wfg._instr is not None, "handle closed before the lock was free"

    release.set()
    td.join(2.0)
    assert done.is_set(), "teardown never completed after lock release"
    assert wfg._instr is None, "handle not closed after teardown"
    holder_t.join(2.0)


def test_is_alive_non_contending_while_session_locked() -> None:
    """While another thread holds io_lock (a connect/teardown in flight),
    is_alive() must return True immediately — never block, never probe the
    half-open handle."""
    wfg = _wired()
    lock_held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with wfg.io_lock:
            lock_held.set()
            release.wait(2.0)

    holder_t = threading.Thread(target=holder)
    holder_t.start()
    assert lock_held.wait(1.0), "holder never acquired io_lock"

    start = time.time()
    assert wfg.is_alive() is True                 # presumed alive, non-contending
    assert time.time() - start < 0.5, "is_alive blocked on the held io_lock"

    release.set()
    holder_t.join(2.0)


def test_disconnect_closes_session_and_marks_down() -> None:
    """A normal disconnect closes the handle, clears both handles, and flips the
    connected flag — the clean teardown the reconnect path depends on."""
    wfg = _wired()
    instr = wfg._instr
    wfg.disconnect()
    assert instr.closed
    assert wfg._instr is None
    assert wfg._rm is None
    assert wfg.connected is False
