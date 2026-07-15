"""MEASUREMENT B -- the acquisition-headroom spike (Lantern U2 entry gate).

WHAT THIS MEASURES (docs/design/qml_kit_forge/candidate_lantern.md SS7)
-----------------------------------------------------------------------
Measurement A proved the frost bake is O(1) in pane count on the worst-case
iGPU (fps 59.98, island >= 30.31 Hz through 8 panes @ 12 Hz; commit 4c5de40).
What A did NOT measure is that same idle-rate bake + living ground running
THROUGH a real acquisition load. SS7 names measurement B as the U2 entry
gate and states its protocol exactly:

    "idle-rate bake + living ground at `full`, running through a live
     *simulated* scan (sim DeviceManager + scan controller + HDF5 writer +
     a 30 Hz plot island) on the lab laptop, asserting the plot holds rate
     and DAQ cadence does not jitter. If B fails, the fallback is run-active
     global calm (bake -> 0 Hz app-wide)."

This harness composes exactly those existing pieces (it edits NONE of them):

  * a sim ``DeviceManager`` (every backend forced to its simulated class /
    ``simulation=True`` -- verified by a hard guard, SS"SAFETY" below);
  * the real ``ScanController`` + ``StateMachine`` driving a classic XY scan
    (``ScanController.start(ScanConfig)``), which the controller itself backs
    with a fresh per-run ``HDF5Writer`` writing into a TEMP directory;
  * a real 30 Hz ``pyqtgraph`` plot island in its own top-level QWidget,
    fed the live per-point DUT charge from the scan's ``on_point_done``
    callback -- the "live scan plot island" of SS7;
  * the Lantern living ground + ONE frost bake @ 12 Hz + N crop-sampler panes,
    the exact ``layer.live:false`` + timed ``scheduleUpdate()`` mechanism from
    the measurement-A spike (``scripts/spikes/lantern_frost_bake_spike.py``).

WITH / WITHOUT design (two independent probes, this repo's rule)
----------------------------------------------------------------
The headroom question is a *comparison*, so B measures two cells in one
process, back to back, on ONE DeviceManager + controller:

  * ``baseline`` -- sim scan + 30 Hz island, NO frost scene rendered. This is
    the acquisition-alone reference: what plot rate + DAQ cadence the laptop
    sustains before any Lantern paint is added.
  * ``loaded``   -- the SAME sim scan + island, PLUS the living ground at
    ``full`` + the frost bake @ 12 Hz + N live panes. Worst case on purpose:
    every pane keeps sampling the bake (no run-owning-pane freeze), so the
    shared bake serves the whole flowing room exactly as SS3.2 says it must
    during a scan.

VERDICT (printed PASS/FAIL block; SS7 assertions, measurement-A floors)
-----------------------------------------------------------------------
  (P1) plot holds rate:  loaded island_hz >= ISLAND_HZ_FLOOR (28.0) AND
                         loaded island_hz >= baseline * ISLAND_RETENTION (0.90)
  (P2) DAQ does not jitter: loaded point-rate >= baseline * DAQ_RATE_RETENTION
                         (0.80) AND loaded inter-point CV <= max(baseline CV
                         * 1.5, DAQ_CV_ABS_MAX 0.50)
  (P3) frost scene renders: loaded qml_fps >= QML_FPS_FLOOR (55.0)

SS7 named the assertions ("plot holds rate", "DAQ cadence does not jitter")
but not the numbers; the floors are inherited from measurement A and the
retention/jitter tolerances are the entry-gate PROPOSAL -- the live operator
tunes them from the printed numbers before ratifying the gate.

EXIT CODES
----------
  0  PASS   -- both assertions held under load
  2  FAIL   -- an assertion failed (SS7 fallback: run-active global calm)
  3  GUARD  -- sim-only guard tripped (a backend did not resolve to sim) OR
               a real desktop session was required and not present
  4  ERROR  -- unexpected harness failure

RUN
---
  # mechanics smoke (headless, offscreen; NO fps assertions -- what an agent
  # is permitted to run):
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe scripts/spike_measurement_b.py --smoke

  # the real windowed measurement (a real desktop GPU session; OPERATOR ONLY --
  # standing rule: agents do not run windowed GUI locally, instruments may be
  # cabled):
  .venv/Scripts/python.exe scripts/spike_measurement_b.py

SAFETY
------
Sim-only by construction AND by guard. The harness builds its OWN forced-sim
config (every backend = simulated, ``simulation: true``, ``output.data_dir``
= a temp path) and then ``assert_simulated`` re-verifies every constructed
device instance is in simulation mode BEFORE ``connect_all`` performs any I/O.
If ANY device is not simulated the harness refuses to start (exit 3) and never
connects. It imports no real transport driver module directly (it goes through
the app's own composition root, ``DeviceManager``, exactly as SS7 specifies).
The scan writes HDF5 into a temp directory only -- never a real data dir.

NOT app code. NOT imported by the app. NOT part of the test suite.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

# --- make the TCT_app package importable when run as a bare script ---------- #
_SCRIPTS = Path(__file__).resolve().parent
_TCT_APP = _SCRIPTS.parent
_REPO_ROOT = _TCT_APP.parent
if str(_TCT_APP) not in sys.path:
    sys.path.insert(0, str(_TCT_APP))

ISLAND_NOMINAL_HZ = 30
DEFAULT_PANES = 6
DEFAULT_REBAKE_HZ = 12.0        # living ground "full" -> 12 Hz bake (SS3.2)
DEFAULT_SECONDS = 15.0
DEFAULT_WARMUP_S = 3.0
BLUR_MAX_PX = 40                # matches candidate_lantern.md SS6 blurPane token

# Verdict thresholds (see module docstring "VERDICT").
ISLAND_HZ_FLOOR = 28.0
QML_FPS_FLOOR = 55.0
ISLAND_RETENTION = 0.90
DAQ_RATE_RETENTION = 0.80
DAQ_CV_ABS_MAX = 0.50

# Exit codes.
EXIT_PASS = 0
EXIT_FAIL = 2
EXIT_GUARD = 3
EXIT_ERROR = 4

# A Windows access violation surfaces as 0xC0000005 (two encodings).
_SEGFAULT_CODES = (-1073741819, 3221225477)


# --------------------------------------------------------------------------- #
# Process CPU (no psutil in this venv -- same GetProcessTimes path as the      #
# measurement-A spike; see its _proc_cpu_seconds docstring)                    #
# --------------------------------------------------------------------------- #

class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _proc_cpu_seconds() -> float:
    """Kernel+user CPU seconds burned by THIS process (Windows only)."""
    if sys.platform != "win32":
        return float("nan")
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FILETIME),
                                    ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
                                    ctypes.POINTER(_FILETIME)]
    k32.GetProcessTimes.restype = wintypes.BOOL
    creation, exit_t, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
    ok = k32.GetProcessTimes(k32.GetCurrentProcess(), ctypes.byref(creation),
                             ctypes.byref(exit_t), ctypes.byref(kernel),
                             ctypes.byref(user))
    if not ok:
        return float("nan")

    def _s(ft: _FILETIME) -> float:
        return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7

    return _s(kernel) + _s(user)


def _settle(ms: int) -> None:
    """Spin the Qt event loop for ``ms`` without blocking it (no time.sleep)."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(max(1, ms), loop.quit)
    loop.exec()


