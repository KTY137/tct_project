"""SPIKE — is candidate LANTERN's baked-frost mechanism actually O(1) in pane count?

THE MECHANISM UNDER TEST
-------------------------
``docs/design/qml_kit_forge/candidate_lantern.md`` SS3.2 promises: one animated
ambient ground (washes that move POSITION, never alpha), blurred by ONE single
blur pass into a baked texture at a low re-bake rate; N glass panes each sample
their own region of that baked texture (position-sampled frost). The claim is
that frost cost is O(1) in pane count -- one bake, N cheap samplers -- unlike
per-pane LIVE blur, which candidate LANTERN's own SS10 already measured at
+13pp CPU/pane on this same iGPU and rejected for exactly that reason. This
spike is the precondition SS3.2 names before U2 may build on it.

HOW THE BAKE IS BUILT (this script's implementation choice)
-------------------------------------------------------------
Three QtQuick primitives, chained by explicit manual cache control rather than
letting Qt re-render on every dirty frame:

  1. ``groundRoot`` -- a plain Item, always live, containing two soft radial
     washes whose ``x``/``y`` animate (never their alpha/opacity). This is
     rendered normally, every frame, at the back of the scene -- it IS the
     visible ambient ground, cheap on its own (a couple of gradient fills).
  2. ``frostTexture`` -- ONE ``MultiEffect`` (``blurEnabled: true``) whose
     ``source`` is ``groundRoot``, wrapped in ``layer.enabled: true`` +
     ``layer.live: false``. ``layer.live: false`` is the load-bearing QtQuick
     primitive here: it turns the item's rendered output into a cached bitmap
     that is NOT re-rendered on every dirty frame, only when
     ``frostTexture.layer.scheduleUpdate()`` is called explicitly. A QML
     ``Timer`` at the tested re-bake rate (6/12 Hz) is the only thing that
     calls it -- so the actual Gaussian blur GPU pass runs at most 6 or 12
     times a second, never at 60 fps, regardless of how many panes exist.
  3. Each of the N ``FrostPane`` delegates owns its OWN
     ``ShaderEffectSource { sourceItem: frostTexture; sourceRect: <its own
     rect>; live: false }`` -- a crop-and-blit sampler of the ALREADY-BAKED
     texture, also gated by ``live: false`` and driven by the same Timer tick
     (``scheduleUpdate()`` on every pane, once per bake). This is the "N cheap
     samplers" half of the claim: no pane runs its own blur shader, ever.

If this caching does not actually gate the GPU work on this Qt/driver
combination, the measured CPU curve will show it directly (no rebake-rate
sensitivity, and/or linear-in-panes growth even at 6 Hz) -- that failure mode
IS a valid, useful spike result, not a bug in the spike.

MATRIX
------
N panes in {2, 4, 8} x re-bake rate in {6, 12} Hz, ground animation ON
(subtle) = 6 cells, plus a BASELINE row (ground animated, ZERO panes, no
bake at all -- the ambient-only reference the pane cells are measured
against).

Per cell, three wall-clock, independent signals over a >=10 s steady-state
window:
  * process CPU % of one core (Win32 ``GetProcessTimes`` kernel+user delta /
    wall time -- this venv has no ``psutil`` and, per this repo's own spike
    precedent -- see ``qml_multieffect_glass_spike.py``'s ``_proc_cpu_seconds``
    docstring -- "a spike may not install one"; GetProcessTimes reports the
    same OS-level number psutil.Process().cpu_percent() would compute)
  * QML scene fps (``QQuickWindow.frameSwapped`` counter over the window)
  * the pyqtgraph island's EFFECTIVE update rate -- not its nominal 30 Hz
    QTimer interval, but the actual wall-clock tick spacing achieved while
    the frost machinery is under load (the airspace-coexistence question:
    does baking steal cycles from an unrelated live plot next to it?)

The island is a REAL ``pyqtgraph.PlotWidget`` in its own top-level QWidget
window (not embedded in the QML scene), driven by a 30 Hz QTimer, in the SAME
process and SAME QApplication event loop as the QML window by default -- that
IS the coexistence case (one process, one GPU, one event loop, exactly how the
real app runs both surfaces side by side). If this single-process combination
proves unstable (crashes / hangs in the stability loop), the matrix falls back
to two simultaneous processes on the same box and the report says so plainly.

STABILITY (M4, same protocol as ``qml_multieffect_glass_spike.py``'s M4)
--------------------------------------------------------------------------
The busiest cell (8 panes @ 12 Hz, both QML + island live) is relaunched as
its OWN process >=20 times; a Windows access violation exits 0xC0000005 and
is counted. One process per run, not a style choice -- it is the only way to
catch a scene-graph segfault from the outside (this codebase's own prior
GL-island spike found a ~50% Python-scene-graph-item crash rate; MultiEffect
is a built-in C++ type with no Python scene-graph code, but the bake's layer
caching under repeated ``scheduleUpdate()`` churn is new enough to be worth
checking cold).

VERDICT CRITERIA (printed PASS/FAIL, each independently)
------------------------------------------------------------
  (a) frost CPU slope < 2 pp per pane, at EACH re-bake rate (the O(1) claim)
  (b) QML scene >= 55 fps in every cell (incl. baseline)
  (c) island holds >= 28 Hz in every cell (incl. baseline)
  (d) 0 crashes across the >=20 stability launches

RUN (real desktop session only -- refuses under offscreen/minimal)
-----------------------------------------------------------------
::

    cd TCT_app
    .venv/Scripts/python.exe scripts/spikes/lantern_frost_bake_spike.py            # full matrix + stability(20)
    .venv/Scripts/python.exe scripts/spikes/lantern_frost_bake_spike.py --seconds 3 --warmup 1 --stability-n 5   # fast smoke
    .venv/Scripts/python.exe scripts/spikes/lantern_frost_bake_spike.py --hold 20 --panes 8 --rebake-hz 12       # eyeball

NOT app code. NOT imported by the app. NOT part of the test suite. No hardware,
no DeviceManager, no QSettings. Standalone: does not import ``gui/``,
``devices/``, or ``controller/``. Single host = Intel UHD iGPU (deliberately
the weakest realistic GPU on the lab fleet -- worst case is the point).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

_SPIKES = Path(__file__).resolve().parent
_SCRIPTS = _SPIKES.parent
_TCT_APP = _SCRIPTS.parent
_REPO_ROOT = _TCT_APP.parent

PANE_COUNTS = (2, 4, 8)
REBAKE_RATES_HZ = (6, 12)
DEFAULT_SECONDS = 10.0
DEFAULT_WARMUP_S = 2.5
ISLAND_NOMINAL_HZ = 30
BLUR_MAX_PX = 40          # matches candidate_lantern.md SS6 blurPane token

CRIT_CPU_SLOPE_PP_PER_PANE = 2.0
CRIT_QML_FPS_FLOOR = 55.0
CRIT_ISLAND_HZ_FLOOR = 28.0

# A Windows access violation surfaces as 0xC0000005 (two equivalent encodings
# depending on how Python/ctypes reports the signed 32-bit exit code).
_SEGFAULT_CODES = (-1073741819, 3221225477)


# --------------------------------------------------------------------------- #
# Process CPU (no psutil in this venv -- see module docstring)                 #
# --------------------------------------------------------------------------- #

class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


_K32 = ctypes.windll.kernel32
_K32.GetCurrentProcess.restype = wintypes.HANDLE
_K32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FILETIME),
                                 ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
                                 ctypes.POINTER(_FILETIME)]
_K32.GetProcessTimes.restype = wintypes.BOOL


def _proc_cpu_seconds() -> float:
    """Kernel+user CPU seconds burned by THIS process (GetProcessTimes).

    argtypes/restype above are load-bearing: without them ctypes marshals the
    64-bit pseudo-handle through a 32-bit ``c_int`` and this silently returns
    ``nan`` (documented failure mode in the sibling spike this is copied from).
    """
    creation, exit_t, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
    ok = _K32.GetProcessTimes(_K32.GetCurrentProcess(), ctypes.byref(creation),
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
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    platform = app.platformName() if app else ""
    if platform in ("offscreen", "minimal"):
        return f"refusing to run under QT_QPA_PLATFORM={platform!r} -- this spike measures real GPU/compositor timing"
    return None


# --------------------------------------------------------------------------- #
# The QML scene -- ground + one bake + N samplers                              #
# --------------------------------------------------------------------------- #

_QML = """
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property int paneCount: 4
    property real rebakeHz: 12
    property bool groundOn: true
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
        text: "lantern_frost_bake_spike -- panes=" + root.paneCount
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


