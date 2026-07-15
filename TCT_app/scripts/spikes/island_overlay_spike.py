"""SPIKE (U2.4 entry micro-spike + mitigation matrix) -- the IN-WINDOW island
overlay measurement, and its follow-up.

WHAT GAP THIS CLOSES (docs/design/u2_hero_plan.md SS2 U2.4, risk R1)
--------------------------------------------------------------------
Measurements A and B both proved the Lantern frost bake + living ground hold
rate, BUT both hosted the pyqtgraph island in its OWN separate top-level
window sitting *next to* the QML scene. U2.4's ratified architecture is the
opposite: the real ``gui.scan_map_view.ScanMapView`` island is an ordinary
sibling ``QWidget`` positioned OVER a published hole in a ``QQuickWidget`` that
renders the whole living-glass face, inside ONE top-level window (option-(a)
hole-and-frame, u2_hero_plan.md SS1). This spike composes precisely that
arrangement and measures it.

FIRST RESULT (artifacts_claude/island_overlay_spike_20260715T111751Z, quiet
machine): FAIL, hard. ``scene_render_hz`` 60 -> 23, ``island_feed_hz`` 30 -> 16,
CPU 23% -> 80% of one core. The control cell (frost+ground alone) held a clean
60 fps -- the living-glass material is innocent; the raster-sibling-over-
QQuickWidget *composition* is the killer. ``storm_suspected=False`` (the ratio
math is tuned to flag an inflated overlay rate; here the overlay rate
*collapsed*, which is a different, worse mechanism: full-backing-store
recomposition of the whole QQuickWidget FBO on every island repaint tick,
CPU-bound on the GUI thread, starving the event loop and every timer in it).
Also: the ``qml_fps`` probe (``QQuickWindow.frameSwapped``) read 0.0 in every
windowed cell -- ``QQuickWidget`` renders to an offscreen FBO and composites
it into the widget backing store; it never performs a real "buffer swap", so
``frameSwapped`` structurally never fires for this widget class. Fixed below
by switching to ``QQuickWindow.afterFrameEnd`` (Qt 6.11), the render-loop-
agnostic "a frame just finished" signal that *does* fire for the FBO/RHI
render-to-texture path. ``qml_scene_render_hz`` (``afterRendering``) remains
the ratified gating metric per the follow-up brief; ``qml_fps`` is now a
real, reportable cross-check, not the gate.

MITIGATION MATRIX (this follow-up -- still throwaway, still a half-day box)
-----------------------------------------------------------------------------
Same one-window arrangement, now built from a per-cell config (``CELLS``
below) so a battery of targeted compositing mitigations can be tried and
tabulated against the same M0 baseline and the same PASS BAR, in one run.

  M0 (kept, unmodified)
    ``m0_control``  -- frost scene alone, no island, no feed. Storm baseline.
    ``m0_overlay``  -- unmitigated overlay (the exact prior-spike FAIL case),
                       carried forward as the matrix's reference failure row.

  M1 -- damage clipping (``m1_opaque_island``)
    Flags the island (``WA_OpaquePaintEvent`` + ``autoFillBackground``) AND an
    intermediate holder ``QWidget`` at the published hole rect with the same
    flags, plus the pyqtgraph viewport's own ``QGraphicsView``
    (``ui.graphicsView``) opacity-fied the same way. HYPOTHESIS: if Qt's
    widget-compositing backing store can prove the island's paint is fully
    opaque over its own rect, damage/composition work should clip to that
    rect instead of recomposing the whole ``QQuickWidget`` -- ``scene_render_hz``
    should recover toward the M0 control baseline.

  M2 -- opaque QQuickWidget (``m2_opaque_qqw``)
    ``WA_OpaquePaintEvent`` + an opaque ``setClearColor`` on the
    ``QQuickWidget`` itself (matching the QML root's own background so no
    seam appears). HYPOTHESIS: an opaque top-level composited surface lets Qt
    skip erase/alpha-blend bookkeeping on the widget's own repaint, cutting
    per-tick overhead independent of M1. NOTE (Qt 6.11 partial-update
    knobs): I could not find an actual damage-region/partial-update knob for
    ``QQuickWidget`` itself -- its FBO-per-frame render-to-texture model
    repaints the whole scene graph each frame regardless of clear-color
    opacity; the opacity flags here act on the *widget-compositing* side
    (this widget's own backing-store blit into its parent), not the QML
    scene graph's internal work. Documented so the result isn't
    over-interpreted as "found a Quick-side partial-update switch".

  M1+M2 combined (``m1_m2_combined``)
    Both mitigations stacked -- the upper bound of what widget-level opacity
    flags alone can buy, and whether they compound or one subsumes the other.

  M3 -- area-scaling diagnostic (``m3_half_area``, DIAGNOSTIC, not a fix)
    ``QQuickWidget`` resized to ~50% of the window area; the island moved
    OUTSIDE it entirely (a sibling strip beside it, zero overlap, no hole
    read at all). HYPOTHESIS: if the failure is a fixed-cost full-FBO blit
    proportional to blit *area*, shrinking that area should raise
    ``scene_render_hz`` roughly in proportion -- confirming (or refuting) the
    "recomposites the whole backing store" mechanism versus a per-widget
    fixed overhead independent of size.

  M4 -- island-rate-scaling diagnostic (``m4_feed15`` / ``m4_feed8``,
        DIAGNOSTIC, not a fix)
    Same unmitigated hole-and-frame arrangement, but the synthetic feed
    (and hence the island's own coalesced repaint pressure) is driven at
    15 Hz and 8 Hz instead of the nominal 30 Hz. HYPOTHESIS: if
    ``scene_render_hz`` scales up as the island's own tick/repaint rate goes
    down, the mechanism is *paced by the island's repaint frequency itself*
    (each island paint triggers one full QQuickWidget recomposite) rather
    than a fixed per-frame cost independent of how often the island paints.
    These floors are gated the same as everywhere (island_feed_hz >= 28) but
    a 15/8 Hz *drive* structurally cannot clear that floor -- the state is
    prefixed ``DIAGNOSTIC-`` so it is never misread as a real pass/fail.

  M5 -- QSG_RENDER_LOOP=basic (``m5_render_loop_basic``, DIAGNOSTIC,
        TOKEN-tier optional pick)
    Qt Quick's render-loop mode must be fixed before ``QGuiApplication``
    exists, so this cell is measured by RE-EXECING this script as a
    subprocess with the env var set (``run_measure_one`` / ``--measure-one``
    below), never in-process. HYPOTHESIS: the default threaded render loop
    pipelines GUI-thread and render-thread work; ``basic`` forces
    synchronous same-thread rendering, which could help (no cross-thread
    sync stalls feeding the starvation) or hurt (removes the one thread that
    was NOT blocked by the GUI-thread event loop). A data point, not an
    expected fix.

RESULT OF THE FIRST MATRIX RUN (windowed, quiet machine,
artifacts_claude/island_overlay_spike_matrix_20260715T121526Z): ALL MITIGATIONS
FAILED, both passes. Control held 60.0-60.1 fps @ 22-27% CPU; every overlay
cell (M0/M1/M2/M1+M2) sat at 23-28 scene_render_hz @ 68-80% CPU regardless of
opacity flags. The two most diagnostic rows both fired negatively:
``m3_half_area`` (QQuickWidget at 50% area, island NOT overlapping it at all)
STILL failed (~24-27 Hz), and ``m4_feed8`` (island driven at ~7 Hz) STILL
failed (~20-24 Hz) -- ruling out blit-area-proportional cost AND island-rate
pacing as the mechanism, on top of M1/M2 already ruling out damage-clip/opacity
provability, and M5 ruling out the render-loop mode. The conclusion: the mere
*presence* of a raster sibling QWidget anywhere over/near a QQuickWidget
forces Qt to CPU-composite the whole top-level's backing store on every QML
frame, independent of area, opacity flags, or pacing -- a compositing-model
fact of ``QQuickWidget`` + a raster sibling in the same window, not a tunable.

NATIVE-SURFACE FOLLOW-UP (M6/M7 -- masterplan's own "revisit WindowContainer
at Qt 6.10+ with a bench spike" clause is active on this Qt 6.11.1 build)
-----------------------------------------------------------------------------
Before escalating the design pivot to the architect on hypothesis alone, two
native-surface candidates are added as MEASURED cells, not assumed:

  M6 -- native island (``m6_native_island``)
    The island keeps its ``QQuickWidget``-hosting arrangement (hole-and-frame,
    unmodified), but the island itself is given ``WA_NativeWindow`` (forced via
    an explicit ``winId()`` call right after parenting) -- its own native
    (HWND) surface that DWM composites above the QQuickWidget, instead of
    sharing its backing store. HYPOTHESIS: the QQuickWidget's own repaint
    should return to its unopposed 60fps path once no raster sibling shares
    its backing store at all. WATCH FOR (operator eyeball via
    ``--hold --hold-cell m6_native_island``): geometry/z-order/DPR-2.5
    correctness of the native child, and flicker on move/resize (this spike's
    protocol is a static single-shot geometry read, not a live resize test --
    ``island_internal_win_id_nonzero`` and ``island_final_geometry`` are
    recorded in every cell's measurement dict as a structural check; the
    move/resize flicker read itself needs the operator's eyeball).

  M7 -- native QML host (``m7_native_qml``)
    QML is hosted via ``QQuickView`` + ``QWidget.createWindowContainer``
    instead of ``QQuickWidget`` -- QML renders through a real native
    swapchain, never through the FBO->backing-store path at all. Airspace
    consequence (brief): a native window-container renders ABOVE raster
    siblings regardless of widget z-order, so the island in this cell is ALSO
    native (``WA_NativeWindow``) to stack above the QML -- which this design's
    dead-zone law already requires (nothing may ever render above an island),
    so this is not a new constraint, just the first cell that measures it.
    KNOWN HAZARD, NARROWED (reproduced empirically during this beat, NOT a
    Python exception -- a hard process segfault): a BARE MINIMAL
    ``createWindowContainer(QQuickView) + .show()`` with NO explicit teardown
    (letting CPython's interpreter-shutdown GC destroy the QQuickView/
    container in whatever order it chooses) segfaults deterministically
    (3/3) at process exit under the ``offscreen`` QPA platform on this
    PySide6/Qt build (6.11.1). This spike's own code, which always calls
    ``win.close()`` (stops the feed, closes island then host then container,
    in that order) BEFORE the process would naturally exit, did NOT
    reproduce the crash in any observed run (7/7 clean: the ``--smoke
    --cells all`` run below, plus 4 repeated standalone ``--measure-one``
    invocations) -- strongly suggesting the hazard is an object-destruction-
    order issue that ``close()``-before-exit discipline avoids, not an
    unconditional property of the API combination. The cell is STILL always
    subprocess-isolated (``isolate=True``, the same re-exec mechanism M5 uses
    for its env requirement) as defense-in-depth -- an exception mid-
    measurement that skips ``close()``, or the real "windows" QPA platform,
    could behave differently -- and the parent process trusts the JSON
    result file over the subprocess's exit code regardless, since the file
    is written before any teardown code runs. Whether the bare hazard (or
    any other) reproduces under the real "windows" QPA platform is unknown
    until the operator's windowed run -- report it either way.

Every cell (mitigation or diagnostic) is measured against the SAME PASS BAR:
``island_feed_hz >= 28.0 AND qml_scene_render_hz >= 55.0``, in every pass
(``--passes``, default 2, matching the original QUIET-RERUN-NEEDED
protocol), printed as one combined table.

RUN
---
  # headless mechanics smoke (what an agent runs -- offscreen, NO fps
  # assertions; proves every selected cell constructs + the env-reexec
  # subprocess/JSON plumbing for env-gated cells, not GPU rate):
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe scripts/spikes/island_overlay_spike.py --smoke
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe scripts/spikes/island_overlay_spike.py --smoke --cells all

  # the real windowed matrix (a real desktop GPU session -- refuses under
  # offscreen/minimal). Same ratified exception as before: zero device
  # imports, only synthetic data.
  .venv/Scripts/python.exe scripts/spikes/island_overlay_spike.py --cells all

  # a narrower/faster matrix run (e.g. just the two required mitigations):
  .venv/Scripts/python.exe scripts/spikes/island_overlay_spike.py --cells m0_control,m0_overlay,m1_opaque_island,m2_opaque_qqw

  # operator eyeball for M6/M7 flicker/z-order/geometry-drift on move/resize
  # (this protocol's own measurement is a static single-shot geometry read):
  .venv/Scripts/python.exe scripts/spikes/island_overlay_spike.py --hold 30 --hold-cell m6_native_island
  .venv/Scripts/python.exe scripts/spikes/island_overlay_spike.py --hold 30 --hold-cell m7_native_qml

SAFETY
------
Zero hardware surface by construction: imports NO ``devices`` module, NO
``DeviceManager``, NO ``controller``. The only app import is
``gui.scan_map_view.ScanMapView``. The scan-point feed is a local synthetic
generator of duck-typed ``ScanResult`` objects; nothing here can reach an
instrument. The env-reexec subprocess (M5) launches only this same script
with an extra env var -- no new import surface.

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
DEFAULT_PASSES = 2               # "both passes each" -- kept from the original protocol
BLUR_MAX_PX = 40                 # matches candidate_lantern.md SS6 blurPane token

# Verdict thresholds (measurement-A floors, ratified in the brief; the
# follow-up brief keeps the numeric bar but gates on qml_scene_render_hz --
# the proven-reliable proxy -- rather than the (now fixed, but still
# secondary) qml_fps probe).
ISLAND_HZ_FLOOR = 28.0
SCENE_HZ_FLOOR = 55.0
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
# The mitigation-matrix cell registry                                          #
# --------------------------------------------------------------------------- #
# Every cell is a plain dict of construction knobs consumed by OverlayWindow /
# measure_cell. ``overlay=False`` cells (m0_control) carry no island/feed at
# all. ``env`` cells can only be measured correctly in a fresh process (Qt
# reads these before QGuiApplication exists) -- run_measurement/run_smoke
# re-exec this same script as a subprocess for those, see run_measure_one().

CELLS: dict[str, dict] = {
    "m0_control": dict(
        label="M0 control (frost scene alone)",
        hypothesis="Storm baseline: living-glass QML scene alone, no island, "
                   "no feed -- what the window sustains unopposed.",
        overlay=False,
    ),
    "m0_overlay": dict(
        label="M0 overlay (unmitigated -- prior spike's FAIL case)",
        hypothesis="Baseline failure: raster sibling QWidget composited over "
                   "the full QQuickWidget; every island repaint tick appears "
                   "to force a full-FBO recomposite on the GUI thread.",
        overlay=True,
    ),
    "m1_opaque_island": dict(
        label="M1 damage-clipped island (opaque island + holder + pg viewport)",
        hypothesis="If the backing store can prove the island's paint is "
                   "fully opaque over its own rect, damage should clip to "
                   "that rect instead of recompositing the whole "
                   "QQuickWidget -- scene_render_hz should recover.",
        overlay=True, opaque_island=True,
    ),
    "m2_opaque_qqw": dict(
        label="M2 opaque QQuickWidget (opaque clearColor + WA_OpaquePaintEvent)",
        hypothesis="An opaque QQuickWidget composited surface may let Qt "
                   "skip erase/alpha-blend bookkeeping on its own repaint, "
                   "independent of M1 (does not touch the QML scene graph "
                   "itself -- see docstring note on partial-update knobs).",
        overlay=True, opaque_qqw=True,
    ),
    "m1_m2_combined": dict(
        label="M1+M2 combined",
        hypothesis="Upper bound of what widget-level opacity flags alone "
                   "can buy -- do the two mitigations compound, or does one "
                   "subsume the other?",
        overlay=True, opaque_island=True, opaque_qqw=True,
    ),
    "m3_half_area": dict(
        label="M3 half-area diagnostic (QQuickWidget ~50% area, island beside it)",
        hypothesis="DIAGNOSTIC, not a fix: if scene_render_hz scales up "
                   "roughly with the smaller Quick blit area, the mechanism "
                   "is a full-backing-store blit proportional to area, not "
                   "a fixed per-tick cost.",
        overlay=True, area_scale=0.5, diagnostic_only=True,
    ),
    "m4_feed15": dict(
        label="M4 island-rate diagnostic @ 15 Hz drive",
        hypothesis="DIAGNOSTIC: if scene_render_hz rises as the island's own "
                   "tick/repaint rate drops, each island repaint is what "
                   "forces one full QQuickWidget recomposite (rate-paced), "
                   "not a fixed background cost. island_feed_hz cannot clear "
                   "the 28 floor at this drive rate by construction.",
        overlay=True, island_hz=15.0, diagnostic_only=True,
    ),
    "m4_feed8": dict(
        label="M4 island-rate diagnostic @ 8 Hz drive",
        hypothesis="Same as m4_feed15 at a lower drive rate -- extends the "
                   "scaling trend read.",
        overlay=True, island_hz=8.0, diagnostic_only=True,
    ),
    "m5_render_loop_basic": dict(
        label="M5 QSG_RENDER_LOOP=basic (env re-exec, TOKEN-tier data point)",
        hypothesis="DIAGNOSTIC: forcing the synchronous 'basic' render loop "
                   "removes GUI/render-thread pipelining. Could help (no "
                   "cross-thread sync stall feeding the starvation) or hurt "
                   "(removes the one thread not blocked by the GUI event "
                   "loop). Not an expected fix, a data point.",
        overlay=True, env={"QSG_RENDER_LOOP": "basic"}, diagnostic_only=True,
    ),
    "m6_native_island": dict(
        label="M6 native island (WA_NativeWindow on the island; QQuickWidget stays)",
        hypothesis="A native DWM-composited surface for the island removes it "
                   "from the QQuickWidget's shared backing store entirely -- "
                   "the QQuickWidget's own repaint should return to its "
                   "unopposed 60fps path. Watch (operator eyeball, "
                   "--hold --hold-cell m6_native_island): geometry/z-order/"
                   "DPR-2.5 correctness of the native child, flicker on "
                   "move/resize.",
        overlay=True, native_island=True,
    ),
    "m7_native_qml": dict(
        label="M7 native QML host (QQuickView + createWindowContainer; native island)",
        hypothesis="QML renders through a real native swapchain, never the "
                   "FBO->backing-store path -- its repaint should be fully "
                   "uncoupled from the island. Airspace consequence: a "
                   "window-container renders ABOVE raster siblings regardless "
                   "of z-order, so the island here is ALSO native "
                   "(WA_NativeWindow) -- already required by the dead-zone "
                   "law. NARROWED HAZARD: a bare createWindowContainer + "
                   "show() with no explicit teardown segfaults at process "
                   "exit under offscreen on this build; this spike's own "
                   "disciplined close() avoided it in every observed run "
                   "(see module docstring) -- still ALWAYS subprocess-"
                   "isolated as defense-in-depth so any crash cannot take "
                   "down the rest of the matrix.",
        overlay=True, native_qml=True, native_island=True, isolate=True,
    ),
}

_CELL_ORDER = list(CELLS.keys())


def _resolve_cells(spec: str) -> list[str]:
    """Parse ``--cells`` ('all' or a comma list of ids) into an ordered,
    deduplicated, validated list of registry keys."""
    if spec.strip().lower() == "all":
        return list(_CELL_ORDER)
    ids = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = [i for i in ids if i not in CELLS]
    if unknown:
        raise ValueError(
            f"unknown cell id(s) {unknown} -- valid ids: {_CELL_ORDER}")
    # de-dup, preserve requested order
    seen: list[str] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen


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
    """A ``QTimer`` at ``hz`` (nominally :data:`ISLAND_NOMINAL_HZ`, overridable
    per cell for the M4 rate-scaling diagnostic) generating synthetic scan
    points along a raster grid and pushing them into ``ScanMapView.update_point``
    -- the "island drive timer" whose effective wall-clock rate is the gated
    ``island_feed_hz``. Cycles the grid so it never runs dry; last-write-wins
    revisits keep the map genuinely re-rendering for the whole window."""

    NX, NY = 50, 40
    X0, X1 = -2.0, 2.0
    Y0, Y1 = -1.5, 1.5

    def __init__(self, island, hz: float = ISLAND_NOMINAL_HZ) -> None:
        from PySide6.QtCore import QTimer, Qt
        self._island = island
        self._hz = float(hz)
        self._i = 0
        self._phase = 0.0
        self.tick_times: list[float] = []
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.tick_times = []
        self._timer.start(round(1000 / max(0.1, self._hz)))

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
# (now cell-config-driven: opaque flags, area scaling, drive rate).            #
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
    ``overlay``) the real ScanMapView island -- either positioned into the
    published ``mapHole`` rect (default hole-and-frame layout) or, for the M3
    diagnostic (``area_scale < 1``), as a non-overlapping sibling strip beside
    a shrunk QQuickWidget."""

    def __init__(self, panes: int, rebake_hz: float, geo: tuple[int, int, int, int],
                 *, overlay: bool, opaque_island: bool = False,
                 opaque_qqw: bool = False, area_scale: float = 1.0,
                 island_hz: float = ISLAND_NOMINAL_HZ,
                 native_island: bool = False) -> None:
        from PySide6.QtCore import QUrl, Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QWidget
        from PySide6.QtQuickWidgets import QQuickWidget

        self.overlay = overlay
        self.area_scale = float(area_scale)
        self.container = QWidget(None)
        self.container.setWindowTitle(
            f"island_overlay_spike -- {'OVERLAY' if overlay else 'CONTROL'} "
            f"panes={panes} rebakeHz={rebake_hz} opaque_island={opaque_island} "
            f"opaque_qqw={opaque_qqw} area_scale={area_scale} island_hz={island_hz}")
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
        qqw_w = w if self.area_scale >= 0.999 else max(80, int(w * self.area_scale))
        self.qqw.setGeometry(0, 0, qqw_w, h)
        if opaque_qqw:
            # M2: opaque top-level composited surface. Matches the QML
            # root's own bg color so no seam appears at the widget edge.
            self.qqw.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            self.qqw.setClearColor(QColor("#0B0D12"))

        self.island = None
        self.island_holder = None
        self._island_outer = None
        self._redraw_count = {"n": 0}
        if overlay:
            from gui.scan_map_view import ScanMapView
            if opaque_island:
                # M1: an intermediate holder QWidget at the hole rect,
                # flagged opaque, hosting the island -- the "and/or an
                # intermediate container" half of the brief.
                self.island_holder = QWidget(self.container)
                self.island_holder.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
                self.island_holder.setAutoFillBackground(True)
                pal = self.island_holder.palette()
                pal.setColor(self.island_holder.backgroundRole(), QColor("#0B0D12"))
                self.island_holder.setPalette(pal)
                self.island = ScanMapView(self.island_holder)
                self.island.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
                self.island.setAutoFillBackground(True)
                self._apply_opaque_pg_viewport(self.island)
                self._island_outer = self.island_holder
            else:
                self.island = ScanMapView(self.container)
                self._island_outer = self.island
            if native_island:
                # M6: force the island (or its opaque holder, if combined)
                # onto its own native (HWND) surface, DWM-composited above
                # the QQuickWidget instead of sharing its backing store.
                # winId() forces creation now rather than waiting on show().
                self._island_outer.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
                self._island_outer.winId()
            self._wrap_island_redraw()

        self.feed = SimScanFeed(self.island, hz=island_hz) if overlay else None

    @staticmethod
    def _apply_opaque_pg_viewport(island) -> None:
        """M1: flag the pyqtgraph ImageView's own QGraphicsView viewport
        opaque too -- the island's actual paint surface, one level below the
        ScanMapView QWidget wrapper."""
        from PySide6.QtCore import Qt
        view = island.image_view()
        if view is None:
            return
        gv = view.ui.graphicsView
        gv.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        gv.setAutoFillBackground(True)

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
        """Position the island (or its opaque holder, M1) either into the
        published ``mapHole`` rect (default) or, for the M3 area-scaling
        diagnostic (``area_scale < 1``), as a non-overlapping sibling strip
        beside the shrunk QQuickWidget -- no hole read at all in that mode."""
        if self.island is None:
            return
        outer = self._island_outer

        if self.area_scale < 0.999:
            qw = self.qqw.width()
            cw = self.container.width()
            ch = self.container.height()
            gap = 12
            xpos = qw + gap
            outer_w = max(1, cw - xpos - 8)
            outer.setGeometry(xpos, 8, outer_w, max(1, ch - 16))
            if outer is not self.island:
                self.island.setGeometry(0, 0, outer.width(), outer.height())
            outer.raise_()
            self.island.raise_()
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
        outer.setGeometry(int(hx + inset), int(hy + inset),
                          int(max(1, hw - 2 * inset)), int(max(1, hh - 2 * inset)))
        if outer is not self.island:
            self.island.setGeometry(0, 0, outer.width(), outer.height())
        outer.raise_()
        self.island.raise_()

    def close(self) -> None:
        if self.feed is not None:
            self.feed.stop()
        if self.island is not None:
            self.island.close()
        if self.island_holder is not None:
            self.island_holder.close()
        self.qqw.close()
        self.container.close()