def _check_real_session() -> str | None:
    """Return a refusal reason if the Qt platform is headless (real run only)."""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    platform = app.platformName() if app else ""
    if platform in ("offscreen", "minimal"):
        return (f"refusing the windowed measurement under QT_QPA_PLATFORM={platform!r} "
                "-- it needs a real on-screen GPU/compositor. Use --smoke for the "
                "headless mechanics check.")
    return None


# --------------------------------------------------------------------------- #
# SAFETY -- the sim-only guard (built first; SS"SAFETY" in the module doc)     #
# --------------------------------------------------------------------------- #

class SimOnlyViolation(RuntimeError):
    """Raised when a constructed device does not resolve to simulation mode."""


# Device attributes on a DeviceManager that MUST be in simulation mode. The
# bias supply is a BiasChannel proxy over a driver, so its driver (_bias_driver)
# is checked directly. Every BaseDevice carries ``.simulation`` (devices/base.py),
# and the *_simulated classes default it True.
def assert_simulated(dev) -> None:
    """Fail closed unless EVERY backend on *dev* is in simulation mode.

    Checks ``.simulation is True`` on every real device instance the harness
    will drive. Raises :class:`SimOnlyViolation` naming every offender. Must be
    called BEFORE ``connect_all`` -- it is the gate that keeps a mis-pointed
    config from ever performing hardware I/O.
    """
    checks = {
        "motor": getattr(dev, "motor", None),
        "scope": getattr(dev, "scope", None),
        "camera": getattr(dev, "camera", None),
        "waveform_generator": getattr(dev, "waveform_generator", None),
        "intensity_monitor": getattr(dev, "intensity_monitor", None),
        "bias_driver": getattr(dev, "_bias_driver", None),
    }
    bad: list[str] = []
    for name, d in checks.items():
        if d is None:
            bad.append(f"{name}=<missing>")
            continue
        sim = getattr(d, "simulation", None)
        if sim is not True:
            bad.append(f"{name}={type(d).__name__}(simulation={sim!r})")
    if bad:
        raise SimOnlyViolation(
            "sim-only guard TRIPPED -- these backends did not resolve to "
            "simulation mode: " + ", ".join(bad)
        )


def _forced_sim_config(data_dir: Path) -> dict:
    """A devices.yaml dict that forces EVERY backend to its simulated form.

    Belt-and-suspenders with :func:`assert_simulated`: this makes the sim path
    the only one DeviceManager can construct, and the guard then re-verifies it.
    ``output.data_dir`` is an absolute TEMP path so the scan's HDF5 never lands
    in a real data directory.
    """
    return {
        "oscilloscope": {"backend": "visa", "simulation": True},
        "motor_stage": {"backend": "simulated", "simulation": True},
        "intensity_monitor": {"backend": "simulated"},
        "bias_supply": {"backend": "simulated"},
        "camera": {"simulation": True},
        "waveform_generator": {"simulation": True},
        "output": {"data_dir": str(data_dir),
                   # heavy save path = realistic acquisition I/O under the plot
                   "save": {"waveforms": True, "camera_frame": False}},
    }


def build_sim_device_manager(data_dir: Path):
    """Construct a guarded sim DeviceManager. Raises SimOnlyViolation on any
    non-sim backend BEFORE any connection is attempted."""
    import yaml
    from controller.device_manager import DeviceManager

    cfg_path = data_dir / "measurement_b_devices.yaml"
    cfg_path.write_text(yaml.safe_dump(_forced_sim_config(data_dir)), encoding="utf-8")
    dev = DeviceManager(str(cfg_path))
    assert_simulated(dev)                 # <-- the gate, before connect_all
    return dev


