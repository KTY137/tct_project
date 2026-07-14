"""SPIKE — is the `ShaderEffect`/`MultiEffect` ban EARNED, or does live glass work?

THE CLAIM UNDER TEST
--------------------
``docs/design/glass_council/SYNTHESIS.md`` §2.2.2/§6 (G2 row) bans live
``MultiEffect``/``ShaderEffect`` glass from the QML kit, enforced by an
object-tree-walk gate (Tyr §4(c)). Two premises were offered for it, and BOTH
are now suspect:

1. **Path-D** ("a render-to-texture child kills the window's DWM material") —
   REFUTED by measurement on 2026-07-14 (``scripts/spikes/gl_island_glass_spike.py``
   finding 1, commit 353072f). A live ``QOpenGLWidget`` child kept the material.
   A ``MultiEffect`` *is* an RTT construct (it renders its source into a texture
   and re-composites it), so if path-D is dead, the "an effect kills the glass"
   half of the ban is dead with it — unless it reproduces for THIS construct,
   which is what M1 below asks.
2. **The ~50 % segfault** from the same spike was a **pure-Python scene-graph
   item** (``QQuickItem.updatePaintNode`` + ``QSGGeometryNode`` built in Python).
   ``MultiEffect`` is a built-in C++ QML type with **zero Python scene-graph
   code**, so that finding says nothing about it. M4 below asks it directly.

If both premises are inapplicable, the ban was never earned — and Qt's own live
blur is on the table, which is a different program (real glass over a LIVE plot,
not a baked frost texture that only works against a static backdrop).

WHAT THIS BUILDS
----------------
A translucent ``QQuickWindow`` (``QQuickView``) on the **OpenGL RHI** — measured
2026-07-14: a QQuickWindow-root shell renders flat WHITE on D3D11 and real glass
on OpenGL on this stack, so OpenGL is the only RHI where the question is even
askable — with a DWM material attached through ``gui/backdrop.py``'s own HWND-level
primitives (imported, never forked), and a **loud striped decoy pinned behind it**
(magenta/cyan, 28 px period — a blur is only measurable if there are sharp edges
to smear).

The scene is the same in every configuration; only the effect elements change:

  * ``holeA``  — an ALPHA HOLE (the scene paints NOTHING): what shows here is the
    DWM material compositing the decoy BEHIND the window. A frost pane over it,
    sourced from the scene's own layer, is the "backdrop-filter" attempt.
  * ``holeB``  — a second alpha hole, frosted from a **recursive**
    ``ShaderEffectSource`` of the whole root — the strongest attempt available
    in Qt Quick at sampling "everything that is behind this pane".
  * ``scenePanel`` — IN-SCENE striped content (same stripe pattern as the decoy,
    so the SAME edge-energy metric measures both), half of it under a frost pane
    and half left crisp as the reference. A ``mover`` element crosses the frosted
    half at ~15 Hz: live content under live glass.
  * ``margin`` — a band no effect ever covers: the M1 material probe.

CONFIGURATIONS (``--config``)
  ``control``   — no effect elements at all. Baseline.
  ``multieffect`` — ``MultiEffect`` (Qt 6 built-in) frost panes.
  ``ses``       — ``ShaderEffectSource`` + ``Qt5Compat.GraphicalEffects.FastBlur``
                  (the older primitive) — the second opinion.
  ``live``      — ``MultiEffect`` + a moving element behind the frosted panel AND
                  an animated decoy behind the window: the case a baked frost
                  texture physically cannot do.

MEASUREMENT (two independent capture methods, which must agree)
---------------------------------------------------------------
Every probe rect is grabbed with BOTH ``QScreen.grabWindow`` and a GDI ``BitBlt``
of the screen DC (both reused verbatim from ``scripts/capture_onscreen.py``), with
a 1 px move-nudge + a throwaway warm-up grab before each read, and every rect is
computed from LIVE geometry (a hard-coded rect is how the earlier harness ended up
measuring off-screen black and calling it "INCONCLUSIVE").

  M1  material survival — margin ``d_toggle`` (material on vs off) and
      ``d_behind`` (decoy striped vs flat, z-order untouched), per config. A
      window whose margin still tracks what is behind it has a live material.
  M2  **the decisive one** — does the blur smear what is behind the WINDOW, or
      only what is inside the QML scene?
        M2a  behind-window: ``delta(control.holeX, cfg.holeX)`` and the edge
             energy of holeX. If a frost pane over an alpha hole is
             pixel-identical to no frost pane at all, Qt cannot see the backdrop.
        M2b  in-scene: ``edge(frosted half) / edge(crisp half)`` of the scene
             panel. ``<< 1`` means the blur is real — inside the scene.
  M3  fps (``frameSwapped``), process CPU % (``GetProcessTimes``), and the GUI
      heartbeat gap (max lateness of a 16 ms QTimer) with the 15 Hz element live.
  M4  stability — ``--stability N`` re-launches each config as its own PROCESS N
      times and counts crashes (a Windows access violation exits 0xC0000005).
  M5  survival of resize, minimize→restore, and (if a second screen exists) a
      monitor move — margin re-measured after each, incl. an explicit white-frame
      check (``mean_rgb`` near 255,255,255 = the sticky white plate).

RUN (real desktop session only — refuses under offscreen/minimal)
-----------------------------------------------------------------
::

    cd TCT_app
    .venv/Scripts/python.exe scripts/spikes/qml_multieffect_glass_spike.py --all
    .venv/Scripts/python.exe scripts/spikes/qml_multieffect_glass_spike.py --stability 20
    .venv/Scripts/python.exe scripts/spikes/qml_multieffect_glass_spike.py --config live --hold 60

NOT app code. NOT imported by the app. NOT part of the test suite. No hardware, no
DeviceManager, no QSettings, no real plots — every motion here is simulated.
Single host = Intel UHD iGPU: a one-host result is a signal, not a universal law.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_SPIKES = Path(__file__).resolve().parent
_SCRIPTS = _SPIKES.parent
_TCT_APP = _SCRIPTS.parent
_REPO_ROOT = _TCT_APP.parent
for _p in (str(_TCT_APP), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage,  # noqa: E402
                           QPainter, QSurfaceFormat)
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import capture_onscreen as cap  # noqa: E402
from gui import backdrop  # noqa: E402  (the DWM chain — imported, never forked)

CONFIGS = ("control", "multieffect", "ses", "live")

# mean-abs-channel-delta thresholds (0..255), same scale as the GL-island spike
T_CHANGED = 6.0
T_UNCHANGED = 2.0

PROBE_FROM_BOTTOM = 74
PROBE_H = 44
PROBE_INSET_X = 24
DECOY_INFLATE = 14
PANE_INSET = 16


# --------------------------------------------------------------------------- #
# The decoy — the content BEHIND the window                                    #
# --------------------------------------------------------------------------- #

class Decoy(QWidget):
    """Frameless opaque window pinned behind the spike window.

    ``stripes`` (loud magenta/cyan, 28 px period — high-frequency, so a blur is
    measurable), ``flat`` (near-black), and ``live`` (the stripes scrolling at
    ~15 Hz — the moving backdrop the "live glass" question is actually about).
    Pattern changes never touch z-order: a hide()/show() would re-raise the decoy
    above the glass window and invalidate every measurement.
    """

    def __init__(self) -> None:
        super().__init__(None)
        # STAYS-ON-TOP is not cosmetic here, it is the fix for a measurement bug
        # that produced a completely false "backdrop blur" reading: the first
        # config's M5 showMinimized() let the TERMINAL window rise BETWEEN the
        # decoy and the spike window, so every later config was measuring DWM
        # blurring VS Code instead of the stripes. Both the decoy and the shell are
        # topmost, and the z-order between them is re-asserted before every grab
        # (see _restack) — the only two windows in the stack we control.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.pattern = "stripes"
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_pattern(self, pattern: str) -> None:
        self.pattern = pattern
        if pattern == "live":
            self._timer.start(66)          # ~15 Hz
        else:
            self._timer.stop()
            self._phase = 0
        self.update()
        self.repaint()

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 120
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        if self.pattern == "flat":
            p.fillRect(self.rect(), QColor("#0B0B10"))
            return
        p.fillRect(self.rect(), QColor("#FF00AA"))
        p.setBrush(QBrush(QColor("#00E5FF")))
        p.setPen(Qt.PenStyle.NoPen)
        for x in range(0, self.width(), 28):
            p.drawRect(x, 0, 14, self.height())
        if self.pattern != "live":
            return
        # A BIG moving blob, not just scrolling stripes. Scrolling a PERIODIC
        # pattern is invisible to a blur: acrylic's kernel is far wider than the
        # 28 px period, so every phase blurs to the same colour and the measured
        # temporal delta was exactly 0.00 — which reads as "DWM does not track live
        # content" when it actually means "this decoy cannot be tracked". A wide
        # bright block changes the LOCAL MEAN, which is precisely what survives a
        # blur.
        span = max(1, self.width() - 240)
        t = self._phase / 120.0
        x = int(abs(2.0 * t - 1.0) * span)          # ping-pong, ~4 s per sweep
        p.setBrush(QBrush(QColor("#FFE066")))
        p.drawRect(x, 0, 240, self.height())


# --------------------------------------------------------------------------- #
# The QML scene — identical in every config; only the effect elements differ   #
# --------------------------------------------------------------------------- #

_QML = """
import QtQuick
import QtQuick.Effects
import Qt5Compat.GraphicalEffects