class _PaintCounter:
    """Minimal duck-typed stand-in exposing only ``.paint_count`` -- lets
    :class:`NativeContainerWindow` present a ``.qqw.paint_count`` attribute
    identical in shape to :class:`OverlayWindow`'s counting QQuickWidget
    subclass, so ``measure_cell``/``_smoke_check_cell`` never need to know
    which window class they are driving."""

    def __init__(self) -> None:
        self.paint_count = 0


class NativeContainerWindow:
    """M7: QML hosted via ``QQuickView`` + ``QWidget.createWindowContainer``
    instead of ``QQuickWidget`` -- renders through a real native swapchain,
    never the FBO->backing-store path at all. Airspace consequence (dead-zone
    law): a native window-container renders ABOVE raster siblings regardless
    of widget z-order, so the island here is also given ``WA_NativeWindow``.

    KNOWN HAZARD, NARROWED (see module docstring): a BARE MINIMAL
    ``createWindowContainer`` + ``.show()`` with no explicit teardown
    segfaults deterministically at process exit under offscreen on this
    build; THIS class's own disciplined ``close()`` (feed -> island -> host
    -> container, always called before process exit) did not reproduce it in
    7/7 observed runs. Every caller still goes through the subprocess-
    isolation path regardless (this cell's spec sets ``isolate=True`` -- see
    ``_needs_subprocess``) as defense-in-depth, so a crash from any cause
    can never take down the rest of the matrix or the smoke suite; the
    parent trusts the JSON result file over the subprocess exit code, since
    the file is written well before any teardown code runs."""

    def __init__(self, panes: int, rebake_hz: float, geo: tuple[int, int, int, int],
                 *, native_island: bool = True, island_hz: float = ISLAND_NOMINAL_HZ) -> None:
        from PySide6.QtCore import QUrl, Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QWidget
        from PySide6.QtQuick import QQuickView

        self.overlay = True
        self.area_scale = 1.0
        self.container = QWidget(None)
        self.container.setWindowTitle(
            f"island_overlay_spike -- M7 NATIVE-QML-HOST panes={panes} "
            f"rebakeHz={rebake_hz} native_island={native_island} island_hz={island_hz}")
        x, y, w, h = geo
        self.container.setGeometry(x, y, w, h)
        self.container_paint_count = 0
        self._install_container_paint_counter()

        self.quick_view = QQuickView()
        self.quick_view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.quick_view.setInitialProperties(
            {"paneCount": panes, "rebakeHz": float(rebake_hz), "groundOn": True})
        self.quick_view.setColor(QColor("#0B0D12"))  # opaque native swapchain clear
        self.quick_view.setSource(QUrl.fromLocalFile(str(_write_qml_tmp())))

        self._host = QWidget.createWindowContainer(self.quick_view, self.container)
        self._host.setGeometry(0, 0, w, h)
        self.qqw = _PaintCounter()   # duck-typed: measure_cell reads win.qqw.paint_count
        self._install_host_paint_counter()

        from gui.scan_map_view import ScanMapView
        self.island = ScanMapView(self.container)
        self.island_holder = None
        self._island_outer = self.island
        if native_island:
            # Airspace consequence: the window-container's native surface
            # renders above ordinary raster siblings regardless of widget
            # z-order/raise_() -- the island MUST be native too to stack
            # above the QML (the dead-zone law already requires this).
            self.island.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            self.island.winId()
        self._redraw_count = {"n": 0}
        self._wrap_island_redraw()

        self.feed = SimScanFeed(self.island, hz=island_hz)

    def _install_container_paint_counter(self) -> None:
        orig = self.container.paintEvent

        def _counted(event):
            self.container_paint_count += 1
            orig(event)

        self.container.paintEvent = _counted  # type: ignore[method-assign]

    def _install_host_paint_counter(self) -> None:
        """Window-container widgets rarely receive real ``paintEvent``s (the
        actual QML pixels bypass QWidget painting entirely, DWM-composited
        natively) -- this staying near 0 is itself the expected/interesting
        signal, not a bug in the counter."""
        orig = self._host.paintEvent

        def _counted(event):
            self.qqw.paint_count += 1
            orig(event)

        self._host.paintEvent = _counted  # type: ignore[method-assign]

    def _wrap_island_redraw(self) -> None:
        orig = self.island._redraw

        def _counted():
            self._redraw_count["n"] += 1
            orig()

        self.island._redraw = _counted  # type: ignore[method-assign]

    def scanmap_repaints(self) -> int:
        return self._redraw_count["n"]

    def quick_window(self):
        return self.quick_view  # QQuickView IS its own QQuickWindow

    def qml_errors(self) -> list[str]:
        return [str(e) for e in self.quick_view.errors()]

    def qml_status(self) -> str:
        return str(self.quick_view.status())

    def show(self) -> None:
        self.container.show()
        self.reposition_island()

    def reposition_island(self) -> None:
        if self.island is None:
            return
        from PySide6.QtCore import QObject
        root = self.quick_view.rootObject()
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
        self._host.close()
        self.container.close()


