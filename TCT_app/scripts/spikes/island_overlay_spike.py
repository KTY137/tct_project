"""SPIKE (U2.4 entry micro-spike) -- the IN-WINDOW island overlay measurement.

WHAT GAP THIS CLOSES (docs/design/u2_hero_plan.md SS2 U2.4, risk R1)
--------------------------------------------------------------------
Measurements A and B both proved the Lantern frost bake + living ground hold
rate, BUT both hosted the pyqtgraph island in its OWN separate top-level
window sitting *next to* the QML scene. U2.4's ratified architecture is the
opposite: the real ``gui.scan_map_view.ScanMapView`` island is an ordinary
sibling ``QWidget`` positioned OVER a published hole in a ``QQuickWidget`` that
renders the whole living-glass face, inside ONE top-level window (option-(a)
hole-and-frame, u2_hero_plan.md SS1). The unmeasured question is exactly that
overlay interaction (R1): a live island blitting above a 12 Hz-rebaking QML
texture, in one window, on the weak lab iGPU -- does the island lose rate, does
QML fps drop, does the composite trigger full-window repaint storms?

This throwaway spike composes precisely that arrangement and measures it. It is
the day-0 gate before any ``gui/qml_island_host.py`` code is written.

THE ARRANGEMENT (one top-level window)
--------------------------------------
  * a container ``QWidget`` (the single top-level);
  * a ``QQuickWidget`` (``SizeRootObjectToView``) filling the container,
    rendering the living ground at FULL amplitude + ONE frost bake @ 12 Hz +
    N flanking crop-sampler panes -- the exact ``layer.live:false`` +
    ``ShaderEffectSource`` mechanism from the passing frost spike
    (``scripts/spikes/lantern_frost_bake_spike.py`` / artifact
    ``lantern_frost_spike_20260714T233707Z``), plus a reserved ``mapHole``
    item that publishes its rect (objectName lookup);
  * the REAL ``ScanMapView`` as a sibling ``QWidget`` of the container,
    ``setGeometry`` into the published hole rect + ``raise_()`` above the
    QQuickWidget (texture-composited sibling stacking, no native airspace --
    both islands are raster pyqtgraph, u2_hero_plan.md SS1.4);
  * a SYNTHETIC sim scan-point feed (``QTimer``, 30 Hz nominal) pushing
    duck-typed ScanResults into ``ScanMapView.update_point`` -- NO controller,
    NO DeviceManager, NO devices import anywhere (see SAFETY).

WHAT IS MEASURED (two cells x two passes, measurement-A/B idioms)
----------------------------------------------------------------
Per pass, back to back in one process:
  * ``control`` -- QQuickWidget frost scene ALONE (no island, no feed). The
    storm baseline: what QML fps / scene-render rate / QQuickWidget composite
    rate the window sustains with only the living glass painting.
  * ``overlay`` -- the SAME frost scene + the ScanMapView island overlaid in
    the hole + the 30 Hz synthetic feed driving it. The real U2.4 case.

Signals (all wall-clock, independent probes -- this repo's rule):
  * ``island_feed_hz``     -- effective rate of the 30 Hz point-feed QTimer
                              (the island DRIVE timer, the direct analog of the
                              A/B island's own 30 Hz drive timer -- an
                              event-loop-starvation probe). GATED vs the floor.
  * ``qml_fps``            -- QQuickWidget scene frames via the internal
                              QQuickWindow ``frameSwapped`` counter. GATED.
  * ``scanmap_repaint_hz`` -- the REAL ScanMapView coalesced ImageView repaints
                              (its own ``_redraw`` wrapped/counted). Reported,
                              NOT gated: ScanMapView intentionally coalesces at
                              ~15 Hz (``SCAN_MAP_REDRAW_INTERVAL_MS = 67``), so
                              this is BELOW 28 by design and must not be read
                              against the island floor. It is the honest
                              "how often does the overlaid widget actually
                              blit" number.
  * repaint-storm observations -- QQuickWidget ``paintEvent`` rate + QML
                              ``afterRendering`` (scene-graph render) rate, in
                              BOTH cells; a storm shows up as overlay rates
                              inflated well above the control baseline.
  * process CPU % of one core (Win32 GetProcessTimes; no psutil in this venv).

PASS BAR (measurement-A floors, ratified in the brief)
------------------------------------------------------
  island_feed_hz >= 28.0  AND  qml_fps >= 55.0  -- in BOTH passes.

QUIET-RERUN honesty (brief): another beat may be running targeted pytest on
this laptop. If ANY gated number lands within ~10% of its floor
(island in [25.2, 30.8] or qml_fps in [49.5, 60.5]) the verdict is
**QUIET-RERUN-NEEDED**, never a pass/fail claim -- rerun on a quiet machine.

RUN
---
  # headless mechanics smoke (what an agent runs -- offscreen, NO fps
  # assertions; proves the overlay/hole/feed/teardown wiring, not GPU rate):
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe scripts/spikes/island_overlay_spike.py --smoke

  # the real windowed measurement (a real desktop GPU session -- refuses under
  # offscreen/minimal). This spike class is a RATIFIED exception to the
  # no-app-runs rule *precisely because it imports zero device code and feeds
  # only synthetic data* (brief): it may be run windowed.
  .venv/Scripts/python.exe scripts/spikes/island_overlay_spike.py

SAFETY
------
Zero hardware surface by construction: imports NO ``devices`` module, NO
``DeviceManager``, NO ``controller``. The only app import is
``gui.scan_map_view.ScanMapView`` (verified import-clean: pulls in no
controller/devices module). The scan-point feed is a local synthetic generator
of duck-typed ``ScanResult`` objects; nothing here can reach an instrument.

NOT app code. NOT imported by the app. NOT part of the test suite. Throwaway.
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
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

# --- make the TCT_app package importable when run as a bare script ---------- #
_SPIKES = Path(__file__).resolve().parent
_SCRIPTS = _SPIKES.parent
_TCT_APP = _SCRIPTS.parent
_REPO_ROOT = _TCT_APP.parent
if str(_TCT_APP) not in sys.path:
    sys.path.insert(0, str(_TCT_APP))

ISLAND_NOMINAL_HZ = 30
DEFAULT_PANES = 6
DEFAULT_REBAKE_HZ = 12.0         # living ground "full" -> 12 Hz bake
DEFAULT_SECONDS = 15.0
DEFAULT_WARMUP_S = 3.0
BLUR_MAX_PX = 40                 # matches candidate_lantern.md SS6 blurPane token

# Verdict thresholds (measurement-A floors, ratified in the brief).
ISLAND_HZ_FLOOR = 28.0
QML_FPS_FLOOR = 55.0
NEAR_FLOOR_FRAC = 0.10           # within +/-10% of a floor => QUIET-RERUN-NEEDED

# Exit codes.
EXIT_PASS = 0
EXIT_FAIL = 2
EXIT_GUARD = 3
EXIT_ERROR = 4
EXIT_QUIET = 5                   # a gated number too close to a floor to call

# A Windows access violation surfaces as 0xC0000005 (two encodings).
_SEGFAULT_CODES = (-1073741819, 3221225477)


# --------------------------------------------------------------------------- #
# Process CPU (no psutil in this venv -- GetProcessTimes, same as the A/B      #
# spikes; argtypes/restype are load-bearing or the handle marshals wrong)      #
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
# The QML face -- living ground FULL + ONE bake @ 12 Hz + flanking samplers +   #
# a reserved mapHole (hole-and-frame). Bake mechanism verbatim from the         #
# passing frost spike (layer.live:false + per-pane ShaderEffectSource).         #
# --------------------------------------------------------------------------- #

_QML = """
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property int paneCount: 6
    property real rebakeHz: 12
    property bool groundOn: true
    property int bakeCount: 0

    readonly property real headerH: 72
    readonly property real margin: 32
    readonly property real gap: 16

    // Central reserved island hole, in ROOT coordinates. Because the
    // QQuickWidget uses SizeRootObjectToView, root logical px == the
    // QQuickWidget's logical widget px, so these values map straight to the
    // sibling island's setGeometry with no DPR arithmetic (u2_hero_plan SS1.3).
    readonly property real holeX: root.width * 0.30
    readonly property real holeY: headerH + gap
    readonly property real holeW: root.width * 0.40
    readonly property real holeH: root.height - holeY - margin

    readonly property int perSide: Math.max(1, Math.ceil(paneCount / 2))
    readonly property real sideColW: Math.max(1, holeX - margin - gap)
    readonly property real sidePaneH: Math.max(1,
        (root.height - headerH - gap - margin - (perSide - 1) * gap) / perSide)

    Rectangle { anchors.fill: parent; color: "#0B0D12" }

    Text {
        x: 20; y: 14; color: "#8993A6"; font.pixelSize: 12
        text: "island_overlay_spike -- living ground FULL + frost bake  panes=" + root.paneCount
              + "  rebakeHz=" + root.rebakeHz + "  bakes=" + root.bakeCount
    }

    // ---- layer 0: the animated ambient ground at FULL amplitude -------------
    // (washes move POSITION only, never alpha -- the bake source)
    Item {
        id: groundRoot
        anchors.fill: parent

        Rectangle {
            id: washA
            width: root.width * 0.60; height: width
            radius: width / 2
            x: root.width * 0.02; y: root.height * 0.06
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#5A2F6FEA" }
                GradientStop { position: 1.0; color: "#00202020" }
            }
            SequentialAnimation on x {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.width * 0.40; duration: 8000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * 0.02; duration: 8000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on y {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.height * 0.40; duration: 6500; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.height * 0.04; duration: 6500; easing.type: Easing.InOutSine }
            }
        }
        Rectangle {
            id: washB
            width: root.width * 0.55; height: width
            radius: width / 2
            x: root.width * 0.42; y: root.height * 0.38
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#4800C2CB" }
                GradientStop { position: 1.0; color: "#00202020" }
            }
            SequentialAnimation on x {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.width * 0.02; duration: 10000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * 0.48; duration: 10000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on y {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.height * 0.62; duration: 7500; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.height * 0.10; duration: 7500; easing.type: Easing.InOutSine }
            }
        }
        Rectangle {
            id: washC
            width: root.width * 0.45; height: width
            radius: width / 2
            x: root.width * 0.30; y: root.height * 0.50
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#402FEAB0" }
                GradientStop { position: 1.0; color: "#00202020" }
            }
            SequentialAnimation on x {
                running: root.groundOn
                loops: Animation.Infinite
                NumberAnimation { to: root.width * 0.55; duration: 9000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * 0.10; duration: 9000; easing.type: Easing.InOutSine }
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

    // ---- N flanking sampler panes (cheap crop-blits of the baked texture),
    // laid out in two columns that flank the central hole so they never
    // overlap the island the way the real ScanViewer flanks its map ----------
    Repeater {
        id: paneRepeater
        model: root.paneCount
        delegate: Item {
            id: pane
            required property int index
            readonly property int col: index % 2
            readonly property int rowIndex: Math.floor(index / 2)
            x: col === 0 ? root.margin : (root.holeX + root.holeW + root.gap)
            y: root.headerH + root.gap + rowIndex * (root.sidePaneH + root.gap)
            width: root.sideColW
            height: root.sidePaneH
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

    // ---- the reserved island hole + frame (the island QWidget overlays the
    // interior; the QML never paints inside it -- hole-and-frame, SS1.3) ------
    Item {
        id: mapHole
        objectName: "mapHole"
        x: root.holeX
        y: root.holeY
        width: root.holeW
        height: root.holeH
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.color: "#4CFFFFFF"
            border.width: 1
            radius: 12
        }
        Text {
            x: 8; y: -20; color: "#8993A6"; font.pixelSize: 11
            text: "mapHole (island overlays here)"
        }
    }
}
""".replace("__BLUR_MAX_PX__", str(BLUR_MAX_PX))


def _write_qml_tmp() -> Path:
    tmp = Path(tempfile.gettempdir()) / "tct_island_overlay_spike.qml"
    tmp.write_text(_QML, encoding="utf-8")
    return tmp


def validate_qml() -> list[str]:
    """Parse-only QML validity check (no GL context needed) -- the authoritative
    QML-correctness gate for the smoke. Returns error strings, empty when clean."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    tmp = _write_qml_tmp()
    engine = QQmlEngine()
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(tmp)))
    return [str(e) for e in comp.errors()]


