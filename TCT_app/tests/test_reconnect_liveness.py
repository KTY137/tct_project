"""Reconnect-bug regression: liveness overrides + handle-clean reconnect.

Bench symptom (real wavegen + real camera): after the instrument silently
dropped its link, the app kept a stale green flag and every reconnect attempt
died silently until the whole app was restarted.  Two driver-level fixes close
that gap, and these headless tests pin their contract with fake transports —
no VISA, no PySpin, no hardware I/O:

  * Increment 1 — ``is_alive()`` overrides on the WaveformGenerator (IEEE 488.2
    ``*STB?`` heartbeat, mirroring the oscilloscope) and the BlackflyCamera
    (cheap non-blocking ``CameraPtr.IsValid()`` handle check).  Either flips the
    driver to DISCONNECTED the moment the link is gone, so the liveness monitor
    (``DeviceManager.poll_liveness``) can surface a dead device instead of a
    stale flag.
  * Increment 2 — idempotent, handle-clean ``connect``/``disconnect``: the
    wavegen closes AND clears both the VISA session and the ResourceManager
    (the RM used to leak), tears any stale session down at the top of connect(),
    and a raising ``output_off`` no longer aborts the close.  The camera runs
    its guarded release path (EndAcquisition/DeInit/ReleaseInstance) at the top
    of connect() too, so the refcounted PySpin singleton is not leaked and a
    still-``Init``'d camera does not keep the USB device busy across a reconnect.
"""
from __future__ import annotations

import sys
import types

import pytest
import yaml

from devices.base import DeviceError
from devices.waveform_generator import WaveformGenerator
from devices.camera_blackfly import BlackflyCamera


# =========================================================================== #
# Minimal fake transports                                                     #
# =========================================================================== #

class _RaisingVisaInstr:
    """pyvisa-resource stand-in whose ``query`` raises (a dead link)."""

    def __init__(self) -> None:
        self.timeout = 5000

    def query(self, cmd: str) -> str:
        raise RuntimeError("VISA I/O error: link down")

    def close(self) -> None:
        pass


class _HealthyVisaInstr:
    """pyvisa-resource stand-in whose ``*STB?`` answers (a live link)."""

    def __init__(self) -> None:
        self.timeout = 5000
        self.queries: list[str] = []

    def query(self, cmd: str) -> str:
        self.queries.append(cmd)
        return "0\n"          # a status byte

    def close(self) -> None:
        pass


# =========================================================================== #
# 1. WaveformGenerator.is_alive()                                             #
# =========================================================================== #

def test_wavegen_is_alive_flips_connected_false_on_probe_error() -> None:
    """A real-mode wavegen whose ``*STB?`` probe raises must fail safe: the
    method returns False AND the connected flag flips (not just the report)."""
    wfg = WaveformGenerator(simulation=False)
    wfg._connected = True
    instr = _RaisingVisaInstr()
    wfg._instr = instr

    assert wfg.is_alive() is False
    assert wfg.connected is False            # flag flipped, fail-safe
    assert instr.timeout == 5000             # previous timeout restored


def test_wavegen_is_alive_true_on_healthy_probe() -> None:
    """A live ``*STB?`` reply keeps the wavegen alive and connected."""
    wfg = WaveformGenerator(simulation=False)
    wfg._connected = True
    instr = _HealthyVisaInstr()
    wfg._instr = instr

    assert wfg.is_alive() is True
    assert wfg.connected is True
    assert any("STB" in q.upper() for q in instr.queries)   # probed *STB?
    assert instr.timeout == 5000             # restored after the short probe


def test_wavegen_is_alive_busy_lock_reports_alive_without_probe() -> None:
    """If ANOTHER thread holds the io_lock the wavegen is mid-conversation —
    is_alive() must report alive WITHOUT probing (never block the monitor).
    The io_lock is re-entrant, so the contention has to come from a second
    thread (the monitor-vs-scan-thread case), not this one."""
    import threading

    wfg = WaveformGenerator(simulation=False)
    wfg._connected = True
    instr = _HealthyVisaInstr()
    wfg._instr = instr

    holding = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with wfg.io_lock:
            holding.set()
            release.wait(timeout=5)

    t = threading.Thread(target=hold_lock)
    t.start()
    try:
        assert holding.wait(timeout=5), "helper never acquired the io_lock"
        assert wfg.is_alive() is True        # non-contending: no block, no probe
        assert instr.queries == []           # no probe was attempted
    finally:
        release.set()
        t.join(timeout=5)