def _build_window(cfg: dict, panes: int, rebake_hz: float,
                  geo: tuple[int, int, int, int]):
    """Cell-config-driven window factory -- dispatches to
    :class:`NativeContainerWindow` for ``native_qml`` cells (M7), else the
    default :class:`OverlayWindow` (M0-M6). Both classes expose an identical
    method/attribute surface, so every caller (``measure_cell``,
    ``_smoke_check_cell``, ``run_hold``) is agnostic to which one it gets."""
    if cfg.get("native_qml"):
        return NativeContainerWindow(panes, rebake_hz, geo,
                                     native_island=bool(cfg.get("native_island", True)),
                                     island_hz=float(cfg.get("island_hz", ISLAND_NOMINAL_HZ)))
    return OverlayWindow(panes, rebake_hz, geo, overlay=bool(cfg.get("overlay", False)),
                        opaque_island=bool(cfg.get("opaque_island", False)),
                        opaque_qqw=bool(cfg.get("opaque_qqw", False)),
                        area_scale=float(cfg.get("area_scale", 1.0)),
                        island_hz=float(cfg.get("island_hz", ISLAND_NOMINAL_HZ)),
                        native_island=bool(cfg.get("native_island", False)))


def _needs_subprocess(cfg: dict) -> bool:
    """True if this cell must be measured in a fresh, isolated process:
    either it needs an env var Qt only reads pre-``QGuiApplication`` (M5), or
    it is flagged ``isolate`` because in-process measurement risks taking
    down the whole run (M7's reproduced offscreen teardown segfault)."""
    if cfg.get("isolate"):
        return True
    env_req = cfg.get("env")
    if env_req and not all(os.environ.get(k) == v for k, v in env_req.items()):
        return True
    return False