# --------------------------------------------------------------------------- #
# The pyqtgraph island -- a REAL PlotWidget, own top-level window, 30 Hz        #
# --------------------------------------------------------------------------- #

class Island:
    """Owns a top-level QWidget hosting a pyqtgraph PlotWidget updated at a
    nominal 30 Hz. ``tick_times`` records wall-clock timestamps of every
    actual update -- the effective rate is derived from THESE, not from the
    QTimer's nominal interval, per the two-independent-probes rule."""

    def __init__(self, x: int, y: int) -> None:
        import numpy as np
        import pyqtgraph as pg
        from PySide6.QtCore import QTimer, Qt
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        self._np = np
        self.widget = QWidget(None)
        self.widget.setWindowTitle("lantern_frost_bake_spike -- pyqtgraph island (30 Hz nominal)")
        self.widget.setGeometry(x, y, 460, 300)
        layout = QVBoxLayout(self.widget)
        self.plot = pg.PlotWidget()
        self.plot.setYRange(-1.3, 1.3)
        self.plot.setLabel("bottom", "sample")
        self.curve = self.plot.plot(pen=pg.mkPen("#5FD3C4", width=2))
        layout.addWidget(self.plot)

        self._n = 400
        self._buf = np.zeros(self._n)
        self._t = 0.0
        self.tick_times: list[float] = []

        self._timer = QTimer(self.widget)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

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
        np = self._np
        self._t += 0.09
        self._buf = np.roll(self._buf, -1)
        self._buf[-1] = math.sin(self._t) + 0.04 * np.random.randn()
        self.curve.setData(self._buf)
        self.tick_times.append(time.perf_counter())

    def effective_hz(self) -> float:
        tt = self.tick_times
        if len(tt) < 2:
            return 0.0
        return (len(tt) - 1) / (tt[-1] - tt[0])


