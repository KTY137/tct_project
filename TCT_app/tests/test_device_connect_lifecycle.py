"""Connect / disconnect lifecycle & cross-thread concurrency regressions for
the VISA drivers.

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

Follow-up beat (2026-07-14, Mary's riders on 7b4ea94): the same unbounded-viOpen
freeze class existed in every VISA driver — an offline / powered-off instrument
on the isolated LAN/USB blocks inside ``viOpen`` for the full OS socket window
because ``open_resource`` carried no ``open_timeout``.  The cross-driver section
below pins, for the wavegen + both scopes + both HV supplies, that connect():
  * forwards ``open_timeout`` (the connection-establishment cap) to viOpen, and
  * fails safe on an open error — no leaked ResourceManager / session, and
    ``connected`` goes False even from a RECONNECT over a prior live flag (so a
    starting scan cannot silently write to a dead session).

No hardware: fake pyvisa resources exercised across real Python threads; every
connect() runs against an injected fake ``pyvisa`` module and never touches a
real instrument.
"""
import sys
import threading
import time
import types

import pytest

from devices.base import DeviceError
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


# =========================================================================== #
# Cross-driver open path: open_timeout forwarded + fail-safe on open error     #
# (Mary's riders on 7b4ea94 — the unbounded-viOpen freeze class in every VISA  #
# driver).  Each connect() runs against a fake pyvisa whose open_resource       #
# records the connection-establishment cap and then fails the open (an offline  #
# / powered-off instrument).  The driver must have forwarded open_timeout and   #
# must fail safe: no leaked ResourceManager / session, and connected False even #
# from a RECONNECT (a live prior flag must not survive a dead open).            #
# =========================================================================== #

class _RecordingBoomRM:
    """pyvisa.ResourceManager stand-in: records the ``open_timeout`` handed to
    ``open_resource`` and then fails the open (models an offline / unreachable
    target).  Accepts ``timeout`` too — Keithley passes the per-op timeout on
    open_resource as well.  ``closed`` proves the fail-safe teardown closed it."""

    def __init__(self) -> None:
        self.open_timeout: object = "unset"    # sentinel: connect() never passed it
        self.closed = False

    def open_resource(self, addr, open_timeout=None, timeout=None, **kw):
        self.open_timeout = open_timeout
        raise OSError("simulated viOpen timeout — instrument offline / unreachable")

    def close(self) -> None:
        self.closed = True


def _install_fake_pyvisa(monkeypatch, rm) -> None:
    """Inject a fake ``pyvisa`` module so a real-mode connect() runs the open
    path without a real VISA backend — never touching an instrument."""
    fake = types.ModuleType("pyvisa")
    fake.ResourceManager = lambda *a, **k: rm     # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyvisa", fake)


def test_wavegen_failed_reconnect_forwards_timeout_and_marks_disconnected(
        monkeypatch) -> None:
    """Mary's rider a: a RECONNECT whose viOpen fails must tear the prior session
    down, leak nothing, and drop the connected flag — otherwise a starting scan
    would silently write to a dead session for up to one liveness poll."""
    rm = _RecordingBoomRM()
    _install_fake_pyvisa(monkeypatch, rm)
    wfg = WaveformGenerator(simulation=False, vendor="rigol",
                            visa_address="TCPIP0::192.168.0.10::INSTR",
                            timeout_ms=3000)
    prior = _FakeInstr()
    wfg._instr = prior
    wfg._connected = True                     # a live prior session → a reconnect
    with pytest.raises(DeviceError):
        wfg.connect()
    assert prior.closed                       # prior session torn down at connect top
    assert wfg._instr is None
    assert wfg._rm is None                     # no leaked ResourceManager
    assert wfg.connected is False             # fail to a safe disconnected state
    assert rm.open_timeout == 3000            # connection-establishment cap forwarded
    assert rm.closed                          # half-open RM closed, not leaked


def test_oscilloscope_open_failure_forwards_timeout_and_fails_safe(
        monkeypatch) -> None:
    """VISA scope: open_timeout forwarded; a failed open leaks nothing and clears
    connected even from a reconnect."""
    from devices.oscilloscope import Oscilloscope
    rm = _RecordingBoomRM()
    _install_fake_pyvisa(monkeypatch, rm)
    scope = Oscilloscope(simulation=False,
                         visa_address="TCPIP0::192.168.0.20::INSTR",
                         timeout_ms=4000)
    scope._connected = True                    # reconnect over a prior live flag
    with pytest.raises(DeviceError):
        scope.connect()
    assert rm.open_timeout == 4000             # open_timeout forwarded to viOpen
    assert scope._instr is None
    assert scope._rm is None                   # no leaked ResourceManager
    assert scope.connected is False           # fail-safe, even from a reconnect
    assert rm.closed


def test_fastframe_open_failure_forwards_timeout_and_fails_safe(
        monkeypatch) -> None:
    """Tek FastFrame scope: same contract.  The vendored dustin import is stubbed
    so connect() reaches the open path without the (optional) vendor package."""
    import devices.oscilloscope_tek_fastframe as ff
    rm = _RecordingBoomRM()
    _install_fake_pyvisa(monkeypatch, rm)
    monkeypatch.setattr(ff, "_import_dustin_mso5204b",
                        lambda: (object(), object(), object()))
    scope = ff.TekFastFrameOscilloscope(simulation=False,
                                        visa_address="TCPIP0::192.168.0.21::INSTR",
                                        timeout_ms=6000)
    scope._connected = True
    with pytest.raises(DeviceError):
        scope.connect()
    assert rm.open_timeout == 6000
    assert scope._instr is None
    assert scope._rm is None
    assert scope.connected is False
    assert rm.closed


def test_iseg_open_failure_forwards_timeout_and_fails_safe(monkeypatch) -> None:
    """iseg HV supply: open_timeout forwarded; a failed connect leaks no session /
    RM and clears connected.  connect() never enables HV, so tearing the link
    down on failure energizes nothing."""
    from devices.bias_supply_iseg import IsegBiasSupply
    rm = _RecordingBoomRM()
    _install_fake_pyvisa(monkeypatch, rm)
    sup = IsegBiasSupply(visa_address="TCPIP0::192.168.0.30::INSTR",
                         simulation=False, timeout_ms=3500)
    sup._connected = True
    with pytest.raises(DeviceError):
        sup.connect()
    assert rm.open_timeout == 3500
    assert sup._inst is None                   # iseg names its handle _inst
    assert sup._rm is None
    assert sup.connected is False
    assert rm.closed


def test_keithley_open_failure_forwards_timeout_and_fails_safe(monkeypatch) -> None:
    """Keithley HV supply: forwards open_timeout ALONGSIDE the existing per-op
    timeout= (Mary's find: only the per-op one was bounded), and fails safe."""
    from devices.bias_supply_keithley import KeithleyBiasSupply
    rm = _RecordingBoomRM()
    _install_fake_pyvisa(monkeypatch, rm)
    sup = KeithleyBiasSupply(visa_address="TCPIP0::192.168.0.31::INSTR",
                             simulation=False, timeout_ms=4500)
    sup._connected = True
    with pytest.raises(DeviceError):
        sup.connect()
    assert rm.open_timeout == 4500             # open_timeout, not just per-op timeout=
    assert sup._inst is None
    assert sup._rm is None
    assert sup.connected is False
    assert rm.closed