# --------------------------------------------------------------------------- #
# Synthetic scan-point feed -- duck-typed ScanResults, NO controller import     #
# --------------------------------------------------------------------------- #

class _SynthPoint:
    """Duck of ``controller.scan_controller.ScanPoint`` (only the two fields the
    ScanMapViewModel reads). Deliberately NOT the real class -- zero import."""
    __slots__ = ("x_mm", "y_mm")

    def __init__(self, x_mm: float, y_mm: float) -> None:
        self.x_mm = x_mm
        self.y_mm = y_mm


class _SynthResult:
    """Duck of ``controller.scan_controller.ScanResult`` -- carries ``.point``
    plus the map quantities ``ScanMapViewModel._extract_values`` reads by name
    (anything absent falls to NaN there). No controller/devices import."""
    __slots__ = ("point", "dut_charge_pC", "dut_charge_norm", "dut_amplitude_V",
                 "ref_amplitude_V", "baseline_rms_V", "drift_time_s",
                 "rise_time_s", "cfd_time_s")

    def __init__(self, x_mm: float, y_mm: float, charge: float, amp: float) -> None:
        self.point = _SynthPoint(x_mm, y_mm)
        self.dut_charge_pC = charge
        self.dut_amplitude_V = amp
        self.ref_amplitude_V = amp * 0.8
        self.baseline_rms_V = 0.002
        self.dut_charge_norm = float("nan")
        self.drift_time_s = float("nan")
        self.rise_time_s = float("nan")
        self.cfd_time_s = float("nan")