Item {
    id: root

    // Injected from Python: "control" | "multieffect" | "ses" | "live"
    property string mode: "control"
    property bool motionEnabled: true
    readonly property bool meOn:  mode === "multieffect" || mode === "live"
    readonly property bool sesOn: mode === "ses"
    readonly property bool anyEffect: meOn || sesOn

    // NO background rectangle anywhere outside scenePanel: the root stays
    // transparent, so the DWM material behind the QQuickWindow is what fills the
    // holes and the margin. That transparency IS the experiment.

    // ---- the scene's own content ------------------------------------------
    // layer.enabled makes this Item a texture provider (an RTT inside the scene
    // graph) WITHOUT hiding it — that is what the frost panes sample. It is also,
    // by itself, a path-D probe: an in-scene FBO under a DWM material.
    Item {
        id: contentLayer
        anchors.fill: parent
        layer.enabled: root.anyEffect

        Text {
            x: 24; y: 20; color: "#E6E9EF"; font.pixelSize: 13; font.bold: true
            text: "qml_multieffect_glass_spike — mode: " + root.mode
        }

        // The IN-SCENE striped panel: same pattern as the decoy behind the
        // window, so ONE edge-energy metric measures both sides of the question.
        Rectangle {
            id: scenePanel
            objectName: "scenePanel"
            x: root.width * 0.50
            y: 60
            width: root.width * 0.46
            height: 300
            color: "#FF00AA"
            clip: true

            Row {
                spacing: 14
                Repeater {
                    model: Math.ceil(scenePanel.width / 28) + 1
                    Rectangle { width: 14; height: scenePanel.height; color: "#00E5FF" }
                }
            }

            // THE LIVE ELEMENT (~15 Hz of visible motion): it crosses UNDER the
            // frosted half. A baked frost texture physically cannot blur this.
            Rectangle {
                objectName: "mover"
                width: 48; height: 48; radius: 6
                color: "#101820"
                border.color: "#FFD166"; border.width: 3
                y: scenePanel.height * 0.62
                x: 8
                SequentialAnimation on x {
                    running: root.motionEnabled
                    loops: Animation.Infinite
                    NumberAnimation { from: 8; to: scenePanel.width - 56; duration: 1500 }
                    NumberAnimation { from: scenePanel.width - 56; to: 8; duration: 1500 }
                }
            }
        }
    }

    // A RECURSIVE snapshot of the WHOLE root — the strongest thing Qt Quick can
    // offer a pane that wants to blur "everything behind me". If even this cannot
    // see the desktop through the window's alpha, nothing in QML can.
    ShaderEffectSource {
        id: rootSource
        anchors.fill: parent
        sourceItem: root
        recursive: true
        live: true
        hideSource: false
        visible: false
    }

    // ---- the frost panes ---------------------------------------------------
    // The standard QML "backdrop blur" recipe: blur a full-scene copy, clip it to
    // the pane's rect, and offset it so it lines up. It is a REAL backdrop filter
    // for anything the scene texture contains — the question is whether the scene
    // texture contains what is behind the WINDOW.
    component FrostPane: Item {
        id: pane
        property Item src: null
        property bool useSes: false
        clip: true

        MultiEffect {
            visible: !pane.useSes
            source: pane.src
            x: -pane.x; y: -pane.y
            width: root.width; height: root.height
            blurEnabled: true
            blur: 1.0
            blurMax: 64
            blurMultiplier: 1.2
            autoPaddingEnabled: false
        }
        FastBlur {
            visible: pane.useSes
            source: pane.src
            x: -pane.x; y: -pane.y
            width: root.width; height: root.height
            radius: 56
        }
        // NO TINT FILL, deliberately. A real GlassPane would carry one — but a
        // white tint over an alpha hole changes those pixels all by itself, and
        // then the M2a cross-config delta would measure THE TINT and be read as
        // "the effect blurred the backdrop". The probe rect is inset past this
        // hairline, so every number below is BLUR ONLY.
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.color: "#66FFFFFF"
            border.width: 1
            radius: 10
        }
    }

    // holeA — ALPHA HOLE (scene paints nothing here). Frosted from the scene's
    // own layer: the honest "backdrop-filter" attempt.
    FrostPane {
        objectName: "frostA"
        visible: root.anyEffect
        src: contentLayer
        useSes: root.sesOn
        x: 24; y: 62
        width: root.width * 0.21; height: 210
    }

    // holeB — ALPHA HOLE, frosted from the RECURSIVE root snapshot.
    FrostPane {
        objectName: "frostB"
        visible: root.anyEffect
        src: rootSource
        useSes: root.sesOn
        x: 24 + root.width * 0.23; y: 62
        width: root.width * 0.21; height: 210
    }

    // frostS — over the RIGHT HALF of the in-scene striped panel. The left half
    // stays crisp: same content, same pixels, one is frosted and one is not.
    FrostPane {
        objectName: "frostS"
        visible: root.anyEffect
        src: contentLayer
        useSes: root.sesOn
        x: scenePanel.x + scenePanel.width * 0.50
        y: scenePanel.y
        width: scenePanel.width * 0.50
        height: scenePanel.height
    }

    // Geometry beacons for Python: invisible items whose rects the measurement
    // reads back, so probe rects are never hard-coded.
    Item { objectName: "holeA"; x: 24; y: 62; width: root.width * 0.21; height: 210 }
    Item { objectName: "holeB"; x: 24 + root.width * 0.23; y: 62
           width: root.width * 0.21; height: 210 }
    Item { objectName: "sceneCrisp"; x: scenePanel.x; y: scenePanel.y
           width: scenePanel.width * 0.50; height: scenePanel.height }
    Item { objectName: "sceneFrost"; x: scenePanel.x + scenePanel.width * 0.50
           y: scenePanel.y; width: scenePanel.width * 0.50; height: scenePanel.height }
    Item { objectName: "moverBand"; x: scenePanel.x + scenePanel.width * 0.50
           y: scenePanel.y + scenePanel.height * 0.58
           width: scenePanel.width * 0.50; height: 64 }
}
"""


# --------------------------------------------------------------------------- #
# Process CPU (no psutil in this venv — and a spike may not install one)       #
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

    The argtypes/restype above are load-bearing, not decoration: without them
    ctypes marshals the 64-bit pseudo-handle through a 32-bit ``c_int``, the call
    fails, and this silently returns ``nan`` for every CPU number in the report.
    (It did, on the first run of this spike.)"""
    creation, exit_t, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
    ok = _K32.GetProcessTimes(_K32.GetCurrentProcess(), ctypes.byref(creation),
                              ctypes.byref(exit_t), ctypes.byref(kernel),
                              ctypes.byref(user))
    if not ok:
        return float("nan")

    def _s(ft: _FILETIME) -> float:
        return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7

    return _s(kernel) + _s(user)