# --------------------------------------------------------------------------- #
# One measured cell                                                            #
# --------------------------------------------------------------------------- #

def measure_cell(cfg: dict, *, panes: int, rebake_hz: float, seconds: float,
                 warmup_s: float, geo: tuple[int, int, int, int]) -> dict:
    """Build the window per ``cfg`` (a :data:`CELLS` entry), warm up, window
    the telemetry for ``seconds``, tear down. Returns the measurement dict."""
    overlay = bool(cfg.get("overlay", False))
    entry: dict = {"errors": []}

    win = _build_window(cfg, panes, rebake_hz, geo)
    entry["qml_status"] = win.qml_status()
    entry["qml_errors"] = win.qml_errors()
    if entry["qml_errors"]:
        entry["errors"].append("QML load errors: " + "; ".join(entry["qml_errors"]))

    frames_end = {"n": 0}        # afterFrameEnd -- the FIXED qml_fps probe
    frames_swapped_raw = {"n": 0}  # frameSwapped -- informational only, expect 0
    renders = {"n": 0}            # afterRendering -- the ratified gating proxy
    qwin = win.quick_window()
    if qwin is not None:
        if hasattr(qwin, "afterFrameEnd"):
            qwin.afterFrameEnd.connect(lambda: frames_end.__setitem__("n", frames_end["n"] + 1))
        if hasattr(qwin, "frameSwapped"):
            qwin.frameSwapped.connect(
                lambda: frames_swapped_raw.__setitem__("n", frames_swapped_raw["n"] + 1))
        qwin.afterRendering.connect(lambda: renders.__setitem__("n", renders["n"] + 1))

    win.show()
    win.reposition_island()

    # warmup: shader compile, bake spin-up, feed reaching steady pace -- NOT measured
    if win.feed is not None:
        win.feed.start()
    _settle(int(warmup_s * 1000))
    win.reposition_island()

    # window the telemetry
    qml_root = win.qqw.rootObject()
    if qml_root is not None:
        qml_root.setProperty("bakeCount", 0)
    frames_end["n"] = 0
    frames_swapped_raw["n"] = 0
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
    entry["qml_fps"] = round(frames_end["n"] / wall, 2) if wall > 0 else None
    entry["qml_frameswapped_hz_raw"] = round(frames_swapped_raw["n"] / wall, 2) if wall > 0 else None
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
        # M6/M7 structural checks (harmless/near-always-0 for non-native
        # cells): did the island actually get a native surface, and does its
        # final geometry match the reserved rect (a static single-shot read
        # -- move/resize flicker still needs the operator's --hold eyeball).
        try:
            entry["island_internal_win_id_nonzero"] = bool(win.island.internalWinId())
        except Exception:  # noqa: BLE001
            entry["island_internal_win_id_nonzero"] = None
        g = win.island.geometry()
        entry["island_final_geometry"] = [g.x(), g.y(), g.width(), g.height()]
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