class SimScanFeed:
    """A ``QTimer`` at ``ISLAND_NOMINAL_HZ`` (30) generating synthetic scan
    points along a raster grid and pushing them into ``ScanMapView.update_point``
    -- the "island drive timer" whose effective wall-clock rate is the gated
    ``island_feed_hz``. Cycles the grid so it never runs dry; last-write-wins
    revisits keep the map genuinely re-rendering for the whole window."""

    NX, NY = 50, 40
    X0, X1 = -2.0, 2.0
    Y0, Y1 = -1.5, 1.5

    def __init__(self, island) -> None:
        from PySide6.QtCore import QTimer, Qt
        self._island = island
        self._i = 0
        self._phase = 0.0
        self.tick_times: list[float] = []
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.tick_times = []
        self._timer.start(round(1000 / ISLAND_NOMINAL_HZ))

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        idx = self._i % (self.NX * self.NY)
        ix, iy = idx % self.NX, idx // self.NX
        x = self.X0 + (self.X1 - self.X0) * ix / (self.NX - 1)
        y = self.Y0 + (self.Y1 - self.Y0) * iy / (self.NY - 1)
        self._phase += 0.0007
        r2 = (x * x) / 1.6 + (y * y) / 1.0
        charge = 120.0 * math.exp(-r2) * (1.0 + 0.15 * math.sin(self._phase + ix * 0.3))
        amp = 0.05 + 0.02 * math.cos(self._phase + iy * 0.2)
        self._island.update_point(_SynthResult(x, y, charge, amp))
        self._i += 1
        self.tick_times.append(time.perf_counter())

    def effective_hz(self) -> float:
        tt = self.tick_times
        if len(tt) < 2:
            return 0.0
        return (len(tt) - 1) / (tt[-1] - tt[0])

    def ticks(self) -> int:
        return len(self.tick_times)