# --------------------------------------------------------------------------- #
# One cell, measured in its own process                                        #
# --------------------------------------------------------------------------- #

def _make_qml_view(panes: int, rebake_hz: float, x: int, y: int, w: int, h: int):
    import tempfile
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQuick import QQuickView

    tmp = Path(tempfile.gettempdir()) / "tct_lantern_frost_bake_spike.qml"
    tmp.write_text(_QML, encoding="utf-8")

    view = QQuickView()
    view.setTitle(f"lantern_frost_bake_spike -- panes={panes} rebakeHz={rebake_hz}")
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.setColor(QColor("#0B0D12"))
    view.setGeometry(x, y, w, h)
    view.setInitialProperties({"paneCount": panes, "rebakeHz": float(rebake_hz), "groundOn": True})
    view.setSource(QUrl.fromLocalFile(str(tmp)))
    return view


def measure_cell(panes: int, rebake_hz: float, seconds: float, warmup_s: float,
                 with_island: bool = True) -> dict:
    """Build the QML window (+ optionally the island), measure steady state,
    tear down. Runs inside a process that already has a QApplication."""
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    qw, qh = min(940, avail.width() - 520), min(620, avail.height() - 120)
    qx, qy = avail.x() + 40, avail.y() + 60
    ix, iy = qx + qw + 24, qy

    entry: dict = {"panes": panes, "rebake_hz": rebake_hz, "errors": []}

    view = _make_qml_view(panes, rebake_hz, qx, qy, qw, qh)
    entry["qml_errors"] = [str(e) for e in view.errors()]
    if entry["qml_errors"]:
        entry["errors"].append("QML load errors: " + "; ".join(entry["qml_errors"]))

    frames = {"n": 0}
    view.frameSwapped.connect(lambda: frames.__setitem__("n", frames["n"] + 1))
    view.show()

    island = None
    if with_island:
        island = Island(ix, iy)
        island.show()

    _settle(int(warmup_s * 1000))   # shader compile + scene graph spin-up, NOT measured

    root = view.rootObject()
    if root is not None:
        root.setProperty("bakeCount", 0)   # window the bake counter to the measured span too

    if island is not None:
        island.start()
    frames["n"] = 0
    cpu0, t0 = _proc_cpu_seconds(), time.perf_counter()
    _settle(int(seconds * 1000))
    cpu1, t1 = _proc_cpu_seconds(), time.perf_counter()
    if island is not None:
        island.stop()

    wall = t1 - t0
    entry["wall_s"] = round(wall, 3)
    entry["qml_fps"] = round(frames["n"] / wall, 2) if wall > 0 else 0.0
    entry["process_cpu_pct_of_one_core"] = round((cpu1 - cpu0) / wall * 100.0, 2) if wall > 0 else float("nan")
    entry["island_effective_hz"] = round(island.effective_hz(), 2) if island is not None else None
    entry["island_ticks"] = len(island.tick_times) if island is not None else None

    entry["bake_count_observed"] = int(root.property("bakeCount")) if root is not None else None
    expected_bakes = round(seconds * rebake_hz) if panes > 0 else 0
    entry["bake_count_expected_approx"] = expected_bakes

    view.close()
    if island is not None:
        island.close()
    _settle(200)
    return entry