class Heartbeat:
    """A 16 ms QTimer that records how LATE it fires — the GUI-responsiveness
    number the synthesis budgets (< 100 ms gap). A blocked/starved event loop
    shows up here and nowhere else."""

    def __init__(self) -> None:
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._last = 0.0
        self.max_gap_ms = 0.0
        self.ticks = 0

    def start(self) -> None:
        self.max_gap_ms = 0.0
        self.ticks = 0
        self._last = time.perf_counter()
        self._timer.start(16)

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        now = time.perf_counter()
        gap = (now - self._last) * 1000.0
        self._last = now
        self.ticks += 1
        if gap > self.max_gap_ms:
            self.max_gap_ms = gap


# --------------------------------------------------------------------------- #
# Pixel metrics (identical to the GL-island spike's, so the two are comparable) #
# --------------------------------------------------------------------------- #

def _to_array(img) -> np.ndarray:
    if hasattr(img, "toImage"):
        img = img.toImage()
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    h, w = img.height(), img.width()
    raw = bytes(img.constBits())
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w, :3]
    return arr.astype(np.float32)  # BGR


def _delta(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None or a.shape != b.shape:
        return float("nan")
    return float(np.abs(a - b).mean())


def _edge_energy(a: np.ndarray) -> float:
    """Mean horizontal gradient. The stripes (decoy AND in-scene panel) are
    vertical, so a crisp view scores high and a blurred view scores low. This one
    number is what "did anything actually smear" means here."""
    if a is None or a.shape[1] < 2:
        return 0.0
    return float(np.abs(np.diff(a, axis=1)).mean())


def _mean_rgb(a: np.ndarray) -> list[float]:
    m = a.reshape(-1, 3).mean(axis=0)
    return [round(float(m[2]), 1), round(float(m[1]), 1), round(float(m[0]), 1)]


def _is_white_plate(a: np.ndarray) -> bool:
    """The sticky-white-frame failure: a flat near-255 plate with no structure."""
    r, g, b = _mean_rgb(a)
    return min(r, g, b) > 235.0 and _edge_energy(a) < 2.0


def _save_arr(a: np.ndarray, path: Path) -> None:
    h, w, _ = a.shape
    rgb = np.ascontiguousarray(
        np.dstack([a[:, :, 2], a[:, :, 1], a[:, :, 0]]).astype(np.uint8))
    QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy().save(str(path))


# --------------------------------------------------------------------------- #
# The shell                                                                    #
# --------------------------------------------------------------------------- #

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_NOREDIRECTIONBITMAP = 0x00200000


def ex_style_flags(hwnd: int) -> dict:
    ex = ctypes.windll.user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    return {"raw": f"0x{ex & 0xFFFFFFFF:08X}",
            "WS_EX_LAYERED": bool(ex & WS_EX_LAYERED),
            "WS_EX_NOREDIRECTIONBITMAP": bool(ex & WS_EX_NOREDIRECTIONBITMAP)}


class Shell:
    """A translucent ``QQuickView`` top-level with a DWM material.

    ``gui/backdrop.py::apply_backdrop`` takes a ``QWidget`` (it calls
    ``QWidget.windowHandle()``), so it cannot be pointed at a ``QQuickWindow``
    as-is; this calls the module's HWND-level primitives directly — the same DWM
    calls, in the same ratified order. Reuse, not a fork.
    """

    def __init__(self, mode: str, x: int, y: int, w: int, h: int) -> None:
        from PySide6.QtQuick import QQuickView, QQuickWindow

        QQuickWindow.setDefaultAlphaBuffer(True)   # BEFORE the window exists

        tmp = Path(tempfile.gettempdir()) / "tct_qml_multieffect_spike.qml"
        tmp.write_text(_QML, encoding="utf-8")

        self.mode = mode
        self.view = QQuickView()
        self.view.setTitle(f"qml_multieffect_glass_spike — {mode}")
        # Topmost, set BEFORE the HWND exists (a setFlags() after creation is one
        # of the documented HWND-recreation paths — Fenrir K9 — and would drop the
        # DWM attributes we are trying to measure). See Decoy's comment for why.
        self.view.setFlags(self.view.flags() | Qt.WindowType.WindowStaysOnTopHint)
        self.view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.view.setColor(QColor(0, 0, 0, 0))     # transparent scene clear
        self.view.setGeometry(x, y, w, h)
        self.view.setInitialProperties({"mode": mode})
        self.view.setSource(QUrl.fromLocalFile(str(tmp)))
        self.errors = [str(e) for e in self.view.errors()]

        self.frames = 0
        self.view.frameSwapped.connect(self._on_frame)

        # Show FIRST, attach the material after the scene graph is up (the
        # GL-island spike found attaching to a not-yet-shown QQuickWindow crashes
        # the D3D backend intermittently). A QQuickWindow does not need the
        # attach-before-create dance a QWidget does: its alpha comes from
        # setDefaultAlphaBuffer + the transparent scene clear, not from a widget
        # attribute.
        self.view.show()
        cap._settle(300)
        self.hwnd = int(self.view.winId())
        self.material_hr = self.apply_material("acrylic")

    def _on_frame(self) -> None:
        self.frames += 1

    def apply_material(self, kind: str) -> dict:
        sbt = {"acrylic": backdrop.DWMSBT_TRANSIENTWINDOW,
               "mica": backdrop.DWMSBT_MAINWINDOW,
               "none": backdrop.DWMSBT_NONE}[kind]
        hr_dark = backdrop._dwm_set_window_attribute(
            self.hwnd, backdrop.DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
        hr_frame = backdrop._dwm_extend_frame(self.hwnd)
        hr_attr = backdrop._dwm_set_window_attribute(
            self.hwnd, backdrop.DWMWA_SYSTEMBACKDROP_TYPE, sbt)
        self.view.setColor(QColor(0, 0, 0, 0) if kind != "none" else QColor("#1E2026"))
        return {"kind": kind, "hr_dark": hr_dark, "hr_extend_frame": hr_frame,
                "hr_backdrop_attr": hr_attr}

    def graphics(self) -> dict:
        from PySide6.QtQuick import QQuickWindow
        try:
            api = QQuickWindow.graphicsApi()
            name = api.name if hasattr(api, "name") else str(api)
        except Exception as exc:
            name = f"ERR {exc}"
        fmt = self.view.format()
        return {"graphicsApi": name,
                "surface_alpha": fmt.alphaBufferSize(),
                "scene_color_alpha": self.view.color().alpha(),
                "ex_style": ex_style_flags(self.hwnd)}

    def set_motion(self, on: bool) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("motionEnabled", on)

    def item_rect(self, object_name: str) -> QRect | None:
        from PySide6.QtQuick import QQuickItem
        root = self.view.rootObject()
        if root is None:
            return None
        it = root.findChild(QQuickItem, object_name)
        if it is None:
            return None
        scene = it.mapToScene(it.boundingRect().topLeft())
        tl = self.view.mapToGlobal(QPoint(int(scene.x()), int(scene.y())))
        return QRect(tl.x(), tl.y(), int(it.width()), int(it.height()))

    def margin_rect(self) -> QRect:
        g = self.view.geometry()
        top = g.height() - PROBE_FROM_BOTTOM
        tl = self.view.mapToGlobal(QPoint(PROBE_INSET_X, top))
        return QRect(tl.x(), tl.y(), g.width() - 2 * PROBE_INSET_X, PROBE_H)

    def nudge(self) -> None:
        """1 px move and back — the documented heal for the Qt 6.10/6.11 + Win11
        stale-surface bug. ``update()`` is not enough; without a REAL geometry
        change the same command yields different pixels run to run."""
        g = self.view.geometry()
        self.view.setX(g.x() + 1)
        cap._settle(40)
        self.view.setX(g.x())
        cap._settle(80)

    def fps_over(self, ms: int) -> float:
        self.frames = 0
        cap._settle(ms)
        return round(self.frames * 1000.0 / ms, 1)

    def close(self) -> None:
        try:
            self.apply_material("none")
        except Exception:
            pass
        self.view.close()


# --------------------------------------------------------------------------- #
# Grabbing                                                                     #
# --------------------------------------------------------------------------- #

METHODS = ("grabwindow", "bitblt")


def _grab_rect(screen, r: QRect) -> dict[str, np.ndarray]:
    """Grab one rect with BOTH methods, throwing the first read away.

    A DWM material recomposites asynchronously after the content behind it
    changes, and the scene is repainting — the very first read after a state
    change can catch a stale composite. (The first version of the GL-island spike
    did exactly that and produced two capture methods disagreeing about the same
    window.)"""
    if r is None:
        return {m: None for m in METHODS}
    for m in METHODS:
        cap._grab(m, screen, r.x(), r.y(), r.width(), r.height())
    cap._settle(200)
    return {m: _to_array(cap._grab(m, screen, r.x(), r.y(), r.width(), r.height()))
            for m in METHODS}


def _inset(r: QRect | None, d: int) -> QRect | None:
    if r is None:
        return None
    return QRect(r.x() + d, r.y() + d, max(1, r.width() - 2 * d), max(1, r.height() - 2 * d))


def _restack(decoy: "Decoy", shell: "Shell") -> None:
    """Re-assert the ONLY z-order this experiment is allowed to assume:
    decoy directly behind the shell, both above everything else.

    Without this the spike measures the wrong thing and cannot tell: a
    ``showMinimized()`` hands focus to whatever is underneath, which then rises
    ABOVE the decoy, and the next grab shows DWM faithfully blurring *that*
    window — a perfect, entirely false "backdrop blur" signal (delta 55 vs
    control on the first run of this spike)."""
    decoy.raise_()
    cap._settle(120)
    shell.view.raise_()
    cap._settle(200)


def _verdict_material(d_toggle: float, d_behind: float) -> str:
    if d_behind > T_CHANGED:
        return "MATERIAL ALIVE (margin tracks what is behind the window)"
    if d_toggle > T_CHANGED and d_behind < T_UNCHANGED:
        return "AMBIGUOUS (pixels changed on toggle but do NOT track what is behind)"
    if d_toggle < T_UNCHANGED and d_behind < T_UNCHANGED:
        return "MATERIAL DEAD (window opaque; alpha never reached DWM)"
    return "INCONCLUSIVE (weak signals)"


# --------------------------------------------------------------------------- #
# One configuration, measured                                                  #
# --------------------------------------------------------------------------- #

SAVED_PROBES = ("margin", "holeA", "holeB", "sceneCrisp", "sceneFrost")


def measure_config(app, mode: str, decoy: Decoy, out_dir: Path,
                   geom: tuple[int, int, int, int]) -> tuple[dict, dict]:
    """Build the shell for ``mode``, measure M1/M2/M3/M5, tear it down.

    Returns ``(report_entry, raw_arrays)`` — the raw probe arrays are persisted by
    the caller so the PARENT can diff every config against ``control`` (the M2a
    question is a CROSS-CONFIG one: "is a frost pane over an alpha hole any
    different from no frost pane at all?").

    RUNS IN ITS OWN PROCESS, one config per process. Not a style choice — measured:
    a config's M5 minimize/restore leaves the material dead, and in a shared
    process every window built AFTERWARDS came up dead too (three different configs
    returned byte-identical [84,84,84] margins, which is not physics). One window
    per process is also exactly how the app runs.
    """
    x, y, w, h = geom
    screen = QGuiApplication.primaryScreen()
    entry: dict = {"mode": mode}
    raw: dict = {}

    shell = Shell(mode, x, y, w, h)
    cap._settle(1200)                 # scene graph up, first frames rendered
    entry["qml_errors"] = shell.errors
    entry["graphics"] = shell.graphics()
    entry["material_hresults"] = shell.material_hr
    if shell.errors:
        print(f"QML ERRORS [{mode}]:", shell.errors, file=sys.stderr)

    try:
        # ---- pixels: freeze the motion so the probes are not sampling a moving
        #      target (M3 turns it back on).
        shell.set_motion(False)
        decoy.set_pattern("stripes")
        _restack(decoy, shell)
        cap._settle(500)
        shell.nudge()

        rects = {
            "margin": shell.margin_rect(),
            "holeA": _inset(shell.item_rect("holeA"), PANE_INSET),
            "holeB": _inset(shell.item_rect("holeB"), PANE_INSET),
            "sceneCrisp": _inset(shell.item_rect("sceneCrisp"), PANE_INSET),
            "sceneFrost": _inset(shell.item_rect("sceneFrost"), PANE_INSET),
            "moverBand": _inset(shell.item_rect("moverBand"), 6),
        }
        entry["probe_rects"] = {k: ([v.x(), v.y(), v.width(), v.height()] if v else None)
                                for k, v in rects.items()}

        # The scene panel's two halves must be the same SIZE or the edge-energy
        # ratio is meaningless. Force it.
        if rects["sceneCrisp"] and rects["sceneFrost"]:
            sw = min(rects["sceneCrisp"].width(), rects["sceneFrost"].width())
            sh = min(rects["sceneCrisp"].height(), rects["sceneFrost"].height())
            for k in ("sceneCrisp", "sceneFrost"):
                r = rects[k]
                rects[k] = QRect(r.x(), r.y(), sw, sh)

        on_stripes = {k: _grab_rect(screen, r) for k, r in rects.items()}
        for m in METHODS:
            cap._save(cap._grab(m, screen, x - 20, y - 20, w + 40, h + 40),
                      out_dir / f"{mode}_full_{m}.png")
        for k in ("holeA", "holeB", "sceneCrisp", "sceneFrost"):
            for m in METHODS:
                if on_stripes[k][m] is not None:
                    _save_arr(on_stripes[k][m], out_dir / f"{mode}_{k}_{m}.png")

        # only the content BEHIND changes; the decoy/shell z-order is re-asserted
        # but never inverted (a hide()/show() of the decoy would re-raise it above
        # the glass window and invalidate the whole measurement).
        decoy.set_pattern("flat")
        _restack(decoy, shell)
        cap._settle(800)
        shell.nudge()
        on_flat = {"margin": _grab_rect(screen, rects["margin"]),
                   "holeA": _grab_rect(screen, rects["holeA"]),
                   "holeB": _grab_rect(screen, rects["holeB"])}

        decoy.set_pattern("stripes")
        _restack(decoy, shell)
        cap._settle(600)
        shell.apply_material("none")
        cap._settle(800)
        shell.nudge()
        off = {"margin": _grab_rect(screen, rects["margin"])}
        shell.apply_material("acrylic")
        cap._settle(800)
        shell.nudge()

        raw["on_stripes"] = on_stripes
        raw["on_flat"] = on_flat

        # ---- M1: does the window keep its DWM material, blur present or not? --
        entry["M1_material"] = {}
        for m in METHODS:
            d_toggle = _delta(on_stripes["margin"][m], off["margin"][m])
            d_behind = _delta(on_stripes["margin"][m], on_flat["margin"][m])
            entry["M1_material"][m] = {
                "d_toggle_material_on_vs_off": round(d_toggle, 2),
                "d_behind_stripes_vs_flat": round(d_behind, 2),
                "margin_mean_rgb_on": _mean_rgb(on_stripes["margin"][m]),
                "margin_mean_rgb_off": _mean_rgb(off["margin"][m]),
                "margin_edge_energy": round(_edge_energy(on_stripes["margin"][m]), 2),
                "white_plate": _is_white_plate(on_stripes["margin"][m]),
                "verdict": _verdict_material(d_toggle, d_behind),
            }

        # ---- M2b: IN-SCENE blur (frosted half vs crisp half of one panel) -----
        entry["M2b_in_scene_blur"] = {}
        for m in METHODS:
            e_crisp = _edge_energy(on_stripes["sceneCrisp"][m])
            e_frost = _edge_energy(on_stripes["sceneFrost"][m])
            ratio = round(e_frost / e_crisp, 3) if e_crisp > 1e-6 else None
            entry["M2b_in_scene_blur"][m] = {
                "edge_crisp_half": round(e_crisp, 2),
                "edge_frosted_half": round(e_frost, 2),
                "edge_ratio": ratio,
                "verdict": ("IN-SCENE BLUR IS REAL (the frosted half's stripes are "
                            "smeared)" if ratio is not None and ratio < 0.5 else
                            "no in-scene blur (frosted half is as crisp as the "
                            "reference half)"),
            }

        # ---- M2a: BEHIND-WINDOW blur — the alpha holes ------------------------
        # Only meaningful against control; the caller fills in the cross-config
        # delta. Here we record what each hole looks like on its own.
        entry["M2a_behind_window"] = {}
        for hole in ("holeA", "holeB"):
            entry["M2a_behind_window"][hole] = {
                m: {"mean_rgb": _mean_rgb(on_stripes[hole][m])
                    if on_stripes[hole][m] is not None else None,
                    "edge_energy": round(_edge_energy(on_stripes[hole][m]), 2),
                    "d_behind_stripes_vs_flat": round(
                        _delta(on_stripes[hole][m], on_flat[hole][m]), 2)}
                for m in METHODS}

        # ---- M3: fps / CPU / heartbeat, with the 15 Hz motion LIVE -------------
        shell.set_motion(True)
        if mode == "live":
            decoy.set_pattern("live")     # ~15 Hz BEHIND the window as well
        _restack(decoy, shell)
        cap._settle(700)

        hb = Heartbeat()
        hb.start()
        cpu0, t0 = _proc_cpu_seconds(), time.perf_counter()
        fps = shell.fps_over(4000)
        cpu1, t1 = _proc_cpu_seconds(), time.perf_counter()
        hb.stop()
        wall = t1 - t0
        entry["M3_perf"] = {
            "fps": fps,
            "process_cpu_pct_of_one_core": round((cpu1 - cpu0) / wall * 100.0, 1),
            "heartbeat_max_gap_ms": round(hb.max_gap_ms, 1),
            "heartbeat_ticks": hb.ticks,
            "window_px": [w, h],
        }

        # live-content proof: does the frosted region CHANGE frame to frame?
        band = rects["moverBand"]
        b1 = _grab_rect(screen, band)
        cap._settle(180)
        b2 = _grab_rect(screen, band)
        ha1 = _grab_rect(screen, rects["holeA"])
        cap._settle(180)
        ha2 = _grab_rect(screen, rects["holeA"])
        entry["M3_live_content"] = {
            m: {"frosted_scene_band_temporal_delta": round(_delta(b1[m], b2[m]), 2),
                "alpha_hole_temporal_delta": round(_delta(ha1[m], ha2[m]), 2)}
            for m in METHODS}
        for m in METHODS:
            if b1[m] is not None:
                _save_arr(b1[m], out_dir / f"{mode}_moverband_{m}.png")
        decoy.set_pattern("stripes")

        # ---- M5: resize / minimize-restore / monitor move ---------------------
        # NOT a whiteness check alone. "No sticky white frame" is necessary but not
        # sufficient: a window can come back from a minimize with a perfectly
        # plausible-looking DARK margin and a DEAD material (the attributes died
        # with a recreated HWND — Fenrir K9). So each lifecycle event is followed
        # by the FULL material test again: only a margin that still TRACKS what is
        # behind the window proves the material survived.
        def _material_alive(scr, tag: str) -> dict:
            decoy.set_pattern("stripes")
            _restack(decoy, shell)
            cap._settle(500)
            shell.nudge()
            a = _grab_rect(scr, shell.margin_rect())
            decoy.set_pattern("flat")
            _restack(decoy, shell)
            cap._settle(700)
            shell.nudge()
            b = _grab_rect(scr, shell.margin_rect())
            decoy.set_pattern("stripes")
            _restack(decoy, shell)
            cap._settle(400)
            out = {}
            for m in METHODS:
                d_behind = _delta(a[m], b[m])
                out[m] = {
                    "mean_rgb": _mean_rgb(a[m]),
                    "d_behind_stripes_vs_flat": round(d_behind, 2),
                    "white_plate": _is_white_plate(a[m]),
                    "verdict": ("MATERIAL ALIVE" if d_behind > T_CHANGED
                                else "MATERIAL LOST after " + tag),
                }
            return out

        m5: dict = {}
        shell.set_motion(False)
        cap._settle(300)

        shell.view.resize(w + 60, h + 40)
        cap._settle(700)
        shell.view.resize(w, h)
        cap._settle(700)
        m5["after_resize"] = _material_alive(screen, "resize")

        shell.view.showMinimized()
        cap._settle(900)
        shell.view.showNormal()
        cap._settle(1100)
        m5["after_minimize_restore"] = _material_alive(screen, "minimize/restore")

        # If the material is gone after a restore, is that PERMANENT (a broken
        # window) or just UN-RE-ASSERTED? This spike deliberately does NOT install
        # gui/backdrop.py's _BackdropGuard event spine (it is a QWidget filter; this
        # is a raw QQuickWindow), and that spine exists precisely to re-run the DWM
        # chain on WindowStateChange. So: re-assert by hand and re-measure. If it
        # comes back, the loss is the KNOWN event-spine gap — orthogonal to the blur
        # question, and identical in the control config.
        shell.apply_material("acrylic")
        shell.nudge()
        cap._settle(600)
        m5["after_reassert"] = _material_alive(screen, "manual re-assert")
        for m in METHODS:
            cap._save(cap._grab(m, screen, x - 20, y - 20, w + 40, h + 40),
                      out_dir / f"{mode}_after_restore_{m}.png")

        screens = QGuiApplication.screens()
        if len(screens) > 1:
            other = next(s for s in screens if s is not screen)
            og = other.availableGeometry()
            dg = decoy.geometry()
            shell.view.setGeometry(og.x() + 40, og.y() + 60, w, h)
            decoy.setGeometry(og.x() + 40 - DECOY_INFLATE, og.y() + 60 - DECOY_INFLATE,
                              w + 2 * DECOY_INFLATE, h + 2 * DECOY_INFLATE)
            cap._settle(1200)
            m5["after_monitor_move"] = _material_alive(other, "monitor move")
            shell.view.setGeometry(x, y, w, h)
            decoy.setGeometry(dg)
            cap._settle(800)
        else:
            m5["after_monitor_move"] = ("NOT TESTABLE — single screen on this host "
                                        "(a DPI/monitor move needs a second display)")
        entry["M5_survival"] = m5

        return entry, raw
    finally:
        shell.close()
        cap._settle(400)


# --------------------------------------------------------------------------- #
# M4 — stability: each config, N times, as its OWN process                     #
# --------------------------------------------------------------------------- #

def stability_run(mode: str) -> int:
    """One short lifecycle: build the shell, render with motion, grab once, exit.

    Deliberately a whole PROCESS per iteration — the segfault class this is
    hunting (a scene-graph access violation at first render) kills the process,
    so it can only be counted from the outside.
    """
    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    w, h = min(900, avail.width() - 80), min(500, avail.height() - 140)
    x, y = avail.x() + 40, avail.y() + 60

    decoy = Decoy()
    decoy.setGeometry(x - DECOY_INFLATE, y - DECOY_INFLATE,
                      w + 2 * DECOY_INFLATE, h + 2 * DECOY_INFLATE)
    decoy.show()
    cap._settle(200)

    shell = Shell(mode, x, y, w, h)
    cap._settle(900)
    if shell.errors:
        print("QML ERRORS:", shell.errors, file=sys.stderr)
        shell.close()
        decoy.close()
        return 3
    shell.set_motion(True)
    cap._settle(900)                    # render frames — where an SG crash lands
    r = shell.margin_rect()
    cap._grab("bitblt", screen, r.x(), r.y(), r.width(), r.height())
    shell.close()
    decoy.close()
    cap._settle(150)
    return 0


def run_stability(n: int, out_dir: Path, report: dict) -> None:
    """Parent side: relaunch this script ``n`` times per config and count crashes."""
    results: dict = {}
    for mode in CONFIGS:
        codes: list[int] = []
        for _ in range(n):
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "--config", mode, "--stability-run"],
                capture_output=True, text=True, timeout=90)
            codes.append(proc.returncode)
        crashes = [c for c in codes if c != 0]
        # A Windows access violation surfaces as 0xC0000005 == -1073741819.
        segfaults = [c for c in codes if c in (-1073741819, 3221225477)]
        results[mode] = {
            "runs": n,
            "exit_codes": codes,
            "crash_count": len(crashes),
            "segfault_count": len(segfaults),
            "crash_rate": f"{len(crashes)}/{n}",
        }
        print(f"  M4 [{mode:12s}] {n} runs -> crashes={len(crashes)} "
              f"segfaults={len(segfaults)}  codes={sorted(set(codes))}")
    report["M4_stability"] = results
    (out_dir / "spike_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="QML MultiEffect / ShaderEffect glass spike.")
    ap.add_argument("--config", default="multieffect", choices=list(CONFIGS))
    ap.add_argument("--all", action="store_true",
                    help="measure every configuration in one process (M1/M2/M3/M5)")
    ap.add_argument("--stability", type=int, default=0, metavar="N",
                    help="M4: relaunch each config N times as its own process and "
                         "count crashes")
    ap.add_argument("--stability-run", action="store_true",
                    help=argparse.SUPPRESS)   # the child side of --stability
    ap.add_argument("--emit", default=None, metavar="DIR",
                    help=argparse.SUPPRESS)   # the child side of --all
    ap.add_argument("--rhi", default="opengl", choices=["opengl", "d3d11", "default"],
                    help="Qt Quick RHI. OpenGL is the DEFAULT here and in main.py: on "
                         "this stack a QQuickWindow-root shell renders flat WHITE on "
                         "D3D11 (measured 2026-07-14) — a white result there is expected, "
                         "not a failure of the blur.")
    ap.add_argument("--hold", type=int, default=0,
                    help="seconds to leave the window on screen after measuring")
    args = ap.parse_args(argv)

    reason = cap.check_environment()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    os.environ.setdefault("QSG_INFO", "1")

    # The RHI must be selected before the first QQuickWindow exists.
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    if args.rhi == "opengl":
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    elif args.rhi == "d3d11":
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)

    fmt = QSurfaceFormat.defaultFormat()
    if fmt.alphaBufferSize() < 8:
        fmt.setAlphaBufferSize(8)
        QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    reason = cap.check_environment(app)
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    if args.stability_run:
        return stability_run(args.config)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.emit:                      # a child writes into the PARENT's directory
        out_dir = Path(args.emit)
    else:
        out_dir = _REPO_ROOT / "artifacts_claude" / f"qml_multieffect_spike_{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)

    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    w = min(980, avail.width() - 80)
    h = min(560, avail.height() - 120)
    x, y = avail.x() + 40, avail.y() + 60

    import PySide6
    report: dict = {
        "spike": "qml_multieffect_glass_spike",
        "utc": ts,
        "windows_build": sys.getwindowsversion().build,  # type: ignore[attr-defined]
        "qt_platform": app.platformName(),
        "pyside": PySide6.__version__,
        "rhi_requested": args.rhi,
        "backdrop_supported": backdrop.is_backdrop_supported(),
        "screen": {"dip": [avail.width(), avail.height()],
                   "dpr": screen.devicePixelRatio(),
                   "count": len(QGuiApplication.screens())},
        "geometry": [x, y, w, h],
        "out_dir": str(out_dir),
        "configs": {},
    }

    if args.stability > 0:
        print(f"\nM4 — STABILITY: {args.stability} process launches per config "
              f"({args.stability * len(CONFIGS)} total)")
        run_stability(args.stability, out_dir, report)
        print(f"\nartifacts: {out_dir}\n")
        return 0

    # ---- CHILD: one config, its own pristine process ------------------------
    if args.emit:
        out_dir = Path(args.emit)
        decoy = Decoy()
        decoy.setGeometry(x - DECOY_INFLATE, y - DECOY_INFLATE,
                          w + 2 * DECOY_INFLATE, h + 2 * DECOY_INFLATE)
        decoy.show()
        cap._settle(400)
        try:
            entry, raw = measure_config(app, args.config, decoy, out_dir, (x, y, w, h))
            for probe in SAVED_PROBES:
                for m in METHODS:
                    arr = raw["on_stripes"].get(probe, {}).get(m)
                    if arr is not None:
                        np.save(out_dir / f"raw_{args.config}_{probe}_{m}.npy", arr)
            (out_dir / f"config_{args.config}.json").write_text(
                json.dumps(entry, indent=2), encoding="utf-8")
            return 0
        finally:
            decoy.close()

    # ---- HOLD: eyeball one config -------------------------------------------
    if args.hold > 0:
        decoy = Decoy()
        decoy.setGeometry(x - DECOY_INFLATE, y - DECOY_INFLATE,
                          w + 2 * DECOY_INFLATE, h + 2 * DECOY_INFLATE)
        decoy.show()
        shell = Shell(args.config, x, y, w, h)
        shell.set_motion(True)
        decoy.set_pattern("live")
        _restack(decoy, shell)
        print(f"holding {args.config} for {args.hold}s — LOOK AT the two frosted panes "
              "over the ALPHA HOLES (left; nothing of the scene is painted under them) "
              "vs the frosted half of the striped panel (right; in-scene content).")
        sys.stdout.flush()
        QTimer.singleShot(args.hold * 1000, app.quit)
        app.exec()
        shell.close()
        decoy.close()
        return 0

    # ---- PARENT: spawn one child per config, then diff them ------------------
    modes = list(CONFIGS) if args.all else [args.config]
    for mode in modes:
        print(f"\n--- measuring config: {mode} (own process) ---")
        sys.stdout.flush()
        # Let the previous child's window teardown (and Windows' own minimize/close
        # animation) finish before the next child starts grabbing pixels — an
        # unsettled desktop is how one config ends up measuring a different backdrop
        # than its control.
        cap._settle(1500)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()),
             "--config", mode, "--emit", str(out_dir), "--rhi", args.rhi],
            timeout=300)
        entry_path = out_dir / f"config_{mode}.json"
        if proc.returncode != 0 or not entry_path.exists():
            report["configs"][mode] = {"FAILED": f"child exit code {proc.returncode}"}
            print(f"    child FAILED: exit {proc.returncode}")
            continue
        report["configs"][mode] = json.loads(entry_path.read_text(encoding="utf-8"))

    # ---- M2a, the CROSS-CONFIG question: is a frost pane over an alpha hole
    #      ANY different from no frost pane at all?
    def _load(mode: str, probe: str, m: str):
        p = out_dir / f"raw_{mode}_{probe}_{m}.npy"
        return np.load(p) if p.exists() else None

    for mode in modes:
        if mode == "control" or "FAILED" in report["configs"].get(mode, {}):
            continue
        cmp_entry: dict = {}
        for hole in ("holeA", "holeB"):
            cmp_entry[hole] = {}
            for m in METHODS:
                a, b = _load("control", hole, m), _load(mode, hole, m)
                if a is None or b is None:
                    continue
                d = _delta(a, b)
                e_ctrl, e_cfg = _edge_energy(a), _edge_energy(b)
                ratio = round(e_cfg / e_ctrl, 3) if e_ctrl > 1e-6 else None
                cmp_entry[hole][m] = {
                    "delta_vs_control": round(d, 2),
                    "mean_rgb_control": _mean_rgb(a),
                    "mean_rgb_with_effect": _mean_rgb(b),
                    "edge_control": round(e_ctrl, 2),
                    "edge_with_effect": round(e_cfg, 2),
                    "edge_ratio_vs_control": ratio,
                    "verdict": (
                        "THE EFFECT CHANGED THE PIXELS OVER AN ALPHA HOLE — inspect "
                        "mean_rgb: a DARKER flat plate means the effect OCCLUDED the "
                        "material, it does not mean it blurred the backdrop"
                        if d > T_CHANGED else
                        "NO BACKDROP BLUR (a frost pane over an alpha hole is "
                        "indistinguishable from no frost pane at all: the effect "
                        "cannot see outside the window)"),
                }
        report["configs"][mode]["M2a_vs_control"] = cmp_entry

    (out_dir / "spike_report.json").write_text(json.dumps(report, indent=2),
                                               encoding="utf-8")
    write_manifest(report, out_dir)
    _print_summary(report)
    print(f"\nartifacts: {out_dir}\n")
    return 0