# --------------------------------------------------------------------------- #
# The overlay window -- ONE top-level: QQuickWidget filled, ScanMapView sibling #
# --------------------------------------------------------------------------- #

def _counting_quickwidget_cls():
    """QQuickWidget subclass counting ``paintEvent`` (widget-level composite
    blits) -- a direct repaint-storm probe. Defined lazily so importing this
    module needs no Qt."""
    from PySide6.QtQuickWidgets import QQuickWidget

    class CountingQQuickWidget(QQuickWidget):
        def __init__(self, *a, **k) -> None:
            super().__init__(*a, **k)
            self.paint_count = 0

        def paintEvent(self, event):  # noqa: N802 - Qt override
            self.paint_count += 1
            super().paintEvent(event)

    return CountingQQuickWidget


class OverlayWindow:
    """Owns the single top-level container, the frost QQuickWidget, and (when
    ``overlay``) the real ScanMapView island positioned into the published
    ``mapHole`` rect."""

    def __init__(self, panes: int, rebake_hz: float, geo: tuple[int, int, int, int],
                 *, overlay: bool) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QWidget
        from PySide6.QtQuickWidgets import QQuickWidget

        self.overlay = overlay
        self.container = QWidget(None)
        self.container.setWindowTitle(
            f"island_overlay_spike -- {'OVERLAY' if overlay else 'CONTROL'} "
            f"panes={panes} rebakeHz={rebake_hz}")
        x, y, w, h = geo
        self.container.setGeometry(x, y, w, h)
        self.container_paint_count = 0
        self._install_container_paint_counter()

        CQW = _counting_quickwidget_cls()
        self.qqw = CQW(self.container)
        self.qqw.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.qqw.setInitialProperties(
            {"paneCount": panes, "rebakeHz": float(rebake_hz), "groundOn": True})
        self.qqw.setSource(QUrl.fromLocalFile(str(_write_qml_tmp())))
        self.qqw.setGeometry(0, 0, w, h)

        self.island = None
        self._redraw_count = {"n": 0}
        if overlay:
            from gui.scan_map_view import ScanMapView
            self.island = ScanMapView(self.container)
            self._wrap_island_redraw()

        self.feed = SimScanFeed(self.island) if overlay else None

    # -- repaint counters ------------------------------------------------- #

    def _install_container_paint_counter(self) -> None:
        orig = self.container.paintEvent

        def _counted(event):
            self.container_paint_count += 1
            orig(event)

        self.container.paintEvent = _counted  # type: ignore[method-assign]

    def _wrap_island_redraw(self) -> None:
        """Count the REAL ScanMapView coalesced repaints by wrapping its
        instance ``_redraw`` -- every flushed grid rebuild + setImage is one
        actual ImageView blit."""
        orig = self.island._redraw

        def _counted():
            self._redraw_count["n"] += 1
            orig()

        self.island._redraw = _counted  # type: ignore[method-assign]

    def scanmap_repaints(self) -> int:
        return self._redraw_count["n"]

    # -- lifecycle -------------------------------------------------------- #

    def quick_window(self):
        return self.qqw.quickWindow()

    def qml_errors(self) -> list[str]:
        return [str(e) for e in self.qqw.errors()]

    def qml_status(self) -> str:
        return str(self.qqw.status())

    def show(self) -> None:
        self.container.show()
        self.reposition_island()

    def reposition_island(self) -> None:
        """Read the published ``mapHole`` rect and lay the sibling island over
        its interior (inset by the frame). Logical px both sides -> no DPR
        math (the claim this spike also exercises on a 2.5-DPI panel)."""
        if self.island is None:
            return
        from PySide6.QtCore import QObject
        root = self.qqw.rootObject()
        if root is None:
            return
        hole = root.findChild(QObject, "mapHole")
        if hole is None:
            return
        hx = float(hole.property("x")); hy = float(hole.property("y"))
        hw = float(hole.property("width")); hh = float(hole.property("height"))
        inset = 6
        self.island.setGeometry(int(hx + inset), int(hy + inset),
                                int(max(1, hw - 2 * inset)), int(max(1, hh - 2 * inset)))
        self.island.raise_()

    def close(self) -> None:
        if self.feed is not None:
            self.feed.stop()
        if self.island is not None:
            self.island.close()
        self.qqw.close()
        self.container.close()