def stability_probe(panes: int, rebake_hz: float, seconds: float = 2.0,
                    warmup_s: float = 1.2, with_island: bool = True) -> int:
    """One short lifecycle for the M4 crash-count loop: build, run briefly with
    motion + baking + (optionally) the island live, grab the bake counter as a
    sanity check, exit 0. A whole process per iteration -- the only way an
    access-violation crash can be counted from the outside."""
    import os
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qml.connections=false")
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtWidgets import QApplication

    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 4
    try:
        entry = measure_cell(panes, rebake_hz, seconds, warmup_s, with_island=with_island)
    except Exception as exc:  # noqa: BLE001 -- a spike counts ANY failure as unstable
        print(f"stability_probe EXCEPTION: {exc}", file=sys.stderr)
        return 3
    if entry["qml_errors"]:
        return 3
    if entry["bake_count_observed"] in (None, 0) and panes > 0:
        print("stability_probe: bake never fired", file=sys.stderr)
        return 5
    return 0


def run_stability(n: int, panes: int, rebake_hz: float, with_island: bool) -> dict:
    codes: list[int] = []
    for _ in range(n):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()),
             "--stability-run", "--panes", str(panes), "--rebake-hz", str(rebake_hz),
             "--seconds", "2.0", "--warmup", "1.2"]
            + ([] if with_island else ["--no-island"]),
            capture_output=True, text=True, timeout=60)
        codes.append(proc.returncode)
    crashes = [c for c in codes if c != 0]
    segfaults = [c for c in codes if c in _SEGFAULT_CODES]
    return {
        "runs": n, "panes": panes, "rebake_hz": rebake_hz, "with_island": with_island,
        "exit_codes": codes, "crash_count": len(crashes), "segfault_count": len(segfaults),
        "crash_rate": f"{len(crashes)}/{n}",
    }


# --------------------------------------------------------------------------- #
# Matrix orchestration -- one process per cell                                 #
# --------------------------------------------------------------------------- #

def run_cell_subprocess(panes: int, rebake_hz: float, seconds: float, warmup_s: float,
                        out_dir: Path, with_island: bool) -> dict:
    tag = f"panes{panes}_hz{rebake_hz}" if panes > 0 else "baseline"
    out_path = out_dir / f"cell_{tag}.json"
    args = [sys.executable, str(Path(__file__).resolve()),
            "--cell-run", "--panes", str(panes), "--rebake-hz", str(rebake_hz),
            "--seconds", str(seconds), "--warmup", str(warmup_s),
            "--emit", str(out_path)]
    if not with_island:
        args.append("--no-island")
    proc = subprocess.run(args, capture_output=True, text=True, timeout=int(seconds + warmup_s + 60))
    if proc.returncode != 0 or not out_path.exists():
        return {"panes": panes, "rebake_hz": rebake_hz,
                "FAILED": f"child exit {proc.returncode}",
                "stderr_tail": proc.stderr[-800:] if proc.stderr else ""}
    return json.loads(out_path.read_text(encoding="utf-8"))