def pass_verdict(entry: dict, cfg: dict) -> dict:
    """Gate on ``island_feed_hz`` and ``qml_scene_render_hz`` (the ratified
    proxy). ``qml_fps`` (now fixed via afterFrameEnd) is reported but is not
    the gating field. Diagnostic cells (M3/M4) get their PASS/FAIL state
    prefixed ``DIAGNOSTIC-`` so a genuine floor-clear never reads as a real
    pass claim for a config that isn't a candidate mitigation."""
    if not cfg.get("overlay", True):
        return {"island_feed_hz": None, "island_floor": ISLAND_HZ_FLOOR,
                "scene_render_hz": entry.get("qml_scene_render_hz"),
                "scene_floor": SCENE_HZ_FLOOR, "near_floor": False, "state": "REFERENCE"}
    island = entry.get("island_feed_hz")
    scene = entry.get("qml_scene_render_hz")
    near = _near_floor(island, ISLAND_HZ_FLOOR) or _near_floor(scene, SCENE_HZ_FLOOR)
    if island is None or scene is None:
        state = "NO-DATA"
    elif near:
        state = "QUIET-RERUN-NEEDED"
    elif island >= ISLAND_HZ_FLOOR and scene >= SCENE_HZ_FLOOR:
        state = "PASS"
    else:
        state = "FAIL"
    if cfg.get("diagnostic_only") and state in ("PASS", "FAIL"):
        state = f"DIAGNOSTIC-{state}"
    return {"island_feed_hz": island, "island_floor": ISLAND_HZ_FLOOR,
            "scene_render_hz": scene, "scene_floor": SCENE_HZ_FLOOR,
            "near_floor": near, "state": state}


def storm_observation(control_entry: dict, cell_entry: dict) -> dict:
    """Repaint-storm read: this cell's QQuickWidget/scene-render rates vs the
    SAME PASS's control baseline. A storm shows as inflated rates well above
    control; the original spike's result instead showed collapse (rates far
    BELOW control), which storm_suspected correctly does not flag -- it is a
    different, worse mechanism (full recomposition cost, not an amplified
    repaint count)."""
    def ratio(a, b):
        if a is None or b in (None, 0):
            return None
        return round(a / b, 3)

    o_render = cell_entry.get("qml_scene_render_hz")
    c_render = control_entry.get("qml_scene_render_hz")
    o_paint = cell_entry.get("qquickwidget_paint_hz")
    c_paint = control_entry.get("qquickwidget_paint_hz")
    render_ratio = ratio(o_render, c_render)
    paint_ratio = ratio(o_paint, c_paint)
    suspected = bool((render_ratio is not None and render_ratio > 1.30)
                     or (paint_ratio is not None and paint_ratio > 1.50))
    return {
        "control_scene_render_hz": c_render, "cell_scene_render_hz": o_render,
        "scene_render_ratio": render_ratio,
        "control_qqw_paint_hz": c_paint, "cell_qqw_paint_hz": o_paint,
        "qqw_paint_ratio": paint_ratio,
        "storm_suspected": suspected,
    }