# --------------------------------------------------------------------------- #
# One measured cell                                                             #
# --------------------------------------------------------------------------- #

def measure_cell(*, overlay: bool, panes: int, rebake_hz: float, seconds: float,
                 warmup_s: float, geo: tuple[int, int, int, int]) -> dict:
    """Build the window, warm up, window the telemetry for ``seconds``, tear
    down. Returns the cell dict."""
    tag = "overlay" if overlay else "control"
    entry: dict = {"cell": tag, "overlay": overlay, "errors": []}

    win = OverlayWindow(panes, rebake_hz, geo, overlay=overlay)
    entry["qml_status"] = win.qml_status()
    entry["qml_errors"] = win.qml_errors()
    if entry["qml_errors"]:
        entry["errors"].append("QML load errors: " + "; ".join(entry["qml_errors"]))

    frames = {"n": 0}
    renders = {"n": 0}
    qwin = win.quick_window()
    if qwin is not None:
        qwin.frameSwapped.connect(lambda: frames.__setitem__("n", frames["n"] + 1))
        qwin.afterRendering.connect(lambda: renders.__setitem__("n", renders["n"] + 1))

    win.show()
    win.reposition_island()

    # warmup: shader compile, bake spin-up, feed reaching steady pace -- NOT measured
    if win.feed is not None:
        win.feed.start()
    _settle(int(warmup_s * 1000))
    win.reposition_island()

    # window the telemetry
    root = qwin  # noqa: F841
    qml_root = win.qqw.rootObject()
    if qml_root is not None:
        qml_root.setProperty("bakeCount", 0)
    frames["n"] = 0
    renders["n"] = 0
    win.qqw.paint_count = 0
    win.container_paint_count = 0
    win._redraw_count["n"] = 0
    if win.feed is not None:
        win.feed.tick_times = []
    cpu0, t0 = _proc_cpu_seconds(), time.perf_counter()
    _settle(int(seconds * 1000))
    cpu1, t1 = _proc_cpu_seconds(), time.perf_counter()
    if win.feed is not None:
        win.feed.stop()

    wall = t1 - t0
    entry["wall_s"] = round(wall, 3)
    entry["qml_fps"] = round(frames["n"] / wall, 2) if wall > 0 else None
    entry["qml_scene_render_hz"] = round(renders["n"] / wall, 2) if wall > 0 else None
    entry["qquickwidget_paint_hz"] = round(win.qqw.paint_count / wall, 2) if wall > 0 else None
    entry["container_paint_hz"] = round(win.container_paint_count / wall, 2) if wall > 0 else None
    entry["process_cpu_pct_of_one_core"] = (
        round((cpu1 - cpu0) / wall * 100.0, 2) if wall > 0 else float("nan"))
    if overlay:
        entry["island_feed_hz"] = round(win.feed.effective_hz(), 2)
        entry["island_feed_ticks"] = win.feed.ticks()
        entry["scanmap_repaint_hz"] = round(win.scanmap_repaints() / wall, 2) if wall > 0 else None
        entry["scanmap_repaints"] = win.scanmap_repaints()
        try:
            win.island.flush_pending()
            entry["island_point_count"] = win.island.point_count()
            entry["island_showing_map"] = bool(win.island.is_showing_map())
        except Exception as exc:  # noqa: BLE001
            entry["errors"].append(f"island read failed: {exc}")
    entry["bake_count_observed"] = (
        int(qml_root.property("bakeCount")) if qml_root is not None else None)
    entry["bake_count_expected_approx"] = round(seconds * rebake_hz)

    win.close()
    _settle(200)
    return entry


# --------------------------------------------------------------------------- #
# Verdict                                                                       #
# --------------------------------------------------------------------------- #

def _near_floor(value, floor: float) -> bool:
    return value is not None and abs(value - floor) <= NEAR_FLOOR_FRAC * floor