def build_matrix(seconds: float, warmup_s: float, out_dir: Path, with_island: bool) -> dict:
    cells: dict = {}
    print(f"\n--- baseline: ground on, 0 panes, no bake ({seconds:.0f}s steady state) ---")
    sys.stdout.flush()
    cells["baseline"] = run_cell_subprocess(0, 0, seconds, warmup_s, out_dir, with_island)

    for rebake_hz in REBAKE_RATES_HZ:
        for panes in PANE_COUNTS:
            tag = f"panes{panes}_hz{rebake_hz}"
            print(f"--- {tag}: {panes} panes, {rebake_hz} Hz rebake ({seconds:.0f}s steady state) ---")
            sys.stdout.flush()
            cells[tag] = run_cell_subprocess(panes, rebake_hz, seconds, warmup_s, out_dir, with_island)
    return cells


def _linfit_slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of ys vs xs (simple 1-D linear regression)."""
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else float("nan")


def compute_verdict(cells: dict) -> dict:
    verdict: dict = {}

    # (a) CPU slope per pane, at each re-bake rate
    slope_by_rate: dict = {}
    for rebake_hz in REBAKE_RATES_HZ:
        xs, ys = [], []
        for panes in PANE_COUNTS:
            tag = f"panes{panes}_hz{rebake_hz}"
            c = cells.get(tag, {})
            if "FAILED" in c:
                continue
            xs.append(float(panes))
            ys.append(c["process_cpu_pct_of_one_core"])
        slope = _linfit_slope(xs, ys) if len(xs) >= 2 else float("nan")
        slope_by_rate[str(rebake_hz)] = round(slope, 3) if slope == slope else None
    slopes_ok = [v for v in slope_by_rate.values() if v is not None]
    a_pass = bool(slopes_ok) and all(v < CRIT_CPU_SLOPE_PP_PER_PANE for v in slopes_ok)
    verdict["a_cpu_slope_per_pane_pp"] = {
        "by_rebake_hz": slope_by_rate, "threshold_pp_per_pane": CRIT_CPU_SLOPE_PP_PER_PANE,
        "pass": a_pass,
    }

    # (b) QML fps floor across every cell
    fps_by_cell = {k: c.get("qml_fps") for k, c in cells.items() if "FAILED" not in c}
    valid_fps = [v for v in fps_by_cell.values() if v is not None]
    b_pass = bool(valid_fps) and min(valid_fps) >= CRIT_QML_FPS_FLOOR
    verdict["b_qml_fps_floor"] = {
        "per_cell": fps_by_cell, "min_fps": min(valid_fps) if valid_fps else None,
        "threshold": CRIT_QML_FPS_FLOOR, "pass": b_pass,
    }

    # (c) island Hz floor across every cell
    hz_by_cell = {k: c.get("island_effective_hz") for k, c in cells.items() if "FAILED" not in c}
    valid_hz = [v for v in hz_by_cell.values() if v is not None]
    c_pass = bool(valid_hz) and min(valid_hz) >= CRIT_ISLAND_HZ_FLOOR
    verdict["c_island_hz_floor"] = {
        "per_cell": hz_by_cell, "min_hz": min(valid_hz) if valid_hz else None,
        "threshold": CRIT_ISLAND_HZ_FLOOR, "pass": c_pass,
    }

    verdict["overall_pass"] = a_pass and b_pass and c_pass  # (d) filled in by caller
    return verdict


# --------------------------------------------------------------------------- #
# Reporting                                                                    #
# --------------------------------------------------------------------------- #

def _print_table(cells: dict) -> None:
    header = (f"{'cell':16s} {'panes':>5s} {'hz':>4s} {'cpu%':>7s} {'qml_fps':>8s} "
              f"{'island_hz':>10s} {'bakes_obs':>9s} {'bakes_exp':>9s}")
    print(header)
    print("-" * len(header))
    order = ["baseline"] + [f"panes{p}_hz{r}" for r in REBAKE_RATES_HZ for p in PANE_COUNTS]
    for tag in order:
        c = cells.get(tag)
        if c is None:
            continue
        if "FAILED" in c:
            print(f"{tag:16s}  FAILED: {c['FAILED']}")
            continue
        print(f"{tag:16s} {c['panes']:>5d} {c['rebake_hz']:>4} {c['process_cpu_pct_of_one_core']:>7.2f} "
              f"{c['qml_fps']:>8.1f} {c['island_effective_hz']:>10.1f} "
              f"{str(c['bake_count_observed']):>9s} {str(c['bake_count_expected_approx']):>9s}")


def _print_summary(report: dict) -> None:
    print("\n" + "=" * 100)
    print(f"LANTERN FROST-BAKE SPIKE -- build={report['windows_build']} qt={report['qt_platform']} "
          f"pyside={report['pyside']} rhi={report['rhi_requested']} with_island={report['with_island']}")
    print("=" * 100)
    _print_table(report["cells"])
    v = report["verdict"]
    print("\nVERDICT")
    a = v["a_cpu_slope_per_pane_pp"]
    print(f"  (a) CPU slope < {a['threshold_pp_per_pane']} pp/pane: {a['by_rebake_hz']} -> "
          f"{'PASS' if a['pass'] else 'FAIL'}")
    b = v["b_qml_fps_floor"]
    print(f"  (b) QML fps >= {b['threshold']} in every cell: min={b['min_fps']} -> "
          f"{'PASS' if b['pass'] else 'FAIL'}")
    c = v["c_island_hz_floor"]
    print(f"  (c) island Hz >= {c['threshold']} in every cell: min={c['min_hz']} -> "
          f"{'PASS' if c['pass'] else 'FAIL'}")
    d = report.get("M4_stability", {})
    if d:
        print(f"  (d) 0 crashes in {d['runs']} stability launches: crashes={d['crash_count']} -> "
              f"{'PASS' if d['crash_count'] == 0 else 'FAIL'}")
    print(f"\n  OVERALL: {'PASS' if report.get('overall_pass') else 'FAIL'}")
    print("=" * 100)


def write_manifest(report: dict, out_dir: Path) -> None:
    lines = [
        "lantern_frost_bake_spike -- is the baked-frost mechanism O(1) in pane count?",
        f"utc={report['utc']}  windows_build={report['windows_build']}  pyside={report['pyside']}  "
        f"rhi={report['rhi_requested']}  with_island={report['with_island']}",
        "host GPU: Intel UHD iGPU (single host -- a signal, not a universal law)",
        "",
    ]
    for tag, c in report["cells"].items():
        if "FAILED" in c:
            lines.append(f"[{tag}] FAILED: {c['FAILED']}")
            continue
        lines.append(f"[{tag}] panes={c['panes']} rebakeHz={c['rebake_hz']}  "
                     f"cpu={c['process_cpu_pct_of_one_core']}%  qml_fps={c['qml_fps']}  "
                     f"island_hz={c['island_effective_hz']}  bakes_obs={c['bake_count_observed']} "
                     f"(expected~{c['bake_count_expected_approx']})")
    lines.append("")
    v = report["verdict"]
    lines.append(f"(a) cpu_slope_pp_per_pane={v['a_cpu_slope_per_pane_pp']['by_rebake_hz']} "
                 f"-> {'PASS' if v['a_cpu_slope_per_pane_pp']['pass'] else 'FAIL'}")
    lines.append(f"(b) min_qml_fps={v['b_qml_fps_floor']['min_fps']} "
                 f"-> {'PASS' if v['b_qml_fps_floor']['pass'] else 'FAIL'}")
    lines.append(f"(c) min_island_hz={v['c_island_hz_floor']['min_hz']} "
                 f"-> {'PASS' if v['c_island_hz_floor']['pass'] else 'FAIL'}")
    if "M4_stability" in report:
        d = report["M4_stability"]
        lines.append(f"(d) stability: runs={d['runs']} crashes={d['crash_count']} "
                     f"segfaults={d['segfault_count']} -> {'PASS' if d['crash_count'] == 0 else 'FAIL'}")
    lines.append(f"OVERALL: {'PASS' if report.get('overall_pass') else 'FAIL'}")
    (out_dir / "manifest.txt").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def _bootstrap_app(rhi: str):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtWidgets import QApplication

    if rhi == "opengl":
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    elif rhi == "d3d11":
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    return app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LANTERN baked-frost O(1)-in-panes spike.")
    ap.add_argument("--panes", type=int, default=4)
    ap.add_argument("--rebake-hz", type=float, default=12)
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    ap.add_argument("--warmup", type=float, default=DEFAULT_WARMUP_S)
    ap.add_argument("--rhi", default="opengl", choices=["opengl", "d3d11", "default"])
    ap.add_argument("--no-island", action="store_true", help="run the QML cell alone (two-process fallback)")
    ap.add_argument("--stability-n", type=int, default=20, metavar="N")
    ap.add_argument("--hold", type=int, default=0, help="seconds to leave one cell on screen")
    # internal / child-side flags
    ap.add_argument("--cell-run", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--stability-run", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--emit", default=None, metavar="FILE", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    with_island = not args.no_island

    if args.stability_run:
        app = _bootstrap_app(args.rhi)  # noqa: F841 -- keeps QApplication alive
        return stability_probe(args.panes, args.rebake_hz, args.seconds, args.warmup, with_island)

    if args.cell_run:
        app = _bootstrap_app(args.rhi)  # noqa: F841
        reason = _check_real_session()
        if reason:
            print(f"REFUSED: {reason}", file=sys.stderr)
            return 2
        entry = measure_cell(args.panes, args.rebake_hz, args.seconds, args.warmup, with_island=with_island)
        Path(args.emit).write_text(json.dumps(entry, indent=2), encoding="utf-8")
        return 0

    app = _bootstrap_app(args.rhi)
    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    if args.hold > 0:
        from PySide6.QtCore import QTimer
        view = _make_qml_view(args.panes, args.rebake_hz, 80, 80, 940, 620)
        errs = [str(e) for e in view.errors()]
        if errs:
            print("QML ERRORS:", errs, file=sys.stderr)
        view.show()
        island = None
        if with_island:
            island = Island(80 + 940 + 24, 80)
            island.show()
            island.start()
        print(f"holding panes={args.panes} rebakeHz={args.rebake_hz} for {args.hold}s -- watch the panes "
              "step between bakes and the island plot for stalls.")
        sys.stdout.flush()
        QTimer.singleShot(args.hold * 1000, app.quit)
        app.exec()
        if island is not None:
            island.close()
        view.close()
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _REPO_ROOT / "artifacts_claude" / f"lantern_frost_spike_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    from PySide6.QtGui import QGuiApplication
    import PySide6
    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()

    report: dict = {
        "spike": "lantern_frost_bake_spike",
        "utc": ts,
        "windows_build": sys.getwindowsversion().build,  # type: ignore[attr-defined]
        "qt_platform": app.platformName(),
        "pyside": PySide6.__version__,
        "rhi_requested": args.rhi,
        "with_island": with_island,
        "screen": {"dip": [avail.width(), avail.height()], "dpr": screen.devicePixelRatio()},
        "matrix_params": {"panes": list(PANE_COUNTS), "rebake_hz": list(REBAKE_RATES_HZ),
                          "seconds": args.seconds, "warmup_s": args.warmup,
                          "island_nominal_hz": ISLAND_NOMINAL_HZ, "blur_max_px": BLUR_MAX_PX},
        "out_dir": str(out_dir),
    }

    print(f"\nLANTERN frost-bake spike -- matrix ({len(PANE_COUNTS) * len(REBAKE_RATES_HZ) + 1} cells, "
          f"{args.seconds:.0f}s steady state each) + stability({args.stability_n})")
    cells = build_matrix(args.seconds, args.warmup, out_dir, with_island)
    report["cells"] = cells

    verdict = compute_verdict(cells)
    report["verdict"] = verdict

    print(f"\nM4 -- STABILITY: {args.stability_n} process launches, busiest cell "
          f"(panes={PANE_COUNTS[-1]}, rebakeHz={REBAKE_RATES_HZ[-1]})")
    sys.stdout.flush()
    m4 = run_stability(args.stability_n, PANE_COUNTS[-1], REBAKE_RATES_HZ[-1], with_island)
    report["M4_stability"] = m4
    print(f"  runs={m4['runs']} crashes={m4['crash_count']} segfaults={m4['segfault_count']} "
          f"codes={sorted(set(m4['exit_codes']))}")

    report["overall_pass"] = bool(verdict["overall_pass"] and m4["crash_count"] == 0)

    (out_dir / "spike_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_manifest(report, out_dir)
    _print_summary(report)
    print(f"\nartifacts: {out_dir}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