def compute_cell_overall(states: list[str]) -> dict:
    if any(s == "NO-DATA" for s in states):
        overall = "NO-DATA"
    elif any(s == "QUIET-RERUN-NEEDED" for s in states):
        overall = "QUIET-RERUN-NEEDED"
    elif any(s == "REFERENCE" for s in states):
        overall = "REFERENCE"
    elif all(s == "PASS" for s in states):
        overall = "PASS"
    elif all(s.startswith("DIAGNOSTIC") for s in states):
        overall = "DIAGNOSTIC-PASS" if all(s == "DIAGNOSTIC-PASS" for s in states) else "DIAGNOSTIC-FAIL"
    else:
        overall = "FAIL"
    return {"pass_states": states, "overall": overall}


def compute_matrix_overall(cell_specs: dict, overall_by_cell: dict) -> dict:
    """The matrix-level read: which mitigation cells actually cleared the bar
    in every pass -- the direct input to the U2.4 decision table."""
    passing = [cid for cid, v in overall_by_cell.items()
              if v["overall"] == "PASS" and cell_specs[cid].get("overlay")
              and not cell_specs[cid].get("diagnostic_only") and cid != "m0_overlay"]
    quiet = [cid for cid, v in overall_by_cell.items() if v["overall"] == "QUIET-RERUN-NEEDED"]
    diag_pass = [cid for cid, v in overall_by_cell.items() if v["overall"] == "DIAGNOSTIC-PASS"]
    if passing:
        verdict = "MITIGATION FOUND"
    elif quiet:
        verdict = "QUIET-RERUN-NEEDED"
    else:
        verdict = "ALL MITIGATIONS FAILED"
    return {"mitigations_passing": passing, "diagnostics_passing": diag_pass,
            "quiet_rerun_needed": quiet, "verdict": verdict}


# --------------------------------------------------------------------------- #
# Reporting                                                                     #
# --------------------------------------------------------------------------- #

def _fmt(v) -> str:
    return "n/a" if v is None else str(v)


def _print_matrix_table(report: dict) -> None:
    print("\n" + "=" * 116)
    print("ISLAND OVERLAY MITIGATION MATRIX -- VERDICT  "
          "(floors: island_feed_hz >= 28.0, qml_scene_render_hz >= 55.0)")
    print(f"  build={_fmt(report.get('windows_build'))} qt={_fmt(report.get('qt_platform'))} "
          f"pyside={_fmt(report.get('pyside'))} dpr={_fmt((report.get('screen') or {}).get('dpr'))} "
          f"panes={report.get('panes')} rebakeHz={report.get('rebake_hz')}")
    print("-" * 116)
    header = (f"  {'cell':<22}{'pass':<5}{'island_hz':<11}{'scene_hz':<10}"
              f"{'qml_fps':<9}{'qqw_paint':<11}{'cpu%':<8}{'state':<20}")
    print(header)
    for p in report["passes"]:
        for cid in report["cells_run"]:
            c = p["cells"][cid]
            m, v = c["measurement"], c["verdict"]
            print(f"  {cid:<22}{p['pass']:<5}"
                  f"{_fmt(m.get('island_feed_hz')):<11}{_fmt(m.get('qml_scene_render_hz')):<10}"
                  f"{_fmt(m.get('qml_fps')):<9}{_fmt(m.get('qquickwidget_paint_hz')):<11}"
                  f"{_fmt(m.get('process_cpu_pct_of_one_core')):<8}{v['state']:<20}")
    print("-" * 116)
    for cid in report["cells_run"]:
        ov = report["overall_by_cell"][cid]
        print(f"  {cid:<22} overall={ov['overall']:<20} pass_states={ov['pass_states']}")
    print("-" * 116)
    mo = report["overall"]
    print(f"  MATRIX VERDICT: {mo['verdict']}")
    print(f"    mitigations_passing={mo['mitigations_passing']}")
    print(f"    diagnostics_passing={mo['diagnostics_passing']}")
    print(f"    quiet_rerun_needed={mo['quiet_rerun_needed']}")
    print("=" * 116)


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

def _smoke_check_cell(cell_id: str, cfg: dict, panes: int, rebake_hz: float) -> dict:
    """Offscreen mechanics check for one cell config: construct the window
    with this cell's mitigation flags, run the synthetic feed briefly (only
    if overlay), confirm QML parses + (if overlay) the island accumulates
    points and repaints. NO fps assertions (offscreen caps rendering) --
    proves construction + wiring only."""
    result = {"cell": cell_id, "ok": False, "detail": ""}
    try:
        win = _build_window(cfg, panes, rebake_hz, _cell_geometry(0))
        qml_errs = win.qml_errors()
        if qml_errs:
            result["detail"] = "QML errors: " + "; ".join(qml_errs)
            win.close()
            return result
        win.show()
        _settle(300)
        win.reposition_island()
        detail_bits = [f"qml_status={win.qml_status()}"]
        ok = True
        if cfg.get("overlay", False):
            win.feed.start()
            _settle(700)
            win.feed.stop()
            win.island.flush_pending()
            pts = win.island.point_count()
            showing = win.island.is_showing_map()
            ticks = win.feed.ticks()
            repaints = win.scanmap_repaints()
            ok = bool(pts >= 1 and showing and ticks >= 1 and repaints >= 1)
            detail_bits.append(f"points={pts} showing={showing} ticks={ticks} repaints={repaints}")
            try:
                detail_bits.append(f"island_native={bool(win.island.internalWinId())}")
            except Exception:  # noqa: BLE001
                pass
        result["ok"] = ok
        result["detail"] = "; ".join(detail_bits)
        win.close()
        _settle(100)
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"EXCEPTION: {exc}"
    return result