def write_manifest(report: dict, out_dir: Path) -> None:
    """The flat, greppable number sheet next to the PNGs (spike_report.json has
    everything; this is the part a human reads first)."""
    L: list[str] = []
    L.append("qml_multieffect_glass_spike — does live QML blur work, and can it reach "
             "BEHIND the window?")
    L.append(f"utc={report['utc']}  windows_build={report['windows_build']}  "
             f"pyside={report['pyside']}  rhi={report['rhi_requested']}  "
             f"platform={report['qt_platform']}")
    L.append(f"screen={report['screen']['dip']} DIP @ dpr={report['screen']['dpr']}  "
             f"screens={report['screen']['count']}  "
             f"backdrop_supported={report['backdrop_supported']}")
    L.append("host GPU: Intel UHD iGPU (single host — a signal, not a universal law)")
    L.append("")
    L.append("M1 = does the window keep its DWM material (d_behind = margin tracks what is "
             "behind it)")
    L.append("M2a = does the effect blur what is BEHIND THE WINDOW (delta vs control over an "
             "alpha hole)")
    L.append("M2b = does the effect blur IN-SCENE content (edge ratio frosted/crisp half)")
    L.append("M3 = fps / process CPU / GUI heartbeat with the 15 Hz element live")
    L.append("M5 = survival of resize / minimize-restore / re-assert")
    L.append("")
    for mode, e in report["configs"].items():
        if "FAILED" in e:
            L.append(f"[{mode}] FAILED: {e['FAILED']}")
            continue
        m1 = e["M1_material"]["bitblt"]
        m2b = e["M2b_in_scene_blur"]["bitblt"]
        p = e["M3_perf"]
        lc = e["M3_live_content"]["bitblt"]
        L.append(f"[{mode}]  qml_errors={e.get('qml_errors') or 'none'}")
        L.append(f"  M1  d_toggle={m1['d_toggle_material_on_vs_off']}  "
                 f"d_behind={m1['d_behind_stripes_vs_flat']}  "
                 f"margin_rgb={m1['margin_mean_rgb_on']}  -> {m1['verdict']}")
        L.append(f"  M2b edge crisp={m2b['edge_crisp_half']} frosted={m2b['edge_frosted_half']} "
                 f"ratio={m2b['edge_ratio']}  -> {m2b['verdict']}")
        for hole, per in e.get("M2a_vs_control", {}).items():
            v = per.get("bitblt")
            if v:
                L.append(f"  M2a {hole}: delta_vs_control={v['delta_vs_control']}  "
                         f"ctrl_rgb={v['mean_rgb_control']} eff_rgb={v['mean_rgb_with_effect']}  "
                         f"-> {v['verdict']}")
        L.append(f"  M3  fps={p['fps']}  cpu={p['process_cpu_pct_of_one_core']}% of one core  "
                 f"heartbeat_max_gap={p['heartbeat_max_gap_ms']} ms")
        L.append(f"  M3  live: frosted-scene-band temporal delta="
                 f"{lc['frosted_scene_band_temporal_delta']}  "
                 f"alpha-hole temporal delta={lc['alpha_hole_temporal_delta']}")
        m5 = e["M5_survival"]
        for ph in ("after_resize", "after_minimize_restore", "after_reassert"):
            v = m5.get(ph)
            if isinstance(v, dict):
                b = v["bitblt"]
                L.append(f"  M5  {ph}: d_behind={b['d_behind_stripes_vs_flat']} "
                         f"rgb={b['mean_rgb']} white={b['white_plate']} -> {b['verdict']}")
        L.append(f"  M5  after_monitor_move: {m5.get('after_monitor_move')}")
        L.append("")
    if "M4_stability" in report:
        L.append("M4 stability (own process per run; a Win32 access violation exits "
                 "0xC0000005):")
        for mode, v in report["M4_stability"].items():
            L.append(f"  [{mode}] runs={v['runs']} crashes={v['crash_count']} "
                     f"segfaults={v['segfault_count']} crash_rate={v['crash_rate']}")
    (out_dir / "manifest.txt").write_text("\n".join(L), encoding="utf-8")