def test_wavegen_is_alive_simulation_returns_connected_without_io() -> None:
    """Simulation short-circuits: is_alive() returns the connected flag and
    never touches the (here deliberately raising) instrument handle."""
    wfg = WaveformGenerator(simulation=True)
    assert wfg.is_alive() is False           # not connected yet
    wfg.connect()
    # Even with a booby-trapped handle attached, sim must do zero I/O.
    wfg._instr = _RaisingVisaInstr()
    assert wfg.is_alive() is True
    assert wfg.connected is True


def test_wavegen_is_alive_no_session_fails_safe() -> None:
    """Real-mode, flag set but no VISA session → DISCONNECTED."""
    wfg = WaveformGenerator(simulation=False)
    wfg._connected = True                     # stale flag, _instr is None
    assert wfg.is_alive() is False
    assert wfg.connected is False


# =========================================================================== #
# 2. BlackflyCamera.is_alive()                                                #
# =========================================================================== #

class _SpinnakerExceptionLike(Exception):
    """Stand-in for PySpin.SpinnakerException."""


class _ValidCam:
    def IsValid(self) -> bool:
        return True


class _PulledCam:
    """Handle whose IsValid() reports the device is gone (no raise)."""

    def IsValid(self) -> bool:
        return False


class _RaisingCam:
    """Handle whose IsValid() raises a SpinnakerException-like error."""

    def IsValid(self) -> bool:
        raise _SpinnakerExceptionLike("camera pulled from USB bus")


def test_camera_is_alive_true_on_valid_handle() -> None:
    cam = BlackflyCamera(simulation=False)
    cam._connected = True
    cam._cam = _ValidCam()
    assert cam.is_alive() is True
    assert cam.connected is True


def test_camera_is_alive_flips_connected_false_when_handle_invalid() -> None:
    cam = BlackflyCamera(simulation=False)
    cam._connected = True
    cam._cam = _PulledCam()
    assert cam.is_alive() is False
    assert cam.connected is False


def test_camera_is_alive_flips_connected_false_on_spinnaker_exception() -> None:
    cam = BlackflyCamera(simulation=False)
    cam._connected = True
    cam._cam = _RaisingCam()
    assert cam.is_alive() is False
    assert cam.connected is False


def test_camera_is_alive_simulation_returns_connected_without_io() -> None:
    cam = BlackflyCamera(simulation=True)
    assert cam.is_alive() is False           # not connected yet
    cam.connect()
    cam._cam = _RaisingCam()                  # must never be touched in sim
    assert cam.is_alive() is True
    assert cam.connected is True


def test_camera_is_alive_no_handle_fails_safe() -> None:
    cam = BlackflyCamera(simulation=False)
    cam._connected = True                     # stale flag, _cam is None
    assert cam.is_alive() is False
    assert cam.connected is False


# =========================================================================== #
# 3. DeviceManager.poll_liveness() marks wavegen + camera dead                #
# =========================================================================== #