def run_smoke_one(args) -> int:
    """``--smoke --measure-one CELL_ID``: the lightweight per-cell mechanics
    check invoked either directly, or re-execed as a subprocess by run_smoke()
    for env-gated cells (proving the subprocess/env/JSON plumbing, not GPU
    rate -- Qt reads env-based render knobs before QGuiApplication exists, so
    they cannot be exercised in-process)."""
    app = _bootstrap_app(smoke=True)  # noqa: F841
    cell_id = args.measure_one
    cfg = CELLS.get(cell_id)
    if cfg is None:
        print(f"unknown cell id {cell_id!r} -- valid: {_CELL_ORDER}", file=sys.stderr)
        return EXIT_ERROR
    res = _smoke_check_cell(cell_id, cfg, args.panes, args.rebake_hz)
    print(f"[measure-one smoke] {cell_id}: ok={res['ok']} detail={res['detail']}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res), encoding="utf-8")
    return EXIT_PASS if res["ok"] else EXIT_FAIL


def run_smoke(args) -> int:
    app = _bootstrap_app(smoke=True)  # noqa: F841 -- keep QApplication alive
    from PySide6.QtGui import QGuiApplication
    import PySide6

    print("ISLAND OVERLAY SPIKE -- SMOKE (offscreen mechanics; NO fps assertions)")
    print(f"  qt_platform={QGuiApplication.instance().platformName()!r} pyside={PySide6.__version__}")

    # 1. QML parse validity (authoritative -- no GL needed; shared by every cell)
    qml_errs = validate_qml()
    print(f"  [1] QML parse: {'OK (no errors)' if not qml_errs else 'ERRORS: ' + '; '.join(qml_errs)}")
    if qml_errs:
        return EXIT_ERROR

    # 2. device-import cleanliness (informational -- the grep is on the source)
    dev_mods = sorted(m for m in sys.modules
                      if m.split(".")[0] in ("controller", "devices"))
    print(f"  [2] controller/devices modules loaded: {dev_mods if dev_mods else 'NONE'}")

    # 3. every selected cell: construct + exercise mechanics. env-gated cells
    #    are exercised via a re-exec'd subprocess (proves that plumbing,
    #    since the env var itself only matters pre-QGuiApplication -- offscreen
    #    cannot demonstrate its GPU effect anyway).
    cell_ids = _resolve_cells(args.cells)
    print(f"  [3] cells selected: {cell_ids}")
    all_ok = True
    for cid in cell_ids:
        cfg = CELLS[cid]
        env_req = cfg.get("env")
        if _needs_subprocess(cfg):
            tmp = Path(tempfile.gettempdir()) / f"tct_spike_smoke_{cid}.json"
            if tmp.exists():
                tmp.unlink()
            env = dict(os.environ)
            if env_req:
                env.update(env_req)
            cmd = [sys.executable, str(Path(__file__).resolve()), "--smoke",
                  "--measure-one", cid, "--panes", str(args.panes),
                  "--rebake-hz", str(args.rebake_hz), "--json-out", str(tmp)]
            try:
                proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
                detail = f"subprocess rc={proc.returncode}"
                if tmp.exists():
                    # The JSON file is written BEFORE any crash-prone teardown
                    # code runs (m7_native_qml: confirmed segfault is always
                    # the LAST thing that happens, after cleanup already
                    # printed) -- so a written ok=True result is trusted even
                    # if the subprocess then exits abnormally.
                    payload = json.loads(tmp.read_text(encoding="utf-8"))
                    ok = bool(payload.get("ok"))
                    detail += f" payload_ok={payload.get('ok')} detail={payload.get('detail')}"
                    if proc.returncode != EXIT_PASS:
                        detail += (" (NOTE: subprocess exited abnormally AFTER writing this "
                                  "result -- known teardown hazard for isolate=True cells, "
                                  "not a mechanics failure; see module docstring)")
                else:
                    ok = False
                    detail += " (no JSON produced -- crashed before the result could be written)"
            except subprocess.TimeoutExpired:
                ok = False
                detail = "subprocess TIMEOUT"
            except Exception as exc:  # noqa: BLE001
                ok = False
                detail = f"subprocess EXCEPTION: {exc}"
            kind = "env-reexec" if env_req else "isolated"
            print(f"  [{cid}] {kind} smoke (env={env_req}, isolate={cfg.get('isolate', False)}): "
                  f"{'OK' if ok else 'FAIL'} -- {detail}")
        else:
            res = _smoke_check_cell(cid, cfg, args.panes, args.rebake_hz)
            ok = res["ok"]
            print(f"  [{cid}] in-process smoke: {'OK' if ok else 'FAIL'} -- {res['detail']}")
        all_ok = all_ok and ok

    print(f"\n  SMOKE {'PASS' if all_ok else 'FAIL'} -- "
          f"{'every selected cell constructed and its wiring fired' if all_ok else 'a cell mechanic did not fire'}")
    print("  (GPU rate numbers require the windowed operator run -- offscreen "
          "caps rendering; see module docstring RUN.)")
    return EXIT_PASS if all_ok else EXIT_FAIL


# --------------------------------------------------------------------------- #
# The real windowed measurement -- single cell (used directly, and as the      #
# env-reexec subprocess target for env-gated cells)                            #
# --------------------------------------------------------------------------- #

def run_measure_one(args) -> int:
    app = _bootstrap_app(smoke=False)
    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return EXIT_GUARD
    cell_id = args.measure_one
    cfg = CELLS.get(cell_id)
    if cfg is None:
        print(f"unknown cell id {cell_id!r} -- valid: {_CELL_ORDER}", file=sys.stderr)
        return EXIT_ERROR
    entry = measure_cell(cfg, panes=args.panes, rebake_hz=args.rebake_hz,
                         seconds=args.seconds, warmup_s=args.warmup, geo=_cell_geometry(0))
    payload = {"cell": cell_id, "measurement": entry}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload), encoding="utf-8")
    print(f"[measure-one] {cell_id}: {json.dumps(entry)}")
    return EXIT_PASS


def _measure_cell_dispatch(cell_id: str, cfg: dict, args, geo) -> dict:
    """Measure one cell for the real matrix: in-process directly, or (for
    ``env``-gated or ``isolate``-flagged cells) via a re-exec'd subprocess so
    the env var is read before that process's own QGuiApplication exists (M5)
    or a known in-process hazard cannot take down the rest of the matrix (M7).
    The JSON result file is trusted over the subprocess exit code -- it is
    written before any crash-prone teardown code runs."""
    if not _needs_subprocess(cfg):
        return measure_cell(cfg, panes=args.panes, rebake_hz=args.rebake_hz,
                            seconds=args.seconds, warmup_s=args.warmup, geo=geo)

    env_req = cfg.get("env")
    tmp = Path(tempfile.gettempdir()) / f"tct_spike_measure_{cell_id}_{os.getpid()}.json"
    if tmp.exists():
        tmp.unlink()
    env = dict(os.environ)
    if env_req:
        env.update(env_req)
    cmd = [sys.executable, str(Path(__file__).resolve()), "--measure-one", cell_id,
          "--seconds", str(args.seconds), "--warmup", str(args.warmup),
          "--panes", str(args.panes), "--rebake-hz", str(args.rebake_hz),
          "--json-out", str(tmp)]
    timeout_s = args.warmup + args.seconds + 60.0
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_s)
        if not tmp.exists():
            return {"errors": [f"subprocess produced no JSON rc={proc.returncode} "
                               f"stderr={proc.stderr[-500:]}"]}
        payload = json.loads(tmp.read_text(encoding="utf-8"))
        measurement = payload.get("measurement", {"errors": ["no measurement in subprocess JSON"]})
        if proc.returncode != EXIT_PASS:
            measurement.setdefault("errors", []).append(
                f"NOTE: subprocess exited abnormally (rc={proc.returncode}) AFTER writing "
                "this measurement -- known teardown hazard for isolate=True cells (see "
                "module docstring); the measurement itself is still trusted.")
        return measurement
    except subprocess.TimeoutExpired:
        return {"errors": ["subprocess TIMEOUT"]}
    except Exception as exc:  # noqa: BLE001
        return {"errors": [f"subprocess EXCEPTION: {exc}"]}