def home_sim_stage(dev) -> None:
    """Home the SIMULATED stage so the scan's ``move_to`` calls are legal.

    ``SimulatedMotorStage.home()`` sets an in-memory ``_homed`` flag and does NO
    hardware I/O -- it is the sim twin of the operator homing before a scan.
    Re-asserts the motor is in simulation mode immediately before the call
    (defense in depth on top of :func:`assert_simulated`): this can only ever
    reach a simulated stage, never a real one (safety rule 1).
    """
    if getattr(dev.motor, "simulation", None) is not True:
        raise SimOnlyViolation(
            f"refusing to home {type(dev.motor).__name__}: not in simulation mode")
    dev.motor.home()


def _walk_to_ready(sm) -> None:
    """Advance the StateMachine label DISCONNECTED -> READY.

    Pure state-machine transitions only -- NO hardware homing / motion is
    commanded (safety rule 1). The scan controller only needs ``can(RUNNING)``,
    which is legal from READY.
    """
    from controller.state_machine import AppState
    for target in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
        if sm.can(target):
            sm.transition(target)


def _reset_to_ready(sm) -> None:
    """Return a terminal (FINISHED/ABORTED/ERROR) state machine to READY."""
    from controller.state_machine import AppState
    if sm.can(AppState.CONFIGURED):
        sm.transition(AppState.CONFIGURED)
    if sm.can(AppState.READY):
        sm.transition(AppState.READY)


# --------------------------------------------------------------------------- #
# The live scan plot island -- a REAL pyqtgraph PlotWidget fed by the scan      #
# --------------------------------------------------------------------------- #

class Island:
    """Top-level QWidget hosting a pyqtgraph PlotWidget at a nominal 30 Hz,
    plotting the live per-point DUT charge pushed by the scan's on_point_done.

    ``tick_times`` records wall-clock timestamps of every actual update; the
    effective rate is derived from THESE, not the QTimer nominal interval."""

    def __init__(self, x: int, y: int) -> None:
        import numpy as np
        import pyqtgraph as pg
        from PySide6.QtCore import QTimer, Qt
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        self._np = np
        self._lock = threading.Lock()
        self._charges: deque = deque(maxlen=600)
        self.tick_times: list[float] = []

        self.widget = QWidget(None)
        self.widget.setWindowTitle("measurement_b -- live scan plot island (30 Hz)")
        self.widget.setGeometry(x, y, 460, 300)
        layout = QVBoxLayout(self.widget)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "scan point")
        self.plot.setLabel("left", "DUT charge [pC]")
        self.curve = self.plot.plot(pen=pg.mkPen("#5FD3C4", width=2))
        layout.addWidget(self.plot)

        self._timer = QTimer(self.widget)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # called from the SCAN worker thread
    def push_charge(self, charge: float) -> None:
        with self._lock:
            self._charges.append(float(charge))

    def show(self) -> None:
        self.widget.show()

    def start(self) -> None:
        self.tick_times = []
        self._timer.start(round(1000 / ISLAND_NOMINAL_HZ))

    def stop(self) -> None:
        self._timer.stop()

    def close(self) -> None:
        self._timer.stop()
        self.widget.close()

    def _tick(self) -> None:
        with self._lock:
            data = self._np.array(self._charges, dtype=float)
        if data.size:
            self.curve.setData(data)
        self.tick_times.append(time.perf_counter())

    def effective_hz(self) -> float:
        tt = self.tick_times
        if len(tt) < 2:
            return 0.0
        return (len(tt) - 1) / (tt[-1] - tt[0])


# --------------------------------------------------------------------------- #
# The scan cadence probe -- timestamps every on_point_done (DAQ cadence)       #
# --------------------------------------------------------------------------- #

class CadenceProbe:
    """Records a wall-clock timestamp for every completed scan point and pushes
    its DUT charge into the island. ``on_point`` is wired to
    ``ScanController.on_point_done`` and runs on the SCAN worker thread."""

    def __init__(self, island: Island | None) -> None:
        self._island = island
        self._lock = threading.Lock()
        self._times: list[float] = []
        self._recording = False

    def on_point(self, result) -> None:
        if self._island is not None:
            self._island.push_charge(getattr(result, "dut_charge_pC", 0.0))
        with self._lock:
            if self._recording:
                self._times.append(time.perf_counter())

    def start_window(self) -> None:
        with self._lock:
            self._times = []
            self._recording = True

    def stop_window(self) -> None:
        with self._lock:
            self._recording = False

    def stats(self) -> dict:
        with self._lock:
            times = list(self._times)
        n = len(times)
        if n < 2:
            return {"points": n, "rate_hz": 0.0, "mean_interval_s": None,
                    "std_interval_s": None, "cv": None, "max_interval_s": None}
        intervals = [t2 - t1 for t1, t2 in zip(times, times[1:])]
        span = times[-1] - times[0]
        mean = sum(intervals) / len(intervals)
        var = sum((iv - mean) ** 2 for iv in intervals) / len(intervals)
        std = math.sqrt(var)
        return {
            "points": n,
            "rate_hz": round((n - 1) / span, 3) if span > 0 else 0.0,
            "mean_interval_s": round(mean, 5),
            "std_interval_s": round(std, 5),
            "cv": round(std / mean, 4) if mean > 0 else None,
            "max_interval_s": round(max(intervals), 5),
        }


# --------------------------------------------------------------------------- #
# The Lantern frost scene -- living ground + ONE bake + N crop-sampler panes    #
# (reused verbatim mechanism from scripts/spikes/lantern_frost_bake_spike.py)  #
# --------------------------------------------------------------------------- #