def _sim_dm(tmp_path):
    from controller.device_manager import DeviceManager
    cfg = {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "simulated"},
        "camera":             {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":        {"backend": "simulated"},
        "output":             {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    dm = DeviceManager(config_path=str(path))
    assert dm.config_errors() == [], dm.config_errors()
    results = dm.connect_all()
    assert all(v == "ok" for v in results.values()), results
    return dm


def test_poll_liveness_marks_wavegen_and_camera_dead(tmp_path) -> None:
    """poll_liveness (which the LivenessMonitor calls on a timer) must surface a
    dead wavegen and a dead camera — the coverage that today only exercised the
    scope, extended to the two drivers this reconnect fix adds is_alive() to."""
    dm = _sim_dm(tmp_path)
    try:
        # Everything simulated → all links report alive first.
        healthy = dm.poll_liveness()
        assert healthy["Waveform Generator"] is True
        assert healthy["Camera"] is True
        assert healthy["Oscilloscope"] is True

        # Now simulate a silent link death on the two reconnect-bug devices by
        # flipping them to real-mode with a dead handle.  The others stay sim.
        dm.waveform_generator.simulation = False
        dm.waveform_generator._connected = True
        dm.waveform_generator._instr = _RaisingVisaInstr()

        dm.camera.simulation = False
        dm.camera._connected = True
        dm.camera._cam = _RaisingCam()

        dead = dm.poll_liveness()
        assert dead["Waveform Generator"] is False
        assert dead["Camera"] is False
        # Unaffected simulated devices still report alive.
        assert dead["Oscilloscope"] is True
        assert dead["Motor Stage"] is True

        # The drivers' own flags flipped — not just the poll report.
        assert dm.waveform_generator.connected is False
        assert dm.camera.connected is False
    finally:
        dm.disconnect_all()


# =========================================================================== #
# 4. WaveformGenerator connect/disconnect handle lifecycle (no leaks)         #
# =========================================================================== #

class _CountingInstr:
    """VISA session stand-in that answers a real connect() and counts closes."""

    def __init__(self, counters: dict) -> None:
        self.timeout = 5000
        self._counters = counters
        self.writes: list[str] = []

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query(self, cmd: str) -> str:
        up = cmd.upper()
        if "IDN" in up:
            return "RIGOL TECHNOLOGIES,DG4162,SN,00.01.14\n"
        if "STAT" in up:                 # :OUTPut{ch}:STATe? (armed resolve)
            return "OFF\n"
        if "WIDT" in up:                 # pulse-width read-back
            return "1.000000e-06\n"
        return "0\n"

    def close(self) -> None:
        self._counters["sess_close"] += 1


class _CountingRM:
    """pyvisa.ResourceManager stand-in counting opens/closes of RM + sessions."""

    def __init__(self, counters: dict) -> None:
        counters["rm_open"] += 1
        self._counters = counters

    def open_resource(self, addr: str) -> _CountingInstr:
        self._counters["sess_open"] += 1
        return _CountingInstr(self._counters)

    def close(self) -> None:
        self._counters["rm_close"] += 1


def _install_counting_pyvisa(monkeypatch, counters: dict) -> None:
    """Inject a fake ``pyvisa`` module so connect() runs without a real VISA."""
    fake = types.ModuleType("pyvisa")
    fake.ResourceManager = lambda *a, **k: _CountingRM(counters)   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyvisa", fake)


def test_wavegen_reconnect_closes_every_session_and_rm(monkeypatch) -> None:
    """connect → disconnect → connect → disconnect: every VISA session AND every
    ResourceManager that was opened is closed — none leaked (the RM leak was the
    silent-death reconnect root)."""
    counters = {"rm_open": 0, "rm_close": 0, "sess_open": 0, "sess_close": 0}
    _install_counting_pyvisa(monkeypatch, counters)
    wfg = WaveformGenerator(simulation=False, vendor="rigol",
                            visa_address="TCPIP0::10.0.0.1::INSTR")
    wfg.connect()
    wfg.disconnect()
    wfg.connect()
    wfg.disconnect()

    assert counters["rm_open"] == 2
    assert counters["rm_open"] == counters["rm_close"]      # no RM leaked
    assert counters["sess_open"] == 2
    assert counters["sess_open"] == counters["sess_close"]  # no session leaked
    assert wfg._instr is None and wfg._rm is None
    assert wfg.connected is False


def test_wavegen_dirty_reconnect_tears_down_prior_session(monkeypatch) -> None:
    """A second connect() with NO intervening disconnect (dirty death) must tear
    the stale session + RM down first — the idempotent-connect guarantee."""
    counters = {"rm_open": 0, "rm_close": 0, "sess_open": 0, "sess_close": 0}
    _install_counting_pyvisa(monkeypatch, counters)
    wfg = WaveformGenerator(simulation=False, vendor="rigol",
                            visa_address="TCPIP0::10.0.0.1::INSTR")
    wfg.connect()
    assert counters["sess_close"] == 0 and counters["rm_close"] == 0

    wfg.connect()                              # dirty reconnect, no disconnect
    # The first session AND RM were closed by the second connect's teardown.
    assert counters["sess_close"] == 1
    assert counters["rm_close"] == 1
    assert counters["sess_open"] == 2
    assert counters["rm_open"] == 2

    wfg.disconnect()
    assert counters["sess_open"] == counters["sess_close"] == 2
    assert counters["rm_open"] == counters["rm_close"] == 2


def test_wavegen_disconnect_with_raising_output_off_still_closes(monkeypatch) -> None:
    """A dead-socket ``output_off()`` during disconnect must not abort the close:
    the session and RM are still torn down and the flag cleared."""
    counters = {"rm_open": 0, "rm_close": 0, "sess_open": 0, "sess_close": 0}
    _install_counting_pyvisa(monkeypatch, counters)
    wfg = WaveformGenerator(simulation=False, vendor="rigol",
                            visa_address="TCPIP0::10.0.0.1::INSTR")
    wfg.connect()
    wfg._output_on = True                      # pretend the trigger is armed

    def boom() -> None:
        raise DeviceError("write to a dead socket")

    wfg.output_off = boom                      # type: ignore[method-assign]

    wfg.disconnect()                           # must NOT raise
    assert counters["sess_close"] == 1         # session still closed
    assert counters["rm_close"] == 1           # RM still closed
    assert wfg._instr is None and wfg._rm is None
    assert wfg.connected is False


# =========================================================================== #
# 5. BlackflyCamera dirty reconnect — refcount + Init balance                 #
# =========================================================================== #

class _AutoNode:
    """Generic QuickSpin node: SetValue/GetValue/GetMin/GetMax no-ops."""

    def __init__(self) -> None:
        self._v = 0.0

    def SetValue(self, v) -> None:
        self._v = v

    def SetIntValue(self, v) -> None:
        self._v = v

    def GetValue(self):
        return self._v

    def GetMin(self):
        return 0.0

    def GetMax(self):
        return 1_000_000.0

    def GetEntryByName(self, name) -> "_AutoNode":
        return _AutoNode()

    def GetNode(self, name) -> "_AutoNode":
        return _AutoNode()


class _FakeSpinCam:
    """Fake CameraPtr: counts Init/DeInit; can be flipped to fail on DeInit
    (a pulled device whose handle now errors on release)."""

    def __init__(self, counters: dict) -> None:
        self._c = counters
        self._nodes: dict = {}
        self.fail_deinit = False

    def __getattr__(self, name):             # any settings node → generic node
        nodes = self.__dict__["_nodes"]
        if name not in nodes:
            nodes[name] = _AutoNode()
        return nodes[name]

    def Init(self) -> None:
        self._c["init"] += 1

    def DeInit(self) -> None:
        self._c["deinit"] += 1
        if self.fail_deinit:
            raise _SpinnakerExceptionLike("camera pulled: DeInit failed")

    def BeginAcquisition(self) -> None:
        pass

    def EndAcquisition(self) -> None:
        pass

    def IsValid(self) -> bool:
        return not self.fail_deinit

    def GetTLStreamNodeMap(self) -> _AutoNode:
        return _AutoNode()

    def GetTLDeviceNodeMap(self) -> _AutoNode:
        return _AutoNode()


class _FakeCamList:
    def __init__(self, counters: dict, present: bool) -> None:
        self._cam = _FakeSpinCam(counters) if present else None
        self._present = present

    def GetSize(self) -> int:
        return 1 if self._present else 0

    def GetBySerial(self, serial):
        return self._cam

    def GetByIndex(self, i):
        return self._cam

    def Clear(self) -> None:
        pass


class _FakeSpinSystem:
    """Fake refcounted System singleton: counts GetInstance/ReleaseInstance."""

    def __init__(self, counters: dict, present: bool) -> None:
        self._c = counters
        self._present = present

    def GetInstance(self) -> "_FakeSpinSystem":
        self._c["getinstance"] += 1
        return self

    def ReleaseInstance(self) -> None:
        self._c["release"] += 1

    def GetCameras(self) -> _FakeCamList:
        return _FakeCamList(self._c, self._present)


class _FakePySpin(types.ModuleType):
    """Minimal fake ``PySpin`` module sufficient for a full connect()/release."""

    def __init__(self, counters: dict, present: bool = True) -> None:
        super().__init__("PySpin")
        self._c = counters
        self.System = _FakeSpinSystem(counters, present)
        self.SpinnakerException = _SpinnakerExceptionLike

    def __getattr__(self, name):             # any enum constant → a sentinel
        return name

    def IsAvailable(self, node) -> bool:
        return True

    def IsWritable(self, node) -> bool:
        return True

    def IsReadable(self, node) -> bool:
        return True

    def CEnumerationPtr(self, node):
        return node

    def CStringPtr(self, node):
        return node


def test_camera_dirty_reconnect_balances_refcount_and_init(monkeypatch) -> None:
    """A silent USB drop mid-session: the held camera handle now errors on
    release.  A reconnect (no disconnect) must still release the stale
    System/camera BEFORE re-acquiring the singleton, so the refcounted
    GetInstance()/ReleaseInstance pair stays balanced and the pulled camera is
    DeInit'd (freeing the USB device) instead of leaked until an app restart."""
    counters = {"getinstance": 0, "release": 0, "init": 0, "deinit": 0}
    fake_ps = _FakePySpin(counters, present=True)
    monkeypatch.setitem(sys.modules, "PySpin", fake_ps)

    cam = BlackflyCamera(simulation=False, serial_number="")
    cam.connect()
    assert cam.connected is True
    assert counters["getinstance"] == 1
    assert counters["init"] == 1
    assert counters["deinit"] == 0
    assert counters["release"] == 0

    # Simulate a pull: the currently-held handle now errors on DeInit.
    first_cam = cam._cam
    first_cam.fail_deinit = True

    # Dirty reconnect (no disconnect first).
    cam.connect()
    assert cam.connected is True
    assert counters["getinstance"] == 2         # fresh singleton acquired
    assert counters["deinit"] == 1              # stale camera DeInit attempted
    assert counters["release"] == 1             # stale system released, not leaked
    # Refcount balance: exactly one live session outstanding.
    assert counters["getinstance"] - counters["release"] == 1

    # A clean disconnect releases the final session → fully balanced.
    cam.disconnect()
    assert cam.connected is False
    assert counters["getinstance"] == counters["release"] == 2
    assert counters["deinit"] == 2
    assert cam._cam is None and cam._system is None