def run_measurement(args) -> int:
    app = _bootstrap_app(smoke=False)
    from PySide6.QtGui import QGuiApplication
    import PySide6

    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return EXIT_GUARD

    cell_ids = _resolve_cells(args.cells)
    # m0_control is always measured (it is this pass's storm baseline for
    # every other cell) but only listed once, first, in the printed table.
    cells_run = (["m0_control"] if "m0_control" not in cell_ids else []) + cell_ids

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _REPO_ROOT / "artifacts_claude" / f"island_overlay_spike_matrix_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry() if screen else None
    report: dict = {
        "spike": "island_overlay_spike_matrix",
        "utc": ts,
        "windows_build": (sys.getwindowsversion().build      # type: ignore[attr-defined]
                          if hasattr(sys, "getwindowsversion") else None),
        "qt_platform": app.platformName(),
        "pyside": PySide6.__version__,
        "panes": args.panes,
        "rebake_hz": args.rebake_hz,
        "params": {"seconds": args.seconds, "warmup_s": args.warmup,
                   "island_nominal_hz": ISLAND_NOMINAL_HZ, "blur_max_px": BLUR_MAX_PX,
                   "n_passes": args.passes},
        "thresholds": {"island_hz_floor": ISLAND_HZ_FLOOR, "scene_hz_floor": SCENE_HZ_FLOOR,
                       "near_floor_frac": NEAR_FLOOR_FRAC},
        "screen": {"dip": [avail.width(), avail.height()] if avail else None,
                   "dpr": screen.devicePixelRatio() if screen else None},
        "out_dir": str(out_dir),
        "cell_specs": {cid: {k: v for k, v in CELLS[cid].items()} for cid in cells_run},
        "cells_run": cells_run,
        "passes": [],
    }

    print(f"\nISLAND OVERLAY MITIGATION MATRIX -- {args.seconds:.0f}s window/cell, "
          f"{args.passes} pass(es), cells={cells_run}")
    states_by_cell: dict[str, list[str]] = {cid: [] for cid in cells_run}
    for p in range(1, args.passes + 1):
        print(f"\n--- pass {p} ---")
        control_entry = measure_cell(CELLS["m0_control"], panes=args.panes, rebake_hz=args.rebake_hz,
                                     seconds=args.seconds, warmup_s=args.warmup, geo=_cell_geometry(0))
        print(f"    m0_control: scene_render_hz={control_entry.get('qml_scene_render_hz')} "
              f"qml_fps={control_entry.get('qml_fps')} cpu%={control_entry.get('process_cpu_pct_of_one_core')}")

        pass_cells: dict = {}
        v_control = pass_verdict(control_entry, CELLS["m0_control"])
        pass_cells["m0_control"] = {
            "measurement": control_entry, "verdict": v_control,
            "storm": storm_observation(control_entry, control_entry),
        }
        states_by_cell["m0_control"].append(v_control["state"])

        for cid in cell_ids:
            if cid == "m0_control":
                continue
            cfg = CELLS[cid]
            sys.stdout.flush()
            entry = _measure_cell_dispatch(cid, cfg, args, _cell_geometry(1))
            verdict = pass_verdict(entry, cfg)
            storm = storm_observation(control_entry, entry)
            pass_cells[cid] = {"measurement": entry, "verdict": verdict, "storm": storm}
            states_by_cell[cid].append(verdict["state"])
            print(f"    {cid}: island_feed_hz={entry.get('island_feed_hz')} "
                  f"scene_render_hz={entry.get('qml_scene_render_hz')} "
                  f"qml_fps={entry.get('qml_fps')} cpu%={entry.get('process_cpu_pct_of_one_core')} "
                  f"-> {verdict['state']}")

        report["passes"].append({"pass": p, "cells": pass_cells})

    overall_by_cell = {cid: compute_cell_overall(states_by_cell[cid]) for cid in cells_run}
    report["overall_by_cell"] = overall_by_cell
    report["overall"] = compute_matrix_overall(report["cell_specs"], overall_by_cell)
    write_artifacts(report, out_dir)
    _print_matrix_table(report)
    print(f"\nartifacts: {out_dir}\n")

    verdict = report["overall"]["verdict"]
    if verdict == "MITIGATION FOUND":
        return EXIT_PASS
    if verdict == "QUIET-RERUN-NEEDED":
        return EXIT_QUIET
    return EXIT_FAIL


def run_hold(args) -> int:
    """Eyeball mode: leave a cell's scene + live synthetic feed on screen for
    ``--hold`` seconds. Defaults to the original ``m0_overlay`` cell;
    ``--hold-cell m6_native_island`` / ``m7_native_qml`` is the operator's
    tool for the flicker/z-order/geometry-drift-on-move-resize checks this
    protocol's own static single-shot measurement cannot perform."""
    app = _bootstrap_app(smoke=False)
    reason = _check_real_session()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return EXIT_GUARD
    cfg = CELLS.get(args.hold_cell)
    if cfg is None:
        print(f"unknown cell id {args.hold_cell!r} -- valid: {_CELL_ORDER}", file=sys.stderr)
        return EXIT_ERROR
    from PySide6.QtCore import QTimer
    win = _build_window(cfg, args.panes, args.rebake_hz, _cell_geometry())
    errs = win.qml_errors()
    if errs:
        print("QML ERRORS:", errs, file=sys.stderr)
    win.show()
    win.reposition_island()
    if win.feed is not None:
        win.feed.start()
    print(f"holding cell={args.hold_cell!r} ({cfg.get('label')}) for {args.hold}s -- watch the "
          "island for stalls/flicker/z-order/geometry drift on move/resize "
          "(M6/M7: try dragging or resizing the window).")
    sys.stdout.flush()
    QTimer.singleShot(args.hold * 1000, app.quit)
    app.exec()
    win.close()
    return EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="U2.4 island-overlay mitigation matrix.")
    ap.add_argument("--smoke", action="store_true",
                    help="headless mechanics check (offscreen; no fps assertions)")
    ap.add_argument("--cells", type=str, default="all",
                    help=f"comma list of cell ids or 'all'. valid: {_CELL_ORDER}")
    ap.add_argument("--passes", type=int, default=DEFAULT_PASSES,
                    help="measurement passes per cell (default 2)")
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help="window per cell")
    ap.add_argument("--warmup", type=float, default=DEFAULT_WARMUP_S)
    ap.add_argument("--panes", type=int, default=DEFAULT_PANES)
    ap.add_argument("--rebake-hz", type=float, default=DEFAULT_REBAKE_HZ)
    ap.add_argument("--hold", type=int, default=0, help="eyeball: leave a cell's scene on screen N s")
    ap.add_argument("--hold-cell", type=str, default="m0_overlay",
                    help="cell id to hold for --hold seconds (default m0_overlay)")
    ap.add_argument("--watchdog", type=float, default=0.0,
                    help="hard out-of-process kill after N s (0 = auto)")
    # internal-only flags used for the env-reexec single-cell subprocess path
    ap.add_argument("--measure-one", type=str, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--json-out", type=str, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if not args.measure_one:
        try:
            _resolve_cells(args.cells)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_ERROR

    if args.hold > 0:
        wd_timeout = args.hold + 60.0
    elif args.measure_one:
        wd_timeout = args.warmup + args.seconds + 60.0
    elif args.smoke:
        wd_timeout = 60.0 + 20.0 * len(_resolve_cells(args.cells))
    else:
        n_other = len([c for c in _resolve_cells(args.cells) if c != "m0_control"])
        total_per_pass = 1 + n_other
        wd_timeout = args.passes * total_per_pass * (args.warmup + args.seconds + 15.0) + 150.0
    if args.watchdog > 0:
        wd_timeout = args.watchdog
    watchdog = _spawn_hard_watchdog(os.getpid(), wd_timeout)

    try:
        if args.measure_one and args.smoke:
            return run_smoke_one(args)
        if args.measure_one:
            return run_measure_one(args)
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