_QML = """
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property int paneCount: 6
    property real rebakeHz: 12
    property bool groundOn: true          // living ground at "full"
    property int bakeCount: 0

    readonly property int cols: Math.max(1, Math.min(4, paneCount))
    readonly property int rows: paneCount > 0 ? Math.ceil(paneCount / cols) : 1
    readonly property real paneMarginX: 32
    readonly property real paneMarginTop: 88
    readonly property real paneMarginBottom: 32
    readonly property real paneSpacing: 18
    readonly property real paneW: cols > 0
        ? (root.width - 2 * paneMarginX - (cols - 1) * paneSpacing) / cols : 0
    readonly property real paneH: rows > 0
        ? (root.height - paneMarginTop - paneMarginBottom - (rows - 1) * paneSpacing) / rows : 0

    Rectangle { anchors.fill: parent; color: "#0B0D12" }

    Text {
        x: 20; y: 16; color: "#8993A6"; font.pixelSize: 12
        text: "measurement_b -- living ground FULL + frost bake  panes=" + root.paneCount
              + "  rebakeHz=" + root.rebakeHz + "  bakes=" + root.bakeCount
    }

    // ---- layer 0: the animated ambient ground (position only, never alpha) --
    Item {
        id: groundRoot
        anchors.fill: parent

        Rectangle {
            id: washA
            width: root.width * 0.55; height: width
            radius: width / 2
            x: root.width * 0.05; y: root.height * 0.10
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#4A2F6FEA" }
                GradientStop { position: 1.0; color: "#00202020" }
            }
            SequentialAnimation on x {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.width * 0.30; duration: 9000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * 0.02; duration: 9000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on y {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.height * 0.28; duration: 7000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.height * 0.06; duration: 7000; easing.type: Easing.InOutSine }
            }
        }
        Rectangle {
            id: washB
            width: root.width * 0.5; height: width
            radius: width / 2
            x: root.width * 0.40; y: root.height * 0.35
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#3800C2CB" }
                GradientStop { position: 1.0; color: "#00202020" }
            }
            SequentialAnimation on x {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.width * 0.05; duration: 11000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * 0.42; duration: 11000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on y {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.height * 0.55; duration: 8000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.height * 0.20; duration: 8000; easing.type: Easing.InOutSine }
            }
        }
    }

    // ---- the bake: ONE blur, cached, re-rendered only on scheduleUpdate() ---
    MultiEffect {
        id: frostTexture
        anchors.fill: groundRoot
        source: groundRoot
        visible: false
        blurEnabled: true
        blur: 1.0
        blurMax: __BLUR_MAX_PX__
        blurMultiplier: 1.0
        autoPaddingEnabled: false
        layer.enabled: true
        layer.live: false
    }

    Timer {
        id: bakeTimer
        interval: Math.max(1, Math.round(1000 / Math.max(0.001, root.rebakeHz)))
        running: root.groundOn && root.paneCount > 0
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            root.bakeCount += 1
            frostTexture.layer.scheduleUpdate()
            for (var i = 0; i < paneRepeater.count; i++) {
                var p = paneRepeater.itemAt(i)
                if (p) p.requestUpdate()
            }
        }
    }

    // ---- N glass panes, each a cheap crop-sampler of the baked texture ------
    Repeater {
        id: paneRepeater
        model: root.paneCount
        delegate: Item {
            id: pane
            required property int index
            x: root.paneMarginX + (index % root.cols) * (root.paneW + root.paneSpacing)
            y: root.paneMarginTop + Math.floor(index / root.cols) * (root.paneH + root.paneSpacing)
            width: root.paneW
            height: root.paneH
            clip: true

            function requestUpdate() { ses.scheduleUpdate() }

            Rectangle { anchors.fill: parent; color: "#14171C" }
            ShaderEffectSource {
                id: ses
                anchors.fill: parent
                sourceItem: frostTexture
                sourceRect: Qt.rect(pane.x, pane.y, pane.width, pane.height)
                live: false
                hideSource: false
            }
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.color: "#33FFFFFF"
                border.width: 1
                radius: 10
            }
            Text {
                anchors.centerIn: parent
                text: "pane " + pane.index
                color: "#AAB3C2"
                font.pixelSize: 11
            }
        }
    }
}
""".replace("__BLUR_MAX_PX__", str(BLUR_MAX_PX))


def _make_qml_view(panes: int, rebake_hz: float, x: int, y: int, w: int, h: int):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQuick import QQuickView

    tmp = Path(tempfile.gettempdir()) / "tct_measurement_b_frost.qml"
    tmp.write_text(_QML, encoding="utf-8")
    view = QQuickView()
    view.setTitle(f"measurement_b -- frost scene panes={panes} rebakeHz={rebake_hz}")
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.setColor(QColor("#0B0D12"))
    view.setGeometry(x, y, w, h)
    view.setInitialProperties({"paneCount": panes, "rebakeHz": float(rebake_hz), "groundOn": True})
    view.setSource(QUrl.fromLocalFile(str(tmp)))
    return view