def _print_summary(report: dict) -> None:
    print("\n" + "=" * 100)
    print(f"QML MULTIEFFECT GLASS SPIKE — build={report['windows_build']} "
          f"qt={report['qt_platform']} pyside={report['pyside']} rhi={report['rhi_requested']} "
          f"screens={report['screen']['count']}")
    print("=" * 100)
    for mode, e in report["configs"].items():
        g = e.get("graphics", {})
        print(f"\n### {mode}   qml_errors={e.get('qml_errors') or 'none'}")
        print(f"    graphics: api={g.get('graphicsApi')} surface_alpha={g.get('surface_alpha')} "
              f"noredir={g.get('ex_style', {}).get('WS_EX_NOREDIRECTIONBITMAP')} "
              f"dwm_hr={e.get('material_hresults')}")
        for m in METHODS:
            r = e["M1_material"][m]
            print(f"    M1 [{m:10s}] d_toggle={r['d_toggle_material_on_vs_off']:<7} "
                  f"d_behind={r['d_behind_stripes_vs_flat']:<7} "
                  f"margin_rgb={r['margin_mean_rgb_on']} white={r['white_plate']}")
            print(f"                  -> {r['verdict']}")
        for m in METHODS:
            r = e["M2b_in_scene_blur"][m]
            print(f"    M2b[{m:10s}] edge crisp={r['edge_crisp_half']:<7} "
                  f"frosted={r['edge_frosted_half']:<7} ratio={r['edge_ratio']}")
            print(f"                  -> {r['verdict']}")
        if "M2a_vs_control" in e:
            for hole, per in e["M2a_vs_control"].items():
                for m in METHODS:
                    r = per[m]
                    print(f"    M2a[{hole}/{m:10s}] delta_vs_control={r['delta_vs_control']:<7} "
                          f"edge {r['edge_control']} -> {r['edge_with_effect']} "
                          f"(ratio={r['edge_ratio_vs_control']})")
                    print(f"                  -> {r['verdict']}")
        p = e["M3_perf"]
        print(f"    M3 fps={p['fps']}  cpu={p['process_cpu_pct_of_one_core']}% of one core  "
              f"heartbeat_max_gap={p['heartbeat_max_gap_ms']} ms")
        lc = e.get("M3_live_content", {})
        for m in METHODS:
            if m in lc:
                print(f"    M3 [{m:10s}] frosted-scene-band temporal delta="
                      f"{lc[m]['frosted_scene_band_temporal_delta']}  "
                      f"alpha-hole temporal delta={lc[m]['alpha_hole_temporal_delta']}")
        m5 = e["M5_survival"]
        for phase in ("after_resize", "after_minimize_restore", "after_reassert",
                      "after_monitor_move"):
            v = m5[phase]
            if isinstance(v, str):
                print(f"    M5 {phase:24s} {v}")
                continue
            print(f"    M5 {phase:24s} " + "  ".join(
                f"[{m}] d_behind={v[m]['d_behind_stripes_vs_flat']} "
                f"white={v[m]['white_plate']} -> {v[m]['verdict']}" for m in METHODS))
    print("=" * 100)


if __name__ == "__main__":
    sys.exit(main())