def pass_verdict(overlay_cell: dict) -> dict:
    island = overlay_cell.get("island_feed_hz")
    fps = overlay_cell.get("qml_fps")
    near = _near_floor(island, ISLAND_HZ_FLOOR) or _near_floor(fps, QML_FPS_FLOOR)
    if island is None or fps is None:
        state = "NO-DATA"
    elif near:
        state = "QUIET-RERUN-NEEDED"
    elif island >= ISLAND_HZ_FLOOR and fps >= QML_FPS_FLOOR:
        state = "PASS"
    else:
        state = "FAIL"
    return {
        "island_feed_hz": island, "island_floor": ISLAND_HZ_FLOOR,
        "qml_fps": fps, "qml_floor": QML_FPS_FLOOR,
        "near_floor": near, "state": state,
    }


def storm_observation(control_cell: dict, overlay_cell: dict) -> dict:
    """Repaint-storm read: overlay QQuickWidget/scene-render rates vs the
    control baseline. A storm shows as overlay rates inflated well above
    control (the island forcing extra full-scene recomposition)."""
    def ratio(a, b):
        if a is None or b in (None, 0):
            return None
        return round(a / b, 3)

    o_render = overlay_cell.get("qml_scene_render_hz")
    c_render = control_cell.get("qml_scene_render_hz")
    o_paint = overlay_cell.get("qquickwidget_paint_hz")
    c_paint = control_cell.get("qquickwidget_paint_hz")
    render_ratio = ratio(o_render, c_render)
    paint_ratio = ratio(o_paint, c_paint)
    suspected = bool((render_ratio is not None and render_ratio > 1.30)
                     or (paint_ratio is not None and paint_ratio > 1.50))
    return {
        "control_scene_render_hz": c_render, "overlay_scene_render_hz": o_render,
        "scene_render_ratio": render_ratio,
        "control_qqw_paint_hz": c_paint, "overlay_qqw_paint_hz": o_paint,
        "qqw_paint_ratio": paint_ratio,
        "storm_suspected": suspected,
    }


def compute_overall(passes: list[dict]) -> dict:
    states = [p["verdict"]["state"] for p in passes]
    if any(s in ("NO-DATA", "QUIET-RERUN-NEEDED") for s in states):
        overall = "QUIET-RERUN-NEEDED" if "QUIET-RERUN-NEEDED" in states else "NO-DATA"
    elif all(s == "PASS" for s in states):
        overall = "PASS"
    else:
        overall = "FAIL"
    return {"pass_states": states, "overall": overall}


# --------------------------------------------------------------------------- #
# Reporting                                                                     #
# --------------------------------------------------------------------------- #

def _fmt(v) -> str:
    return "n/a" if v is None else str(v)


def _print_verdict_block(report: dict) -> None:
    print("\n" + "=" * 92)
    print("ISLAND OVERLAY SPIKE -- VERDICT  (floors: island_feed_hz >= 28.0, qml_fps >= 55.0)")
    print(f"  build={_fmt(report.get('windows_build'))} qt={_fmt(report.get('qt_platform'))} "
          f"pyside={_fmt(report.get('pyside'))} dpr={_fmt((report.get('screen') or {}).get('dpr'))} "
          f"panes={report.get('panes')} rebakeHz={report.get('rebake_hz')}")
    print("-" * 92)
    for p in report["passes"]:
        v = p["verdict"]
        s = p["storm"]
        print(f"  pass {p['pass']}: island_feed_hz={_fmt(v['island_feed_hz'])} "
              f"qml_fps={_fmt(v['qml_fps'])} -> {v['state']}")
        print(f"           scanmap_repaint_hz(obs,~15 by design)="
              f"{_fmt(p['overlay'].get('scanmap_repaint_hz'))}  "
              f"cpu%={_fmt(p['overlay'].get('process_cpu_pct_of_one_core'))}")
        print(f"           storm: scene_render overlay={_fmt(s['overlay_scene_render_hz'])} "
              f"vs control={_fmt(s['control_scene_render_hz'])} (x{_fmt(s['scene_render_ratio'])}); "
              f"qqw_paint overlay={_fmt(s['overlay_qqw_paint_hz'])} "
              f"vs control={_fmt(s['control_qqw_paint_hz'])} (x{_fmt(s['qqw_paint_ratio'])}) "
              f"-> storm_suspected={s['storm_suspected']}")
    print("-" * 92)
    print(f"  OVERALL: {report['overall']['overall']}   pass_states={report['overall']['pass_states']}")
    print("=" * 92)