def validate_qml() -> list[str]:
    """Parse-only QML validity check (no GL context needed). Returns error
    strings, empty when the embedded frost scene compiles cleanly."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    tmp = Path(tempfile.gettempdir()) / "tct_measurement_b_frost.qml"
    tmp.write_text(_QML, encoding="utf-8")
    engine = QQmlEngine()
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(tmp)))
    errs = [str(e) for e in comp.errors()]
    return errs


# --------------------------------------------------------------------------- #
# One cell (baseline or loaded) -- reuses the shared DeviceManager/controller  #
# --------------------------------------------------------------------------- #

def _scan_config(seconds: float, warmup_s: float, settle_s: float):
    """A grid sized to run *well past* warmup + window so cadence never runs
    out of points mid-measurement."""
    from controller.scan_controller import ScanConfig
    # Generous grid: 81 x 81 = 6561 points. At sim-scan pace (a few tens of ms
    # per point) that is minutes of points -- far more than any window needs.
    return ScanConfig(
        x_start_mm=-2.0, x_stop_mm=2.0, x_step_mm=0.05,
        y_start_mm=-2.0, y_stop_mm=2.0, y_step_mm=0.05,
        z_mm=0.0, n_averages=1, settle_time_s=settle_s,
    )


def measure_cell(dev, sm, controller, *, loaded: bool, seconds: float,
                 warmup_s: float, settle_s: float, panes: int, rebake_hz: float,
                 render_qml: bool) -> dict:
    """Run one measurement cell on the shared sim scan.

    * builds the island (+ frost view when ``render_qml``);
    * starts the scan, lets it reach steady state (``warmup_s``), windows the
      telemetry for ``seconds``, then aborts + waits for the worker to finish;
    * returns the cell telemetry dict.
    """
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry() if screen else None
    if avail is not None:
        qw, qh = min(900, max(320, avail.width() - 540)), min(600, max(240, avail.height() - 140))
        qx, qy = avail.x() + 40, avail.y() + 60
        ix, iy = qx + qw + 24, qy
    else:
        qw, qh, qx, qy, ix, iy = 800, 560, 60, 60, 900, 60

    tag = "loaded" if loaded else "baseline"
    entry: dict = {"cell": tag, "loaded": loaded, "errors": []}

    island = Island(ix, iy)
    island.show()
    probe = CadenceProbe(island)

    view = None
    if loaded and render_qml:
        view = _make_qml_view(panes, rebake_hz, qx, qy, qw, qh)
        entry["qml_errors"] = [str(e) for e in view.errors()]
        if entry["qml_errors"]:
            entry["errors"].append("QML load errors: " + "; ".join(entry["qml_errors"]))
    frames = {"n": 0}
    if view is not None:
        view.frameSwapped.connect(lambda: frames.__setitem__("n", frames["n"] + 1))
        view.show()

    # wire scan callbacks
    finished = threading.Event()
    controller.on_point_done = probe.on_point
    controller.on_finished = finished.set
    controller.on_error = lambda msg: entry["errors"].append(f"scan on_error: {msg}")

    # start the sim scan
    cfg = _scan_config(seconds, warmup_s, settle_s)
    _reset_to_ready(sm)
    finished.clear()
    controller.start(cfg)

    # warmup: let shaders compile, the bake spin up, and the scan reach a steady
    # per-point pace -- NOT measured.
    _settle(int(warmup_s * 1000))

    # window the telemetry
    root = view.rootObject() if view is not None else None
    if root is not None:
        root.setProperty("bakeCount", 0)
    probe.start_window()
    island.start()
    frames["n"] = 0
    cpu0, t0 = _proc_cpu_seconds(), time.perf_counter()
    _settle(int(seconds * 1000))
    cpu1, t1 = _proc_cpu_seconds(), time.perf_counter()
    island.stop()
    probe.stop_window()

    wall = t1 - t0
    entry["wall_s"] = round(wall, 3)
    entry["qml_fps"] = round(frames["n"] / wall, 2) if (view is not None and wall > 0) else None
    entry["process_cpu_pct_of_one_core"] = (
        round((cpu1 - cpu0) / wall * 100.0, 2) if wall > 0 else float("nan"))
    entry["island_effective_hz"] = round(island.effective_hz(), 2)
    entry["island_ticks"] = len(island.tick_times)
    entry["daq"] = probe.stats()
    entry["bake_count_observed"] = int(root.property("bakeCount")) if root is not None else None
    if root is not None:
        entry["bake_count_expected_approx"] = round(seconds * rebake_hz)

    # stop the scan and wait for the worker to unwind (fail-safe teardown runs)
    controller.abort(reason="measurement_b cell end")
    if not finished.wait(timeout=15.0):
        entry["errors"].append("scan worker did not finish within 15 s of abort")
    _settle(200)

    # HDF5 provenance -- confirm a file was written into the TEMP data dir
    try:
        runs = sorted(dev.data_dir.glob("run_*/waveforms.h5"))
        entry["hdf5_files"] = [str(p) for p in runs]
        entry["hdf5_last_bytes"] = runs[-1].stat().st_size if runs else 0
    except Exception as exc:  # noqa: BLE001
        entry["errors"].append(f"hdf5 provenance check failed: {exc}")

    island.close()
    if view is not None:
        view.close()
    _settle(150)

    # detach callbacks so the next cell starts clean
    controller.on_point_done = None
    controller.on_finished = None
    controller.on_error = None
    return entry


# --------------------------------------------------------------------------- #
# Verdict                                                                       #
# --------------------------------------------------------------------------- #

def compute_verdict(baseline: dict, loaded: dict) -> dict:
    bl_daq = baseline.get("daq", {})
    ld_daq = loaded.get("daq", {})

    bl_hz = baseline.get("island_effective_hz") or 0.0
    ld_hz = loaded.get("island_effective_hz") or 0.0
    p1_floor = ld_hz >= ISLAND_HZ_FLOOR
    p1_retain = ld_hz >= bl_hz * ISLAND_RETENTION if bl_hz > 0 else False
    p1 = p1_floor and p1_retain

    bl_rate = bl_daq.get("rate_hz") or 0.0
    ld_rate = ld_daq.get("rate_hz") or 0.0
    bl_cv = bl_daq.get("cv")
    ld_cv = ld_daq.get("cv")
    p2_rate = ld_rate >= bl_rate * DAQ_RATE_RETENTION if bl_rate > 0 else False
    cv_ceiling = max((bl_cv or 0.0) * 1.5, DAQ_CV_ABS_MAX)
    p2_jitter = (ld_cv is not None) and (ld_cv <= cv_ceiling)
    p2 = p2_rate and p2_jitter

    ld_fps = loaded.get("qml_fps")
    p3 = (ld_fps is not None) and (ld_fps >= QML_FPS_FLOOR)

    return {
        "p1_plot_holds_rate": {
            "loaded_island_hz": ld_hz, "baseline_island_hz": bl_hz,
            "floor": ISLAND_HZ_FLOOR, "retention_frac": ISLAND_RETENTION,
            "retention_target": round(bl_hz * ISLAND_RETENTION, 2),
            "pass": bool(p1),
        },
        "p2_daq_no_jitter": {
            "loaded_rate_hz": ld_rate, "baseline_rate_hz": bl_rate,
            "rate_retention_frac": DAQ_RATE_RETENTION,
            "rate_target": round(bl_rate * DAQ_RATE_RETENTION, 3),
            "loaded_cv": ld_cv, "baseline_cv": bl_cv, "cv_ceiling": round(cv_ceiling, 4),
            "pass": bool(p2),
        },
        "p3_frost_renders": {
            "loaded_qml_fps": ld_fps, "floor": QML_FPS_FLOOR, "pass": bool(p3),
        },
        "overall_pass": bool(p1 and p2 and p3),
    }


def _print_summary(report: dict) -> None:
    print("\n" + "=" * 100)
    print(f"MEASUREMENT B -- acquisition-headroom spike  build={report.get('windows_build')} "
          f"qt={report.get('qt_platform')} pyside={report.get('pyside')} "
          f"panes={report.get('panes')} rebakeHz={report.get('rebake_hz')}")
    print("=" * 100)
    header = (f"{'cell':10s} {'cpu%':>7s} {'qml_fps':>8s} {'island_hz':>10s} "
              f"{'daq_pts':>8s} {'daq_hz':>8s} {'daq_cv':>7s} {'bakes':>7s}")
    print(header)
    print("-" * len(header))
    for tag in ("baseline", "loaded"):
        c = report["cells"].get(tag, {})
        daq = c.get("daq", {})
        print(f"{tag:10s} {str(c.get('process_cpu_pct_of_one_core')):>7s} "
              f"{str(c.get('qml_fps')):>8s} {str(c.get('island_effective_hz')):>10s} "
              f"{str(daq.get('points')):>8s} {str(daq.get('rate_hz')):>8s} "
              f"{str(daq.get('cv')):>7s} {str(c.get('bake_count_observed')):>7s}")
    v = report.get("verdict", {})
    if v:
        p1, p2, p3 = v["p1_plot_holds_rate"], v["p2_daq_no_jitter"], v["p3_frost_renders"]
        print("\nVERDICT")
        print(f"  (P1) plot holds rate: island {p1['loaded_island_hz']} Hz >= floor "
              f"{p1['floor']} AND >= {p1['retention_target']} (0.90 x baseline "
              f"{p1['baseline_island_hz']}) -> {'PASS' if p1['pass'] else 'FAIL'}")
        print(f"  (P2) DAQ no jitter: rate {p2['loaded_rate_hz']} Hz >= "
              f"{p2['rate_target']} (0.80 x baseline {p2['baseline_rate_hz']}) AND "
              f"cv {p2['loaded_cv']} <= {p2['cv_ceiling']} -> "
              f"{'PASS' if p2['pass'] else 'FAIL'}")
        print(f"  (P3) frost renders: qml_fps {p3['loaded_qml_fps']} >= {p3['floor']} -> "
              f"{'PASS' if p3['pass'] else 'FAIL'}")
        print(f"\n  OVERALL: {'PASS' if v['overall_pass'] else 'FAIL'}  "
              f"(FAIL fallback per SS7: run-active global calm, bake -> 0 Hz app-wide)")
    print("=" * 100)


def write_artifacts(report: dict, out_dir: Path) -> None:
    (out_dir / "spike_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Watchdog (out-of-process hard kill -- copied from scripts/rhi_gl_probe.py)   #
# --------------------------------------------------------------------------- #

def _spawn_hard_watchdog(pid: int, seconds: float) -> subprocess.Popen:
    """A watchdog in its OWN process/interpreter/GIL. If this process wedges
    inside a blocking Qt/driver call, an in-process timer can never fire (the
    GIL is never released); ``os.kill(pid, 3)`` from a separate process calls
    TerminateProcess regardless and exits us with code 3."""
    code = ("import os, time\n"
            f"time.sleep({seconds})\n"
            f"try:\n    os.kill({pid}, 3)\nexcept Exception:\n    pass\n")
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen([sys.executable, "-c", code], creationflags=creationflags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- #
# Bootstrap                                                                     #
# --------------------------------------------------------------------------- #

def _bootstrap_app(smoke: bool):
    from PySide6.QtGui import QGuiApplication  # noqa: F401
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtWidgets import QApplication

    if not smoke:
        # Real windowed run -> pin OpenGL RHI (same as the measurement-A spike
        # and the U0 gate probe). Under offscreen we leave Qt's default so the
        # smoke never demands a GL context that isn't there.
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    return app


def _guard_selftest(dev) -> tuple[bool, str]:
    """Prove the sim-only guard TRIPS on a non-sim backend, without ever
    constructing a real driver: flip one live sim device's ``.simulation`` flag
    to False in memory and confirm ``assert_simulated`` refuses."""
    victim = dev.motor
    original = getattr(victim, "simulation", None)
    try:
        victim.simulation = False
        try:
            assert_simulated(dev)
            return False, "guard did NOT trip on a non-sim device (FAIL)"
        except SimOnlyViolation as exc:
            return True, f"guard tripped as required: {exc}"
    finally:
        victim.simulation = original


def run_smoke(args) -> int:
    """Headless mechanics check -- NO fps assertions. Verifies: sim guard passes;
    sim guard trips on a forced non-sim device; the sim scan starts and produces
    points; HDF5 is written to a TEMP path; the island + cadence telemetry emit;
    the QML frost scene parses; clean exit."""
    app = _bootstrap_app(smoke=True)  # noqa: F841 -- keep QApplication alive
    from PySide6.QtGui import QGuiApplication
    import PySide6

    print("MEASUREMENT B -- SMOKE (offscreen mechanics; no fps assertions)")
    print(f"  qt_platform={QGuiApplication.instance().platformName()!r} pyside={PySide6.__version__}")

    tmp = Path(tempfile.mkdtemp(prefix="measurement_b_smoke_"))
    data_dir = tmp / "scan_runs"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. build + guard the sim DeviceManager
    try:
        dev = build_sim_device_manager(data_dir)
    except SimOnlyViolation as exc:
        print(f"  [1] sim guard: UNEXPECTED trip on the forced-sim config: {exc}")
        return EXIT_GUARD
    print("  [1] sim guard PASSED on forced-sim config "
          f"(motor={type(dev.motor).__name__}, bias_driver={type(dev._bias_driver).__name__})")

    # 2. guard must TRIP on a non-sim device
    ok, msg = _guard_selftest(dev)
    print(f"  [2] guard-trip selftest: {'OK' if ok else 'FAIL'} -- {msg}")
    if not ok:
        return EXIT_ERROR

    # 3. QML parse validity
    qml_errs = validate_qml()
    print(f"  [3] QML frost scene parse: {'OK (no errors)' if not qml_errs else 'ERRORS: ' + '; '.join(qml_errs)}")
    if qml_errs:
        return EXIT_ERROR

    # 4. connect (sim, safe) + walk state machine to READY
    from controller.state_machine import StateMachine
    from controller.scan_controller import ScanController
    results = dev.connect_all()
    bad = {k: v for k, v in results.items() if v != "ok"}
    print(f"  [4] connect_all (sim): {'all ok' if not bad else 'non-ok: ' + str(bad)}")
    home_sim_stage(dev)
    sm = StateMachine()
    _walk_to_ready(sm)
    controller = ScanController(dev, sm)
    print(f"      state machine -> {sm.state.name}")

    # 5. run ONE short cell (scan + island, no QML render offscreen)
    cell = measure_cell(dev, sm, controller, loaded=False,
                        seconds=max(1.5, args.seconds if args.seconds < 5 else 2.0),
                        warmup_s=0.6, settle_s=0.005,
                        panes=args.panes, rebake_hz=args.rebake_hz, render_qml=False)
    daq = cell.get("daq", {})
    print(f"  [5] sim scan cell: points={daq.get('points')} daq_rate={daq.get('rate_hz')} Hz "
          f"island_hz={cell.get('island_effective_hz')} island_ticks={cell.get('island_ticks')}")
    print(f"      HDF5 written: {len(cell.get('hdf5_files', []))} file(s), "
          f"last={cell.get('hdf5_last_bytes')} bytes under {data_dir}")
    if cell.get("errors"):
        print(f"      cell errors: {cell['errors']}")

    # 6. verdict on mechanics
    mech_ok = (
        not cell.get("errors")
        and (daq.get("points") or 0) >= 1
        and (cell.get("island_ticks") or 0) >= 1
        and len(cell.get("hdf5_files", [])) >= 1
    )
    dev.disconnect_all()
    print(f"\n  SMOKE {'PASS' if mech_ok else 'FAIL'} -- "
          f"{'guard + sim scan + HDF5 + telemetry + QML-parse all exercised' if mech_ok else 'a mechanic did not fire'}")
    # scratch cleanup is best-effort; leave the dir for inspection on failure
    return EXIT_PASS if mech_ok else EXIT_FAIL


def run_measurement(args) -> int:
    """The real windowed measurement (operator only)."""
    app = _bootstrap_app(smoke=False)
    from PySide6.QtGui import QGuiApplication
    import PySide6

    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return EXIT_GUARD

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _REPO_ROOT / "artifacts_claude" / f"measurement_b_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = out_dir / "scan_runs"
    data_dir.mkdir(parents=True, exist_ok=True)

    # sim DeviceManager + guard
    try:
        dev = build_sim_device_manager(data_dir)
    except SimOnlyViolation as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_GUARD

    dev.connect_all()
    home_sim_stage(dev)
    from controller.state_machine import StateMachine
    from controller.scan_controller import ScanController
    sm = StateMachine()
    _walk_to_ready(sm)
    controller = ScanController(dev, sm)

    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry() if screen else None
    report: dict = {
        "spike": "measurement_b_acquisition_headroom",
        "utc": ts,
        "windows_build": (sys.getwindowsversion().build      # type: ignore[attr-defined]
                          if hasattr(sys, "getwindowsversion") else None),
        "qt_platform": app.platformName(),
        "pyside": PySide6.__version__,
        "panes": args.panes,
        "rebake_hz": args.rebake_hz,
        "params": {"seconds": args.seconds, "warmup_s": args.warmup,
                   "settle_s": args.settle, "island_nominal_hz": ISLAND_NOMINAL_HZ},
        "thresholds": {"island_hz_floor": ISLAND_HZ_FLOOR, "qml_fps_floor": QML_FPS_FLOOR,
                       "island_retention": ISLAND_RETENTION,
                       "daq_rate_retention": DAQ_RATE_RETENTION, "daq_cv_abs_max": DAQ_CV_ABS_MAX},
        "screen": {"dip": [avail.width(), avail.height()] if avail else None,
                   "dpr": screen.devicePixelRatio() if screen else None},
        "out_dir": str(out_dir),
        "cells": {},
    }

    print(f"\nMEASUREMENT B -- {args.seconds:.0f}s window per cell "
          f"(baseline: scan+island; loaded: + frost full @ {args.rebake_hz} Hz, {args.panes} panes)")
    print("--- baseline: sim scan + 30 Hz island, no frost scene ---")
    sys.stdout.flush()
    report["cells"]["baseline"] = measure_cell(
        dev, sm, controller, loaded=False, seconds=args.seconds, warmup_s=args.warmup,
        settle_s=args.settle, panes=args.panes, rebake_hz=args.rebake_hz, render_qml=False)

    print("--- loaded: sim scan + 30 Hz island + living ground FULL + frost bake ---")
    sys.stdout.flush()
    report["cells"]["loaded"] = measure_cell(
        dev, sm, controller, loaded=True, seconds=args.seconds, warmup_s=args.warmup,
        settle_s=args.settle, panes=args.panes, rebake_hz=args.rebake_hz, render_qml=True)

    report["verdict"] = compute_verdict(report["cells"]["baseline"], report["cells"]["loaded"])
    report["overall_pass"] = report["verdict"]["overall_pass"]

    dev.disconnect_all()
    write_artifacts(report, out_dir)
    _print_summary(report)
    print(f"\nartifacts: {out_dir}\n")
    return EXIT_PASS if report["overall_pass"] else EXIT_FAIL


def run_hold(args) -> int:
    """Eyeball mode: leave the loaded scene + live sim scan on screen for N s."""
    app = _bootstrap_app(smoke=False)
    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return EXIT_GUARD
    tmp = Path(tempfile.mkdtemp(prefix="measurement_b_hold_"))
    data_dir = tmp / "scan_runs"
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        dev = build_sim_device_manager(data_dir)
    except SimOnlyViolation as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_GUARD
    dev.connect_all()
    home_sim_stage(dev)
    from controller.state_machine import StateMachine
    from controller.scan_controller import ScanController
    from PySide6.QtCore import QTimer
    sm = StateMachine()
    _walk_to_ready(sm)
    controller = ScanController(dev, sm)

    island = Island(980, 80)
    island.show()
    probe = CadenceProbe(island)
    controller.on_point_done = probe.on_point
    view = _make_qml_view(args.panes, args.rebake_hz, 80, 80, 880, 600)
    errs = [str(e) for e in view.errors()]
    if errs:
        print("QML ERRORS:", errs, file=sys.stderr)
    view.show()
    island.start()
    _reset_to_ready(sm)
    controller.start(_scan_config(args.hold, 1.0, args.settle))
    print(f"holding loaded scene + live sim scan for {args.hold}s -- watch the "
          "island plot and the panes for stalls.")
    sys.stdout.flush()
    QTimer.singleShot(args.hold * 1000, app.quit)
    app.exec()
    controller.abort()
    island.close()
    view.close()
    dev.disconnect_all()
    return EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lantern measurement B -- acquisition-headroom spike.")
    ap.add_argument("--smoke", action="store_true",
                    help="headless mechanics check (offscreen; no fps assertions)")
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help="window per cell")
    ap.add_argument("--warmup", type=float, default=DEFAULT_WARMUP_S)
    ap.add_argument("--settle", type=float, default=0.02, help="scan settle_time_s per point")
    ap.add_argument("--panes", type=int, default=DEFAULT_PANES)
    ap.add_argument("--rebake-hz", type=float, default=DEFAULT_REBAKE_HZ)
    ap.add_argument("--hold", type=int, default=0, help="eyeball: leave loaded scene on screen N s")
    ap.add_argument("--watchdog", type=float, default=0.0,
                    help="hard out-of-process kill after N s (0 = auto from window sizes)")
    args = ap.parse_args(argv)

    # Out-of-process hard watchdog so this can never hang a gate.
    if args.hold > 0:
        wd_timeout = args.hold + 60.0
    elif args.smoke:
        wd_timeout = 120.0
    else:
        wd_timeout = 2 * (args.warmup + args.seconds) + 150.0
    if args.watchdog > 0:
        wd_timeout = args.watchdog
    watchdog = _spawn_hard_watchdog(os.getpid(), wd_timeout)

    try:
        if args.smoke:
            return run_smoke(args)
        if args.hold > 0:
            return run_hold(args)
        return run_measurement(args)
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"HARNESS ERROR: {exc}", file=sys.stderr)
        traceback.print_exc()
        return EXIT_ERROR
    finally:
        try:
            watchdog.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