def write_artifacts(report: dict, out_dir: Path) -> None:
    (out_dir / "spike_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Watchdog (out-of-process hard kill -- same idiom as measurement B)           #
# --------------------------------------------------------------------------- #

def _spawn_hard_watchdog(pid: int, seconds: float) -> subprocess.Popen:
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
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtWidgets import QApplication

    if not smoke:
        # Real windowed run -> pin OpenGL RHI (same as the A/B spikes + U0
        # probe). Under offscreen we leave Qt's default so the smoke never
        # demands a GL context that isn't there.
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    return QApplication.instance() or QApplication(sys.argv[:1])


def _cell_geometry(idx: int = 0) -> tuple[int, int, int, int]:
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry() if screen else None
    if avail is not None:
        w = min(1200, max(760, avail.width() - 120))
        h = min(800, max(520, avail.height() - 120))
        x = avail.x() + 40 + (idx % 2) * 24
        y = avail.y() + 40 + (idx % 2) * 24
        return x, y, w, h
    return 60, 60, 1120, 740


# --------------------------------------------------------------------------- #
# Smoke (offscreen mechanics -- what an agent runs)                            #
# --------------------------------------------------------------------------- #

def run_smoke(args) -> int:
    app = _bootstrap_app(smoke=True)  # noqa: F841 -- keep QApplication alive
    from PySide6.QtGui import QGuiApplication
    import PySide6

    print("ISLAND OVERLAY SPIKE -- SMOKE (offscreen mechanics; NO fps assertions)")
    print(f"  qt_platform={QGuiApplication.instance().platformName()!r} pyside={PySide6.__version__}")

    # 1. QML parse validity (authoritative -- no GL needed)
    qml_errs = validate_qml()
    print(f"  [1] QML parse: {'OK (no errors)' if not qml_errs else 'ERRORS: ' + '; '.join(qml_errs)}")
    if qml_errs:
        return EXIT_ERROR

    # 2. device-import cleanliness (informational -- the grep is on the source)
    dev_mods = sorted(m for m in sys.modules
                      if m.split(".")[0] in ("controller", "devices"))
    print(f"  [2] controller/devices modules loaded: {dev_mods if dev_mods else 'NONE'}")

    # 3. build the overlay window, position the island into the hole
    win = OverlayWindow(args.panes, args.rebake_hz, _cell_geometry(), overlay=True)
    print(f"  [3] QQuickWidget status={win.qml_status()} errors={win.qml_errors() or 'none'}")
    win.show()
    _settle(500)
    win.reposition_island()
    root = win.qqw.rootObject()
    if root is None:
        print("  [3a] rootObject is None under offscreen -- hole geometry read is "
              "verified only in the windowed run; QML parse (step 1) still authoritative.")
    else:
        from PySide6.QtCore import QObject
        hole = root.findChild(QObject, "mapHole")
        if hole is None:
            print("  [3a] mapHole not found via objectName (FAIL)")
            win.close()
            return EXIT_FAIL
        geo = win.island.geometry()
        print(f"  [3a] mapHole rect=({hole.property('x')},{hole.property('y')},"
              f"{hole.property('width')},{hole.property('height')}) -> island setGeometry="
              f"({geo.x()},{geo.y()},{geo.width()},{geo.height()})")

    # 4. run the synthetic feed briefly, confirm the island accumulates + shows map
    win.feed.start()
    _settle(1500)
    win.feed.stop()
    win.island.flush_pending()
    pts = win.island.point_count()
    showing = win.island.is_showing_map()
    feed_hz = round(win.feed.effective_hz(), 2)
    repaints = win.scanmap_repaints()
    print(f"  [4] feed: ticks={win.feed.ticks()} effective_hz={feed_hz} "
          f"island_points={pts} showing_map={showing} scanmap_repaints={repaints}")

    win.close()
    _settle(150)

    mech_ok = (not qml_errs and pts >= 1 and showing and win.feed.ticks() >= 1
               and repaints >= 1)
    print(f"\n  SMOKE {'PASS' if mech_ok else 'FAIL'} -- "
          f"{'QML + overlay window + hole positioning + synthetic feed + ScanMapView repaint all exercised' if mech_ok else 'a mechanic did not fire'}")
    print("  (GPU rate numbers require the windowed operator run -- offscreen "
          "caps rendering; see module docstring RUN.)")
    return EXIT_PASS if mech_ok else EXIT_FAIL


# --------------------------------------------------------------------------- #
# The real windowed measurement (two cells x two passes)                        #
# --------------------------------------------------------------------------- #

def run_measurement(args) -> int:
    app = _bootstrap_app(smoke=False)
    from PySide6.QtGui import QGuiApplication
    import PySide6

    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return EXIT_GUARD

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _REPO_ROOT / "artifacts_claude" / f"island_overlay_spike_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry() if screen else None
    report: dict = {
        "spike": "island_overlay_spike",
        "utc": ts,
        "windows_build": (sys.getwindowsversion().build      # type: ignore[attr-defined]
                          if hasattr(sys, "getwindowsversion") else None),
        "qt_platform": app.platformName(),
        "pyside": PySide6.__version__,
        "panes": args.panes,
        "rebake_hz": args.rebake_hz,
        "params": {"seconds": args.seconds, "warmup_s": args.warmup,
                   "island_nominal_hz": ISLAND_NOMINAL_HZ, "blur_max_px": BLUR_MAX_PX,
                   "n_passes": 2},
        "thresholds": {"island_hz_floor": ISLAND_HZ_FLOOR, "qml_fps_floor": QML_FPS_FLOOR,
                       "near_floor_frac": NEAR_FLOOR_FRAC},
        "screen": {"dip": [avail.width(), avail.height()] if avail else None,
                   "dpr": screen.devicePixelRatio() if screen else None},
        "out_dir": str(out_dir),
        "passes": [],
    }

    print(f"\nISLAND OVERLAY SPIKE -- {args.seconds:.0f}s window/cell, 2 cells "
          f"(control|overlay) x 2 passes  panes={args.panes} rebakeHz={args.rebake_hz}")
    for p in (1, 2):
        print(f"\n--- pass {p} / control: frost scene alone (storm baseline) ---")
        sys.stdout.flush()
        control = measure_cell(overlay=False, panes=args.panes, rebake_hz=args.rebake_hz,
                               seconds=args.seconds, warmup_s=args.warmup,
                               geo=_cell_geometry(0))
        print(f"    qml_fps={control.get('qml_fps')} scene_render_hz={control.get('qml_scene_render_hz')} "
              f"qqw_paint_hz={control.get('qquickwidget_paint_hz')} cpu%={control.get('process_cpu_pct_of_one_core')}")

        print(f"--- pass {p} / overlay: frost scene + ScanMapView island + 30 Hz feed ---")
        sys.stdout.flush()
        overlay = measure_cell(overlay=True, panes=args.panes, rebake_hz=args.rebake_hz,
                               seconds=args.seconds, warmup_s=args.warmup,
                               geo=_cell_geometry(1))
        print(f"    island_feed_hz={overlay.get('island_feed_hz')} qml_fps={overlay.get('qml_fps')} "
              f"scanmap_repaint_hz={overlay.get('scanmap_repaint_hz')} "
              f"cpu%={overlay.get('process_cpu_pct_of_one_core')} "
              f"points={overlay.get('island_point_count')}")

        report["passes"].append({
            "pass": p,
            "control": control,
            "overlay": overlay,
            "verdict": pass_verdict(overlay),
            "storm": storm_observation(control, overlay),
        })

    report["overall"] = compute_overall(report["passes"])
    write_artifacts(report, out_dir)
    _print_verdict_block(report)
    print(f"\nartifacts: {out_dir}\n")

    state = report["overall"]["overall"]
    if state == "PASS":
        return EXIT_PASS
    if state == "QUIET-RERUN-NEEDED" or state == "NO-DATA":
        return EXIT_QUIET
    return EXIT_FAIL


def run_hold(args) -> int:
    """Eyeball mode: leave the overlay scene + live synthetic feed on screen."""
    app = _bootstrap_app(smoke=False)
    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return EXIT_GUARD
    from PySide6.QtCore import QTimer
    win = OverlayWindow(args.panes, args.rebake_hz, _cell_geometry(), overlay=True)
    errs = win.qml_errors()
    if errs:
        print("QML ERRORS:", errs, file=sys.stderr)
    win.show()
    win.reposition_island()
    win.feed.start()
    print(f"holding overlay scene + live synthetic feed for {args.hold}s -- watch the "
          "island map for stalls and the flanking panes for bake steps.")
    sys.stdout.flush()
    QTimer.singleShot(args.hold * 1000, app.quit)
    app.exec()
    win.close()
    return EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="U2.4 island-overlay entry micro-spike.")
    ap.add_argument("--smoke", action="store_true",
                    help="headless mechanics check (offscreen; no fps assertions)")
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help="window per cell")
    ap.add_argument("--warmup", type=float, default=DEFAULT_WARMUP_S)
    ap.add_argument("--panes", type=int, default=DEFAULT_PANES)
    ap.add_argument("--rebake-hz", type=float, default=DEFAULT_REBAKE_HZ)
    ap.add_argument("--hold", type=int, default=0, help="eyeball: leave overlay scene on screen N s")
    ap.add_argument("--watchdog", type=float, default=0.0,
                    help="hard out-of-process kill after N s (0 = auto)")
    args = ap.parse_args(argv)

    if args.hold > 0:
        wd_timeout = args.hold + 60.0
    elif args.smoke:
        wd_timeout = 120.0
    else:
        # 2 passes x 2 cells, each ~ warmup + seconds + teardown
        wd_timeout = 4 * (args.warmup + args.seconds + 8.0) + 90.0
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
