"""G0 SPIKE — does a DWM material survive a GL "island" (native child window)?

THE CLAIM UNDER TEST
--------------------
``docs/design/glass_council/SYNTHESIS.md`` §2.2.2 (GlassShell) and Thor's
path-D analysis (``thor.md`` §1.2) rest on ONE load-bearing assumption:

    A Windows 11 DWM system backdrop (Mica/Acrylic) survives on a top-level
    window that hosts OpenGL content **iff** the GL content lives in its OWN
    NATIVE WINDOW (``QWindow`` + ``QWidget.createWindowContainer``), rather
    than as a render-to-texture (RTT) child (``QOpenGLWidget`` / pyqtgraph
    ``GLViewWidget`` / ``QQuickWidget``), which flips the whole top-level onto
    Qt's GPU-composited flush path (Thor path D) and kills per-pixel alpha for
    the entire window.

If the island pattern holds, the GlassShell can host FastDAQ/GL surfaces
inside a glass shell. If it does not, GL content must be composited INTO the
scene (texture sharing) and the synthesis changes.

WHAT THIS BUILDS (one process, top-levels side by side, same backdrop chain —
``gui/backdrop.py::apply_backdrop`` is IMPORTED, never forked):

  * **W1 control**    — translucent window, no GL at all.        (expect: ALIVE)
  * **W2 rtt**        — same + a ``QOpenGLWidget`` child (RTT).  (expect: DEAD, path D)
                        pyqtgraph's ``GLViewWidget`` IS a ``QOpenGLWidget``
                        subclass, so this is literally the app's Motor-Stage case.
  * **W3 island**     — same + a ``QOpenGLWindow`` hosted via
                        ``QWidget.createWindowContainer`` (a real child HWND). (THE QUESTION)
  * **W4 qml_island** — ``--with-qml``: a ``QQuickView`` (a real QQuickWindow)
                        hosted the same way — the escape-hatch question for the QML
                        chrome, which is a ``QQuickWidget`` (= RTT) today.

MEASUREMENT (not the eye)
-------------------------
Every window has a large empty margin (its own unclaimed background = where a
material can show) and a **decoy window pinned behind it** painting loud
magenta/cyan stripes. Per window we grab the SAME margin rect in four states,
with BOTH OS-level capture methods (``QScreen.grabWindow`` and a GDI ``BitBlt``
of the screen DC — both reused from ``scripts/capture_onscreen.py``):

  1. ``decoy_only``  — windows lowered below the decoy (raw stripes reference)
  2. ``on_stripes``  — backdrop applied, decoy painting stripes
  3. ``on_flat``     — backdrop applied, decoy repainted flat dark
                       (z-order untouched — ONLY the content behind changes)
  4. ``off``         — backdrop reset to ``none`` + opaque canvas (baseline)

Derived numbers (mean abs channel delta, 0..255):

  * ``d_toggle``  = |on_stripes − off|      → the material changed the pixels at all
  * ``d_behind``  = |on_stripes − on_flat|  → **the decisive one**: the margin TRACKS
                    what is behind the window. Only a live see-through/material path
                    can do that; an opaque window cannot fake it.
  * ``edge_ratio`` = edge energy(on_stripes) / edge energy(decoy_only) → ≈1.0 means the
                    stripes come through CRISP (alpha reached DWM but nothing is
                    blurring = "see-through, no material"); ≪1.0 means BLURRED = a real
                    acrylic/mica material is compositing.

Two canvas modes, because the two are NOT the same experiment:
  ``--canvas qss``    (default) — app-realistic: the window paints ``rgba(bg, α)``
                      while a backdrop is active and an opaque colour when it is not,
                      exactly like ``gui/style.py``'s ``_canvas_fill``.
  ``--canvas alpha0`` — maximally sensitive: the window paints NOTHING while a
                      backdrop is active (alpha-0 canvas ⇒ 100 % material).

Structural evidence, independent of any pixel: ``EnumChildWindows`` on each
top-level HWND proves whether the GL surface is a separate native window (W3)
or not (W2), plus each child's ``internalWinId()`` — which, unlike ``winId()``,
does NOT force native creation (a probe must not manufacture its own answer).
``--diag`` additionally dumps the flush-path-relevant state: surface-format
alpha, ``WA_TranslucentBackground`` / ``WA_NoSystemBackground``, and the
Win32 ex-style bits (``WS_EX_LAYERED`` / ``WS_EX_NOREDIRECTIONBITMAP``).

RUN (real desktop session only — refuses under offscreen/minimal)
-----------------------------------------------------------------
::

    cd TCT_app
    .venv/Scripts/python.exe scripts/spikes/gl_island_glass_spike.py                  # W1/W2/W3 + exit
    .venv/Scripts/python.exe scripts/spikes/gl_island_glass_spike.py --with-qml       # + QQuickView island
    .venv/Scripts/python.exe scripts/spikes/gl_island_glass_spike.py --qml-root       # W4 QML-root shell
    .venv/Scripts/python.exe scripts/spikes/gl_island_glass_spike.py --qml-root --rhi opengl
    .venv/Scripts/python.exe scripts/spikes/gl_island_glass_spike.py --live-toggle    # the app's broken path
    .venv/Scripts/python.exe scripts/spikes/gl_island_glass_spike.py --hold 180       # eyeball

FINDINGS — 2026-07-13/14, Win11 build 26200, PySide6 6.11.1, Intel UHD iGPU
---------------------------------------------------------------------------
1. **The island claim is NOT falsified — but neither is the RTT claim confirmed.**
   With the material attached correctly, W1 (no GL), W2 (RTT QOpenGLWidget), W3
   (native-window GL island) and W4 (QQuickView island) ALL kept a live DWM
   material in their margins. **Thor's path-D barrier — "any visible RTT child
   kills the whole window's material" — did not reproduce on Qt 6.11.1.** The GL
   island is *sufficient*; it is not *necessary* on this stack.
2. **The real killer is ATTRIBUTE ORDER, not GL.** ``WA_TranslucentBackground``
   set AFTER the native window exists ⇒ the surface never gains alpha
   (``format().alphaBufferSize() == -1``) and EVERY window — including the GL-free
   control — renders its canvas fully opaque: the material is dead, acrylic-on and
   acrylic-off are pixel-identical. Set before creation ⇒ alpha 8, material live.
   ``apply_backdrop`` calls ``winId()`` (which CREATES the HWND) *before* its canvas
   prep, so the "toggle the backdrop on a live window" path cannot work by
   construction. Reproduce with ``--live-toggle`` vs the default.
3. **Structural proof (deterministic, EnumChildWindows):** W2's QOpenGLWidget has
   ZERO child HWNDs (an alien RTT widget), while W3's QOpenGLWindow and W4's
   QQuickView each own exactly ONE child HWND
   (``Qt6111QWindowOwnDCIcon`` / ``Qt6111QWindowIcon``). So the QML chrome DOES have
   an escape hatch from RTT: host a real ``QQuickWindow`` in a window container
   instead of using a ``QQuickWidget``.
4. **The RHI verdict is the OPPOSITE of the design assumption.** A QQuickWindow-root
   shell (``--qml-root``) with a transparent scene renders its margins **flat WHITE
   (255) on the D3D11 RHI** and **real, blurred, live glass on the OpenGL RHI**.
   Mechanism: neither backend sets ``WS_EX_NOREDIRECTIONBITMAP`` — Qt 6.11 never
   creates the DirectComposition swapchain the "D3D = alpha first-class" premise
   assumes — so D3D11's flip-model present loses the alpha against an opaque
   redirection surface. **The OpenGL pin in main.py is therefore NOT dead weight:
   on this host it is the only RHI that yields glass at all.**
5. **A pure-Python scene-graph plot item is NOT dependable here.** PySide6 6.11
   exposes the whole API (QQuickItem.updatePaintNode, QSGGeometryNode, QSGGeometry,
   materials, QQuickFramebufferObject, QQuickRhiItem, even QRhi) — but a
   ``QSGGeometryNode`` built from Python segfaults (access violation at first
   render) in **roughly half of all runs**, independent of render loop
   (threaded/basic), RHI (D3D11/OpenGL), and ownership pattern (Owns* flags vs
   Python refs). ``--plot-impl sg`` reproduces it; ``--plot-impl painted``
   (QQuickPaintedItem) is the stable stand-in used for the measurements.
6. **Glass CAN be composited over a live plot inside a QML scene** (measured:
   the overlay region keeps changing frame to frame ⇒ the running waveform is
   visible through the translucent rectangle) — the thing a native-window island
   can never do. Its price, measured: one shared pipeline. A deliberately heavy
   render item drags the WHOLE window from ~60 fps to ~4 fps; a native-window
   island owns its own swapchain and cannot stall the shell's repaint.

NOT app code. NOT imported by the app. NOT part of the test suite. A scratch
experiment: no hardware, no DeviceManager, and it never reads or writes
QSettings (unlike ``capture_onscreen.py``, it builds no ``TCTMainWindow``).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import sys
import tempfile
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# TCT_app/ and TCT_app/scripts/ on the path: `gui.backdrop` is the chain under
# test (imported, never forked) and `capture_onscreen` owns the two OS-level
# grab implementations this spike reuses verbatim.
_SPIKES = Path(__file__).resolve().parent
_SCRIPTS = _SPIKES.parent
_TCT_APP = _SCRIPTS.parent
_REPO_ROOT = _TCT_APP.parent
for _p in (str(_TCT_APP), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage,  # noqa: E402
                           QLinearGradient, QPainter, QPolygonF, QSurfaceFormat)
from PySide6.QtOpenGL import QOpenGLWindow  # noqa: E402
from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: E402
from PySide6.QtQuick import (QQuickItem, QQuickPaintedItem,  # noqa: E402
                             QSGFlatColorMaterial, QSGGeometry, QSGGeometryNode, QSGNode)
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

import capture_onscreen as cap  # noqa: E402
from gui import backdrop  # noqa: E402  (THE chain under test)

# --------------------------------------------------------------------------- #
# Geometry — computed from the ACTUAL screen.                                  #
# (Hard-coded rects are a trap here: this host is 3840x2160 @ 250 % = 1536x864 #
# DIP, and a 3x520 px layout silently ran off the right edge — the first run   #
# of this spike measured partly off-screen black and "proved" nothing.)        #
# --------------------------------------------------------------------------- #

WIN_Y = 70
MARGIN_X = 18
GAP = 12
GL_FRAC = 0.78          # GL surface width as a fraction of the window width
PROBE_INSET_X = 24
PROBE_FROM_BOTTOM = 74
PROBE_H = 44
DECOY_INFLATE = 12

# mean-abs-channel-delta thresholds (0..255 scale)
T_CHANGED = 6.0
T_UNCHANGED = 2.0


def _pyside_version() -> str:
    import PySide6
    return PySide6.__version__


def _layout(n: int) -> tuple[int, int, int, int]:
    """(win_w, win_h, x0, y0) that actually fits the primary screen."""
    avail = QGuiApplication.primaryScreen().availableGeometry()
    win_w = (avail.width() - 2 * MARGIN_X - (n - 1) * GAP) // n
    win_h = min(430, avail.height() - WIN_Y - 40)
    return win_w, win_h, avail.x() + MARGIN_X, avail.y() + WIN_Y


# --------------------------------------------------------------------------- #
# Decoy — the "content behind the window" whose changes we look for            #
# --------------------------------------------------------------------------- #

class Decoy(QWidget):
    """Frameless opaque window pinned BEHIND a spike window.

    Two patterns, toggled without ever touching z-order (a hide()/show() would
    re-raise it above the glass window and invalidate the measurement):
    ``stripes`` (loud magenta/cyan, high-frequency — so a blur is measurable)
    and ``flat`` (near-black).
    """

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.pattern = "stripes"

    def set_pattern(self, pattern: str) -> None:
        self.pattern = pattern
        self.update()
        self.repaint()

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


# --------------------------------------------------------------------------- #
# GL content — animated, so "GL is really rendering" is not in doubt           #
# --------------------------------------------------------------------------- #

# Which GPU actually rendered each surface. On a hybrid-graphics laptop (Intel iGPU
# + NVIDIA dGPU) DWM composes on one adapter while the app may render on the other;
# that cross-adapter copy is the difference between smooth glass and stuttering
# glass, so the spike NAMES the adapter instead of assuming it.
_GL_STRINGS: dict[str, dict] = {}

GL_VENDOR, GL_RENDERER, GL_VERSION = 0x1F00, 0x1F01, 0x1F02


def _gl_strings(tag: str) -> dict:
    """GL_VENDOR/RENDERER/VERSION of the CURRENT context (call from initializeGL)."""
    from PySide6.QtGui import QOpenGLContext
    ctx = QOpenGLContext.currentContext()
    if ctx is None:
        return {"error": "no current GL context"}

    def _s(enum: int) -> str:
        try:                                    # Qt's own wrapper first
            v = ctx.functions().glGetString(enum)
            if v:
                return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            pass
        try:                                    # opengl32 fallback (context is current)
            lib = ctypes.windll.opengl32
            lib.glGetString.restype = ctypes.c_char_p
            v = lib.glGetString(ctypes.c_uint(enum))
            return v.decode() if v else "?"
        except Exception as exc:
            return f"ERR {type(exc).__name__}"

    f = ctx.format()
    info = {"GL_VENDOR": _s(GL_VENDOR), "GL_RENDERER": _s(GL_RENDERER),
            "GL_VERSION": _s(GL_VERSION),
            "ctx": f"{f.majorVersion()}.{f.minorVersion()} alpha={f.alphaBufferSize()} "
                   f"samples={f.samples()}"}
    _GL_STRINGS[tag] = info
    return info


def _paint_gl_scene(device, w: int, h: int, phase: float, tag: str) -> None:
    """Shared painter for both GL surfaces. QPainter on a GL paint device is
    still the GL pipeline: a QOpenGLWidget stays render-to-texture and a
    QOpenGLWindow stays a native GL surface no matter which drawing API runs
    inside — and this keeps the spike free of a PyOpenGL dependency."""
    p = QPainter(device)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor("#0E2233"))
    grad.setColorAt(1.0, QColor("#123D2E"))
    p.fillRect(0, 0, w, h, grad)
    p.translate(w / 2.0, h / 2.0)
    p.rotate(phase)
    r = min(w, h) * 0.35
    p.setBrush(QBrush(QColor("#39D98A")))
    p.setPen(QColor("#EAFBF2"))
    p.drawPolygon(QPolygonF([QPoint(0, int(-r)), QPoint(int(r * 0.87), int(r * 0.5)),
                             QPoint(int(-r * 0.87), int(r * 0.5))]))
    p.resetTransform()
    p.setPen(QColor("#EAFBF2"))
    p.drawText(8, 18, f"GL: {tag}")
    p.end()


class SpinGLWidget(QOpenGLWidget):
    """W2's poison: a render-to-texture child — the class pyqtgraph's
    ``GLViewWidget`` derives from (verified via ``GLViewWidget.__mro__``)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self) -> None:
        self._phase = (self._phase + 3.0) % 360.0
        self.update()

    def initializeGL(self) -> None:  # noqa: N802
        _gl_strings("W2_rtt/QOpenGLWidget")

    def paintGL(self) -> None:  # noqa: N802
        _paint_gl_scene(self, self.width(), self.height(), self._phase, "QOpenGLWidget RTT")


class SpinGLWindow(QOpenGLWindow):
    """W3's island: a real ``QWindow`` with its own GL surface and its own HWND,
    hosted in the widget tree via ``QWidget.createWindowContainer``."""

    def __init__(self) -> None:
        super().__init__()
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self) -> None:
        self._phase = (self._phase + 3.0) % 360.0
        self.update()

    def initializeGL(self) -> None:  # noqa: N802
        _gl_strings("W3_island/QOpenGLWindow")

    def paintGL(self) -> None:  # noqa: N802
        _paint_gl_scene(self, self.width(), self.height(), self._phase, "QOpenGLWindow island")


_QML_SOURCE = """
import QtQuick
Rectangle {
    color: "#0E2233"
    Rectangle {
        anchors.centerIn: parent
        width: 84; height: 84; color: "#39D98A"; radius: 8
        RotationAnimation on rotation { from: 0; to: 360; duration: 3000; loops: Animation.Infinite }
    }
    Text { x: 8; y: 4; color: "#EAFBF2"; text: "QQuickWindow island" }
}
"""


# --------------------------------------------------------------------------- #
# The spike windows                                                            #
# --------------------------------------------------------------------------- #

class SpikeWindow(QWidget):
    """A top-level with a deliberately huge empty margin — that margin IS the
    measured surface.

    Canvas modes mirror the app: ``qss`` paints ``rgba(bg, α)`` while a backdrop
    is active and an opaque colour when it is not (``gui/style.py``'s
    ``_canvas_fill`` rule, the configuration whose acrylic blur is live-verified
    on the theme-editor dialog); ``alpha0`` paints nothing at all while a
    backdrop is active (100 % material — maximally sensitive).
    """

    OPAQUE_QSS = "QWidget#spikeShell { background: #1E2026; }"
    GLASS_QSS = "QWidget#spikeShell { background: rgba(30, 32, 38, 0.55); }"

    def __init__(self, title: str, subtitle: str, kind: str, canvas: str,
                 win_w: int, win_h: int, glass_at_birth: bool = True) -> None:
        super().__init__(None)
        self.kind_label = title
        self.canvas = canvas
        self.setObjectName("spikeShell")
        self.setWindowTitle(f"{title} — {subtitle}")
        self.setFixedSize(win_w, win_h)
        self.setStyleSheet(self.OPAQUE_QSS)

        # THE ORDER THAT MATTERS. Qt decides a top-level's surface alpha (and thus
        # whether per-pixel alpha can ever reach DWM) when the PLATFORM WINDOW is
        # created. gui/backdrop.py::apply_backdrop calls winId() — which creates it
        # — and only afterwards sets WA_TranslucentBackground, so on its own it can
        # never make a from-birth-translucent window. Setting the attribute here,
        # before anything creates the HWND, is the documented recipe.
        if glass_at_birth:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.set_canvas(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 34, 30, 92)
        lay.setSpacing(14)

        head = QLabel(f"{title}\n{subtitle}", self)
        head.setStyleSheet("color:#E6E9EF; background:transparent; font:600 12px 'Segoe UI';")
        head.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay.addWidget(head)

        gl_w = int(win_w * GL_FRAC)
        gl_h = int(gl_w * 0.48)
        self.gl_child: QWidget | None = None
        self.gl_window = None  # own the ref; the container reparents but does not own it

        if kind == "rtt":
            self.gl_child = SpinGLWidget(self)
        elif kind == "island":
            self.gl_window = SpinGLWindow()
            self.gl_child = QWidget.createWindowContainer(self.gl_window, self)
        elif kind == "qml_island":
            from PySide6.QtQuick import QQuickView
            tmp = Path(tempfile.gettempdir()) / "tct_gl_island_spike.qml"
            tmp.write_text(_QML_SOURCE, encoding="utf-8")
            view = QQuickView()
            view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
            view.setSource(QUrl.fromLocalFile(str(tmp)))
            self.gl_window = view
            self.gl_child = QWidget.createWindowContainer(view, self)

        if self.gl_child is not None:
            self.gl_child.setFixedSize(gl_w, gl_h)
            lay.addWidget(self.gl_child, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)

    def set_canvas(self, glass: bool) -> None:
        """Paint the canvas the way the app would for this backdrop state."""
        if not glass:
            self.setStyleSheet(self.OPAQUE_QSS)
        elif self.canvas == "alpha0":
            self.setStyleSheet("")          # nothing paints -> alpha-0 canvas
        else:
            self.setStyleSheet(self.GLASS_QSS)

    def probe_rect_global(self) -> QRect:
        top = self.height() - PROBE_FROM_BOTTOM
        tl = self.mapToGlobal(QPoint(PROBE_INSET_X, top))
        return QRect(tl.x(), tl.y(), self.width() - 2 * PROBE_INSET_X, PROBE_H)


# --------------------------------------------------------------------------- #
# W4 — the QML-ROOT shell (the OTHER island mechanism)                          #
#                                                                              #
# W3 hosts GL in its own NATIVE CHILD WINDOW: DWM composites it separately, so #
# the parent can keep its material — but the island is then opaque and         #
# topmost BY MECHANISM, so no QML glass/overlay can ever be drawn on top of it.#
#                                                                              #
# W4 is the alternative: the shell top-level IS a QQuickWindow and the fast    #
# data surface is a SCENE-GRAPH ITEM (a QSGGeometryNode built in Python) —     #
# i.e. the plot is a GPU primitive INSIDE the scene, not a foreign window. If  #
# this holds, glass/blur/overlays CAN be composited over the live waveform     #
# (the visionOS look), at the price of sharing one render pipeline with the UI.#
#                                                                              #
# PySide6 6.11 exposes the whole scene-graph surface (verified at runtime by   #
# ``report["qsg_api"]`` below): QQuickItem.updatePaintNode, QSGGeometryNode,   #
# QSGGeometry(+defaultAttributes_Point2D), QSGFlatColorMaterial, QSGTexture,   #
# QQuickFramebufferObject, QQuickRhiItem, and even QRhi/QRhiCommandBuffer.     #
# --------------------------------------------------------------------------- #

class FastPlotItem(QQuickItem):
    """A FastDAQ-style waveform as a pure scene-graph node — the Gemini design.

    No FBO, no RTT widget, no native window: ``updatePaintNode`` builds a
    line-strip ``QSGGeometryNode`` that the Quick renderer draws with the rest of
    the scene, so QML items can be stacked ON TOP of it with real alpha.

    ``busy`` swaps the point count to a deliberately punishing number so the
    isolation cost (a slow render item stalling the whole UI, because they share
    one pipeline) can be MEASURED rather than argued about.
    """

    N_IDLE = 2048
    N_BUSY = 120_000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        self._phase = 0.0
        self._busy = False
        # PYSIDE6 OWNERSHIP TRAP (found the hard way — intermittent SEGFAULT):
        # the C++/Qt idiom is to build QSGGeometry/QSGMaterial as locals and hand
        # ownership to the node via QSGNode.OwnsGeometry/OwnsMaterial. In PySide6
        # that races the Python GC — the wrapper is collected while the scene graph
        # still uses (and separately deletes) the object. Keeping Python refs and
        # NOT setting the Owns* flags is the stable pattern: Python owns them, they
        # outlive the node, and nothing is double-freed. This is a real constraint
        # on any pure-Python scene-graph plot item.
        self._node = None
        self._geometry = None
        self._material = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _tick(self) -> None:
        self._phase += 0.15
        self.update()

    @property
    def _npoints(self) -> int:
        return self.N_BUSY if self._busy else self.N_IDLE

    def updatePaintNode(self, old_node, _data):  # noqa: N802
        node = old_node
        n = self._npoints
        if node is None or self._node is None:
            node = QSGGeometryNode()
            self._geometry = QSGGeometry(QSGGeometry.defaultAttributes_Point2D(), n)
            self._geometry.setDrawingMode(QSGGeometry.DrawingMode.DrawLineStrip)
            self._geometry.setLineWidth(2.0)
            node.setGeometry(self._geometry)
            self._material = QSGFlatColorMaterial()
            self._material.setColor(QColor("#39D98A"))
            node.setMaterial(self._material)
            self._node = node  # keep it alive on the Python side — see __init__

        geo = self._geometry
        if geo.vertexCount() != n:
            geo.allocate(n)
        w, h = float(self.width()), float(self.height())
        pts = geo.vertexDataAsPoint2D()
        two_pi = 6.2831853
        for i in range(n):
            t = i / (n - 1)
            y = (h * 0.5
                 + math.sin(t * two_pi * 6.0 + self._phase) * h * 0.30
                 * math.sin(t * two_pi * 0.5 + self._phase * 0.3))
            pts[i].set(w * t, y)
        node.markDirty(QSGNode.DirtyState.DirtyGeometry)
        return node


class PaintedPlotItem(QQuickPaintedItem):
    """The STABLE stand-in for the scene-graph plot item.

    ``FastPlotItem`` above is the design-correct version (GPU geometry, zero CPU
    copies) — but it segfaults about half the time (see its docstring), so the
    spike needs a second implementation to finish the material/overlay/pacing
    measurements. ``QQuickPaintedItem`` paints on the CPU into a texture that the
    scene graph then composites: slower and copy-heavy (i.e. NOT the FastDAQ
    answer), but it is still a real item INSIDE the scene, so it answers the two
    architectural questions — does the QQuickWindow root keep its material, and
    can QML glass be composited over live plot content — identically.
    """

    N_IDLE = 2048
    N_BUSY = 120_000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _tick(self) -> None:
        self._phase += 0.15
        self.update()

    def paint(self, painter) -> None:
        n = self.N_BUSY if self._busy else self.N_IDLE
        w, h = float(self.width()), float(self.height())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = painter.pen()
        pen.setColor(QColor("#39D98A"))
        pen.setWidth(2)
        painter.setPen(pen)
        two_pi = 6.2831853
        poly = QPolygonF()
        for i in range(n):
            t = i / (n - 1)
            y = (h * 0.5 + math.sin(t * two_pi * 6.0 + self._phase) * h * 0.30
                 * math.sin(t * two_pi * 0.5 + self._phase * 0.3))
            poly.append(QPointF(w * t, y))
        painter.drawPolyline(poly)


_QML_ROOT_SOURCE = """
import QtQuick
import TctSpike

Item {
    id: root
    // NO background rectangle: the root stays transparent so the DWM material
    // behind the QQuickWindow is what fills the margins.
    Text {
        x: 30; y: 26; color: "#E6E9EF"; font.pixelSize: 13; font.bold: true
        text: "W4_qml_root — QQuickWindow root + scene-graph FastPlot item"
    }

    FastPlot {
        id: plot
        objectName: "plot"
        x: 30; y: 70
        width: root.width - 60
        height: 170
    }

    // GLASS OVER THE LIVE WAVEFORM — impossible against a native-window island.
    Rectangle {
        objectName: "overlay"
        x: plot.x + plot.width * 0.52
        y: plot.y + plot.height * 0.10
        width: plot.width * 0.42
        height: plot.height * 0.80
        radius: 10
        color: "#59FFFFFF"                 // 35 % white over the running plot
        border.color: "#99FFFFFF"
        border.width: 1
        Text {
            anchors.centerIn: parent; color: "#0B1020"; font.pixelSize: 12
            text: "glass OVER live plot"
        }
    }
}
"""


class QmlRootShell:
    """A real ``QQuickWindow`` top-level (QQuickView) with a transparent scene.

    NOTE FOR THE SYNTHESIS: ``gui/backdrop.py::apply_backdrop`` takes a
    ``QWidget`` (it calls ``QWidget.windowHandle()``), so it cannot be pointed at
    a ``QQuickWindow`` as-is. This spike therefore calls the module's HWND-level
    primitives directly — which is exactly the "mechanical extraction of an
    HWND-level entry point" SYNTHESIS §2.2.2 predicts the GlassShell will need.
    It is reuse, not a fork: the same DWM calls, in the same order.
    """

    def __init__(self, kind: str, x: int, y: int, w: int, h: int, rhi: str = "default",
                 plot_impl: str = "painted") -> None:
        from PySide6.QtQml import qmlRegisterType
        from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

        # The RHI question (Loki's unpriced dependency): main.py pins Qt Quick to
        # OpenGL — but that pin exists ONLY so a chrome QQuickWidget could share one
        # window with the Motor-Stage GLViewWidget, and that GLViewWidget is GONE
        # (main.py:41). The GlassShell wants D3D (DirectComposition is where
        # per-pixel alpha is first-class). So: measure both.
        if rhi == "opengl":
            QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
        elif rhi == "d3d11":
            QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)

        self.plot_impl = plot_impl
        impl = FastPlotItem if plot_impl == "sg" else PaintedPlotItem
        qmlRegisterType(impl, "TctSpike", 1, 0, "FastPlot")
        QQuickWindow.setDefaultAlphaBuffer(True)  # BEFORE the window exists

        tmp = Path(tempfile.gettempdir()) / "tct_gl_island_spike_root.qml"
        tmp.write_text(_QML_ROOT_SOURCE, encoding="utf-8")

        self.view = QQuickView()
        self.view.setTitle("W4_qml_root — QQuickWindow root + scene-graph FastPlot")
        self.view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.view.setColor(QColor(0, 0, 0, 0))     # transparent scene clear
        self.view.setGeometry(x, y, w, h)
        self.view.setSource(QUrl.fromLocalFile(str(tmp)))
        self.errors = [str(e) for e in self.view.errors()]

        self.frames = 0
        self.view.frameSwapped.connect(self._on_frame)

        # Show FIRST, attach the material after the scene graph is up. Attaching DWM
        # attributes to a not-yet-shown QQuickWindow and then calling show() crashed
        # the D3D11 backend intermittently on this host (access violation inside
        # show()'s first synchronous present); showing first is stable AND is what
        # the app would do anyway. Unlike a QWidget, a QQuickWindow does not need
        # the attach before creation: its alpha comes from setDefaultAlphaBuffer +
        # the transparent scene clear, not from a widget attribute.
        self.view.show()
        cap._settle(300)
        self.hwnd = int(self.view.winId())
        self.apply_material(kind)
        self.requested_rhi = rhi

    def graphics_info(self) -> dict:
        """Which RHI backend Qt Quick ACTUALLY chose (not what we asked for)."""
        from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
        try:
            api = QQuickWindow.graphicsApi()
            name = api.name if hasattr(api, "name") else str(api)
        except Exception as exc:
            name = f"ERR {exc}"
        ri = self.view.rendererInterface()
        live = "?"
        if ri is not None:
            try:
                a = ri.graphicsApi()
                live = a.name if hasattr(a, "name") else str(a)
            except Exception:
                pass
        fmt = self.view.format()
        return {"requested": self.requested_rhi, "QQuickWindow.graphicsApi": name,
                "rendererInterface.graphicsApi": live,
                "surface_alpha": fmt.alphaBufferSize(),
                "scene_color_alpha": self.view.color().alpha(),
                # WS_EX_NOREDIRECTIONBITMAP is the tell: it is what Qt sets when it
                # presents through a DirectComposition swapchain (per-pixel alpha
                # first-class). Without it, a translucent scene is composited against
                # an OPAQUE redirection surface — which is how "transparent" becomes
                # a flat WHITE plate.
                "ex_style": ex_style_flags(self.hwnd),
                "note": "QSG_INFO=1 is set in this mode — Qt logs the chosen RHI backend "
                        "and the D3D adapter (GPU) to stderr above."}

    def _on_frame(self) -> None:
        self.frames += 1

    def apply_material(self, kind: str) -> dict:
        """The same DWM chain as gui/backdrop.apply_backdrop, at HWND level."""
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

    def item(self, object_name: str):
        root = self.view.rootObject()
        if root is None:
            return None
        return root.findChild(QQuickItem, object_name)

    def item_rect_global(self, object_name: str) -> QRect | None:
        it = self.item(object_name)
        if it is None:
            return None
        p = it.mapToScene(it.position() * 0)  # scene origin of the item
        top_left = self.view.mapToGlobal(QPoint(int(it.x()), int(it.y())))
        return QRect(top_left.x(), top_left.y(), int(it.width()), int(it.height()))

    def margin_rect_global(self) -> QRect:
        g = self.view.geometry()
        top = g.height() - PROBE_FROM_BOTTOM
        tl = self.view.mapToGlobal(QPoint(PROBE_INSET_X, top))
        return QRect(tl.x(), tl.y(), g.width() - 2 * PROBE_INSET_X, PROBE_H)

    def measure_fps(self, ms: int) -> float:
        self.frames = 0
        cap._settle(ms)
        return round(self.frames * 1000.0 / ms, 1)


# --------------------------------------------------------------------------- #
# Win32 / Qt structural probes                                                 #
# --------------------------------------------------------------------------- #

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

WS_EX_LAYERED = 0x00080000
WS_EX_NOREDIRECTIONBITMAP = 0x00200000
WS_EX_COMPOSITED = 0x02000000
GWL_EXSTYLE = -20


def enum_child_hwnds(hwnd: int) -> list[dict]:
    """Every descendant HWND of ``hwnd`` (class name + screen rect, physical px).

    THE structural proof: an RTT child (QOpenGLWidget) is an *alien* widget with
    NO HWND at all, while a ``createWindowContainer``-hosted QWindow is a genuine
    child window and must show up here.
    """
    out: list[dict] = []
    user32 = ctypes.windll.user32

    def _cb(h, _l):  # noqa: ANN001
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, buf, 256)
        r = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(h), ctypes.byref(r))
        out.append({"hwnd": int(h), "class": buf.value,
                    "rect_px": [r.left, r.top, r.right - r.left, r.bottom - r.top]})
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), _WNDENUMPROC(_cb), 0)
    return out


def ex_style_flags(hwnd: int) -> dict:
    ex = ctypes.windll.user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    return {"raw": f"0x{ex & 0xFFFFFFFF:08X}",
            "WS_EX_LAYERED": bool(ex & WS_EX_LAYERED),
            "WS_EX_NOREDIRECTIONBITMAP": bool(ex & WS_EX_NOREDIRECTIONBITMAP),
            "WS_EX_COMPOSITED": bool(ex & WS_EX_COMPOSITED)}


def qt_child_natives(win: SpikeWindow) -> list[dict]:
    """Qt-side view. Uses ``internalWinId()`` — 0 for an alien widget, and it does
    NOT force native creation (calling ``winId()`` here would CREATE the very HWND
    we are testing for: the probe would manufacture its own answer)."""
    rows = []
    for child in win.findChildren(QWidget):
        get = getattr(child, "internalWinId", None)
        iwid = int(get()) if callable(get) else -1
        rows.append({"class": type(child).__name__, "internalWinId": iwid,
                     "WA_NativeWindow": bool(child.testAttribute(
                         Qt.WidgetAttribute.WA_NativeWindow)),
                     "WA_PaintOnScreen": bool(child.testAttribute(
                         Qt.WidgetAttribute.WA_PaintOnScreen))})
    return rows


def flush_path_diag(win: SpikeWindow) -> dict:
    """The flush-path-relevant state (Thor §1.2/§1.3), read straight off Qt/Win32."""
    wh = win.windowHandle()
    fmt = wh.format() if wh is not None else None
    req = wh.requestedFormat() if wh is not None else None
    d = {
        "hwnd": f"0x{int(win.winId()):X}",
        "WA_TranslucentBackground": bool(win.testAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground)),
        "WA_NoSystemBackground": bool(win.testAttribute(
            Qt.WidgetAttribute.WA_NoSystemBackground)),
        "autoFillBackground": win.autoFillBackground(),
        "palette_window": win.palette().color(win.backgroundRole()).name(QColor.NameFormat.HexArgb),
        "styleSheet": win.styleSheet(),
        "format_alpha": fmt.alphaBufferSize() if fmt else None,
        "requested_alpha": req.alphaBufferSize() if req else None,
        "surface_type": str(wh.surfaceType()) if wh else None,
        "ex_style": ex_style_flags(int(win.winId())),
    }
    if win.gl_window is not None:
        gwh = win.gl_window
        d["gl_window"] = {
            "class": type(gwh).__name__,
            "winId": f"0x{int(gwh.winId()):X}",
            "surface_type": str(gwh.surfaceType()),
            "format_alpha": gwh.format().alphaBufferSize(),
            "ex_style": ex_style_flags(int(gwh.winId())),
        }
    return d


# --------------------------------------------------------------------------- #
# Pixel metrics                                                                #
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
    if a.shape != b.shape:
        return float("nan")
    return float(np.abs(a - b).mean())


def _edge_energy(a: np.ndarray) -> float:
    """Mean horizontal gradient — the decoy's stripes are vertical, so a crisp
    view of them scores high and a blurred (acrylic) view scores low."""
    if a.shape[1] < 2:
        return 0.0
    return float(np.abs(np.diff(a, axis=1)).mean())


def _mean_rgb(a: np.ndarray) -> list[float]:
    m = a.reshape(-1, 3).mean(axis=0)
    return [round(float(m[2]), 1), round(float(m[1]), 1), round(float(m[0]), 1)]


def _grab_all(methods: list[str], win: SpikeWindow) -> dict[str, np.ndarray]:
    """Grab the probe band with every method — TWICE, keeping the second.

    The first grab is a throwaway warm-up: a DWM material recomposites
    asynchronously after the content behind it changes, and a GL child is
    repainting at 30 Hz, so the very first read after a state change can catch a
    stale composite. (The first version of this spike did exactly that and
    produced two capture methods disagreeing about the same window.)
    """
    r = win.probe_rect_global()
    for m in methods:
        cap._grab(m, win.screen(), r.x(), r.y(), r.width(), r.height())
    cap._settle(250)
    return {m: _to_array(cap._grab(m, win.screen(), r.x(), r.y(), r.width(), r.height()))
            for m in methods}


def _nudge(win) -> None:
    """Move the window 1 px and back — the documented "heal" for the Qt 6.10/6.11 +
    Win11 stale-surface bug (Thor §1.5, forum 163927), where a window keeps
    presenting a stale composite after live attribute churn until a REAL geometry
    change forces a fresh surface. ``update()`` is a weaker nudge and is not
    enough; without this the same command produced different pixels run to run."""
    g = win.geometry()
    win.move(g.x() + 1, g.y())
    win.move(g.x(), g.y())


def _strip_shot(wins: list[SpikeWindow], methods: list[str], out_dir: Path, tag: str,
                x0: int, y0: int, win_w: int, win_h: int) -> None:
    """Whole-row screenshot, taken IN the phase it names (never after a re-apply —
    re-applying a backdrop to an already-shown window is itself broken, see the
    module docstring's preapply finding)."""
    for m in methods:
        img = cap._grab(m, wins[0].screen(), x0 - 20, y0 - 20,
                        len(wins) * (win_w + GAP) + 40, win_h + 60)
        cap._save(img, out_dir / f"all_windows_{tag}_{m}.png")


def _verdict(d_toggle: float, d_behind: float, edge_ratio: float | None) -> str:
    """The decisive signal is d_behind: a margin that changes when ONLY the content
    behind the window changed can happen for exactly one reason — the window's alpha
    is reaching DWM and something is compositing through it."""
    if d_behind > T_CHANGED:
        if edge_ratio is not None and edge_ratio > 0.75:
            return ("SEE-THROUGH BUT UNBLURRED (alpha reaches DWM; stripes crisp -> "
                    "no material compositing)")
        return "MATERIAL ALIVE (margin tracks the content behind it, blurred)"
    if d_toggle > T_CHANGED and d_behind < T_UNCHANGED:
        return ("AMBIGUOUS (pixels changed on toggle but do NOT track what is behind "
                "-> flat plate / wallpaper-only material)")
    if d_toggle < T_UNCHANGED and d_behind < T_UNCHANGED:
        return "MATERIAL DEAD (nothing changed: window opaque; alpha never reached DWM)"
    return "INCONCLUSIVE (weak signals — eyeball needed)"


# --------------------------------------------------------------------------- #
# W4 run — the QML-root shell                                                  #
# --------------------------------------------------------------------------- #

def _grab_rect(methods: list[str], screen, r: QRect) -> dict[str, np.ndarray]:
    for m in methods:
        cap._grab(m, screen, r.x(), r.y(), r.width(), r.height())
    cap._settle(250)
    return {m: _to_array(cap._grab(m, screen, r.x(), r.y(), r.width(), r.height()))
            for m in methods}


def run_qml_root(app, args, out_dir: Path, report: dict) -> int:
    """W4: does a QQuickWindow ROOT keep its DWM material while a scene-graph item
    renders GPU content — and can QML glass be composited OVER that live plot?"""
    from PySide6.QtQuick import QQuickView, QQuickWindow  # noqa: F401

    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    w, h = min(880, avail.width() - 60), min(520, avail.height() - 120)
    x, y = avail.x() + 40, avail.y() + 60
    methods = ["grabwindow", "bitblt"]

    decoy = Decoy()
    decoy.setGeometry(x - DECOY_INFLATE, y - DECOY_INFLATE,
                      w + 2 * DECOY_INFLATE, h + 2 * DECOY_INFLATE)
    decoy.show()
    cap._settle(400)

    shell = QmlRootShell(args.kind, x, y, w, h, rhi=args.rhi, plot_impl=args.plot_impl)
    cap._settle(1400)  # scene graph up, first frames rendered
    report["qml_root"] = {"qml_errors": shell.errors,
                          "graphics": shell.graphics_info(),
                          "material_hresults": shell.apply_material(args.kind)}
    if shell.errors:
        print("QML ERRORS:", shell.errors, file=sys.stderr)

    margin = shell.margin_rect_global()
    plot_r = shell.item_rect_global("plot")
    over_r = shell.item_rect_global("overlay")
    caps: dict[str, dict[str, np.ndarray]] = {}

    # (a) material: does the transparent scene's margin track what is BEHIND it?
    decoy.set_pattern("stripes")
    cap._settle(700)
    caps["on_stripes"] = _grab_rect(methods, screen, margin)
    for m in methods:
        cap._save(cap._grab(m, screen, x - 20, y - 20, w + 40, h + 40),
                  out_dir / f"qml_root_on_stripes_{m}.png")
    decoy.set_pattern("flat")
    cap._settle(900)
    caps["on_flat"] = _grab_rect(methods, screen, margin)
    decoy.set_pattern("stripes")
    cap._settle(700)
    shell.apply_material("none")
    cap._settle(900)
    caps["off"] = _grab_rect(methods, screen, margin)
    shell.apply_material(args.kind)
    cap._settle(900)

    mat: dict = {}
    for m in methods:
        d_toggle = _delta(caps["on_stripes"][m], caps["off"][m])
        d_behind = _delta(caps["on_stripes"][m], caps["on_flat"][m])
        mat[m] = {"d_toggle": round(d_toggle, 2), "d_behind": round(d_behind, 2),
                  "mean_rgb": {k: _mean_rgb(caps[k][m]) for k in
                               ("off", "on_stripes", "on_flat")},
                  "verdict": _verdict(d_toggle, d_behind, None)}
    report["qml_root"]["material"] = mat

    # (b) overlay proof: is the glass rectangle really compositing over the LIVE plot?
    plot_only = QRect(plot_r.x() + 8, plot_r.y() + 8, int(plot_r.width() * 0.35), plot_r.height() - 16)
    over_in = QRect(over_r.x() + 10, over_r.y() + 10, over_r.width() - 20, over_r.height() - 20)
    a1 = _grab_rect(methods, screen, over_in)
    cap._settle(220)
    a2 = _grab_rect(methods, screen, over_in)
    p1 = _grab_rect(methods, screen, plot_only)
    for m in methods:
        cap._save(cap._grab(m, screen, over_in.x(), over_in.y(), over_in.width(), over_in.height()),
                  out_dir / f"qml_root_overlay_{m}.png")
    report["qml_root"]["overlay"] = {
        m: {"overlay_mean_rgb": _mean_rgb(a1[m]),
            "plot_only_mean_rgb": _mean_rgb(p1[m]),
            "overlay_temporal_delta": round(_delta(a1[m], a2[m]), 2),
            "overlay_edge_energy": round(_edge_energy(a1[m]), 2),
            "verdict": ("GLASS OVER LIVE PLOT (the running waveform is visible THROUGH "
                        "the translucent overlay: it changes between frames)"
                        if _delta(a1[m], a2[m]) > 1.0 else
                        "overlay is opaque or the plot is not visible through it")}
        for m in methods}

    # (c) isolation cost: does a punishing render item stall the whole UI?
    plot_item = shell.item("plot")
    fps_idle = shell.measure_fps(3000)
    if plot_item is not None:
        plot_item.set_busy(True)
    cap._settle(600)
    fps_busy = shell.measure_fps(3000)
    if plot_item is not None:
        plot_item.set_busy(False)
    report["qml_root"]["frame_pacing"] = {
        "fps_idle_2k_points": fps_idle, "fps_busy_120k_points": fps_busy,
        "note": ("one shared render pipeline: the busy item's cost lands on the WHOLE "
                 "window's frame rate — that is the isolation price of the scene-graph "
                 "design (a native-window island would keep its own swapchain)")}

    print("\n" + "=" * 96)
    print("W4 — QML ROOT SHELL (QQuickWindow + scene-graph FastPlot item)")
    print("=" * 96)
    print(f"QML errors: {shell.errors or 'none'}")
    print(f"graphics: {report['qml_root']['graphics']}")
    print(f"DWM HRESULTs: {report['qml_root']['material_hresults']}")
    for m in methods:
        r = mat[m]
        print(f"  [{m:10s}] material d_toggle={r['d_toggle']:<7} d_behind={r['d_behind']:<7} "
              f"off={r['mean_rgb']['off']} on_stripes={r['mean_rgb']['on_stripes']} "
              f"on_flat={r['mean_rgb']['on_flat']}")
        print(f"               -> {r['verdict']}")
    for m in methods:
        o = report["qml_root"]["overlay"][m]
        print(f"  [{m:10s}] overlay mean={o['overlay_mean_rgb']} plot_only={o['plot_only_mean_rgb']} "
              f"temporal_delta={o['overlay_temporal_delta']}")
        print(f"               -> {o['verdict']}")
    print(f"  frame pacing: idle(2k pts)={fps_idle} fps   busy(120k pts)={fps_busy} fps")
    print(f"\nartifacts: {out_dir}")
    print("=" * 96 + "\n")

    (out_dir / "spike_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.hold > 0:
        print(f"holding W4 on screen for {args.hold}s — LOOK AT THE MARGINS and at the "
              "glass rectangle over the running waveform.")
        sys.stdout.flush()
        QTimer.singleShot(args.hold * 1000, app.quit)
        app.exec()
    shell.view.close()
    decoy.close()
    return 0


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GL-island glass spike (G0).")
    ap.add_argument("--kind", default="acrylic", choices=["acrylic", "mica"])
    ap.add_argument("--canvas", default="qss", choices=["qss", "alpha0"])
    ap.add_argument("--with-qml", action="store_true",
                    help="also build W4: a QQuickView hosted via createWindowContainer")
    ap.add_argument("--qml-root", action="store_true",
                    help="W4 mode: a QQuickWindow ROOT shell whose fast-data surface is a "
                         "scene-graph item (glass CAN overlay it) — the other island design")
    ap.add_argument("--plot-impl", default="painted", choices=["painted", "sg"],
                    help="--qml-root plot item: 'sg' = QSGGeometryNode (design-correct but "
                         "SEGFAULTS ~50%% of runs in PySide6 6.11); 'painted' = QQuickPaintedItem "
                         "(stable stand-in, answers the same architectural questions)")
    ap.add_argument("--rhi", default="default", choices=["default", "d3d11", "opengl"],
                    help="Qt Quick RHI backend for --qml-root (main.py pins OpenGL today; "
                         "the GlassShell wants D3D — measure both)")
    ap.add_argument("--live-toggle", action="store_true",
                    help="reproduce the app's path: attach the backdrop AFTER show() "
                         "(WA_TranslucentBackground set post-creation)")
    ap.add_argument("--hold", type=int, default=0,
                    help="seconds to leave the windows on screen after measuring")
    args = ap.parse_args(argv)

    reason = cap.check_environment()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    if args.qml_root:
        # Qt then logs the chosen RHI backend AND the graphics adapter it opened —
        # the only cheap way to learn whether we landed on the Intel iGPU or the
        # NVIDIA dGPU on a hybrid-graphics laptop.
        os.environ.setdefault("QSG_INFO", "1")

    # Same pre-QApplication step main.py does (alpha on the DEFAULT surface).
    fmt = QSurfaceFormat.defaultFormat()
    if fmt.alphaBufferSize() < 8:
        fmt.setAlphaBufferSize(8)
        QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    reason = cap.check_environment(app)
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _REPO_ROOT / "artifacts_claude" / f"gl_island_spike_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.qml_root:
        # The availability question is itself a finding: if PySide6 could NOT expose a
        # custom scene-graph item, the scene-graph island design would be dead on
        # arrival in a pure-Python codebase (Vorschrift 3.1).
        import PySide6.QtGui as _g
        import PySide6.QtQuick as _q
        qsg = {n: hasattr(_q, n) for n in
               ("QQuickItem", "QQuickFramebufferObject", "QQuickRhiItem", "QQuickPaintedItem",
                "QSGGeometryNode", "QSGGeometry", "QSGFlatColorMaterial", "QSGRenderNode",
                "QSGSimpleTextureNode", "QSGTexture", "QSGMaterialShader")}
        qsg["QRhi (QtGui)"] = hasattr(_g, "QRhi")
        qsg["QRhiCommandBuffer (QtGui)"] = hasattr(_g, "QRhiCommandBuffer")
        report: dict = {
            "mode": "qml_root", "kind": args.kind,
            "windows_build": sys.getwindowsversion().build,  # type: ignore[attr-defined]
            "qt_platform": app.platformName(), "pyside": _pyside_version(),
            "qsg_api": qsg, "out_dir": str(out_dir),
        }
        return run_qml_root(app, args, out_dir, report)

    specs = [("W1_control", "no GL at all", "none"),
             ("W2_rtt", "QOpenGLWidget child (RTT)", "rtt"),
             ("W3_island", "QOpenGLWindow via createWindowContainer", "island")]
    if args.with_qml:
        specs.append(("W4_qml_island", "QQuickView via createWindowContainer", "qml_island"))

    win_w, win_h, x0, y0 = _layout(len(specs))
    screen = QGuiApplication.primaryScreen()

    glass_at_birth = not args.live_toggle

    report: dict = {
        "kind": args.kind, "canvas": args.canvas, "live_toggle": args.live_toggle,
        "windows_build": sys.getwindowsversion().build,  # type: ignore[attr-defined]
        "qt_platform": app.platformName(), "pyside": _pyside_version(),
        "backdrop_supported": backdrop.is_backdrop_supported(),
        "screen": {"dip": [screen.availableGeometry().width(),
                           screen.availableGeometry().height()],
                   "dpr": screen.devicePixelRatio()},
        "layout": {"win_w": win_w, "win_h": win_h, "x0": x0, "y0": y0},
        "out_dir": str(out_dir), "windows": {},
    }

    # capture_onscreen's own grabWindow-vs-BitBlt probe places its decoy at a
    # hard-coded (60, 1000) — OFF-SCREEN on this 1536x864-DIP host, which makes it
    # report variance 0.0/INCONCLUSIVE for both methods. Move it into the free band
    # BELOW our windows (in-process only; the file is not touched).
    cap._PROBE_POS = (MARGIN_X, min(y0 + win_h + 30, screen.availableGeometry().height() - 170))

    decoys: list[Decoy] = []
    wins: list[SpikeWindow] = []
    try:
        # 1) decoys first => they stay BELOW every spike window in z-order.
        for i in range(len(specs)):
            d = Decoy()
            d.setGeometry(x0 + i * (win_w + GAP) - DECOY_INFLATE, y0 - DECOY_INFLATE,
                          win_w + 2 * DECOY_INFLATE, win_h + 2 * DECOY_INFLATE)
            d.show()
            decoys.append(d)
        cap._settle(400)

        # 2) the spike windows.
        applied: dict[str, bool] = {}
        for i, (name, sub, kind) in enumerate(specs):
            w = SpikeWindow(name, sub, kind, args.canvas, win_w, win_h,
                            glass_at_birth=glass_at_birth)
            w.move(x0 + i * (win_w + GAP), y0)
            if glass_at_birth:
                applied[name] = bool(backdrop.apply_backdrop(w, args.kind, dark=True))
            w.show()
            w.raise_()
            wins.append(w)
        cap._settle(1000)  # GL contexts + first frames

        method, evidence = cap._probe_capture_method(app)
        report["capture_probe"] = {"preferred": method, "evidence": evidence}
        methods = ["grabwindow", "bitblt"]  # measure with BOTH; trust neither blindly
        for w in wins:
            w.raise_()
        cap._settle(400)

        caps: dict[str, dict[str, dict[str, np.ndarray]]] = {}

        # 3) decoy_only: lower the windows below their decoys, grab, raise again.
        for w in wins:
            w.lower()
        cap._settle(450)
        for w in wins:
            caps.setdefault(w.kind_label, {})["decoy_only"] = _grab_all(methods, w)
        for w in wins:
            w.raise_()
        cap._settle(450)

        # 4) backdrop ON (already on unless --live-toggle), decoy = stripes.
        if not glass_at_birth:
            for w in wins:
                w.set_canvas(True)
                applied[w.kind_label] = bool(backdrop.apply_backdrop(w, args.kind, dark=True))
            cap._settle(800)
        for w in wins:
            _nudge(w)
        cap._settle(600)
        for w in wins:
            caps[w.kind_label]["on_stripes"] = _grab_all(methods, w)
        _strip_shot(wins, methods, out_dir, "on_stripes", x0, y0, win_w, win_h)

        # 5) ONLY the content behind changes — z-order untouched.
        for d in decoys:
            d.set_pattern("flat")
        cap._settle(900)
        for w in wins:
            _nudge(w)
        cap._settle(600)
        for w in wins:
            caps[w.kind_label]["on_flat"] = _grab_all(methods, w)
        _strip_shot(wins, methods, out_dir, "on_flat", x0, y0, win_w, win_h)
        for d in decoys:
            d.set_pattern("stripes")
        cap._settle(600)

        diag = {w.kind_label: flush_path_diag(w) for w in wins}

        # 6) backdrop OFF -> opaque baseline.
        for w in wins:
            backdrop.apply_backdrop(w, "none")
            w.set_canvas(False)
            _nudge(w)
        cap._settle(900)
        for w in wins:
            caps[w.kind_label]["off"] = _grab_all(methods, w)
        _strip_shot(wins, methods, out_dir, "off", x0, y0, win_w, win_h)

        # ---- metrics -------------------------------------------------------
        for w in wins:
            key = w.kind_label
            entry: dict = {
                "backdrop_applied": applied.get(key),
                "child_hwnds": enum_child_hwnds(int(w.winId())),
                "qt_children": qt_child_natives(w),
                "diag": diag[key],
                "methods": {},
            }
            for m in methods:
                c = caps[key]
                d_toggle = _delta(c["on_stripes"][m], c["off"][m])
                d_behind = _delta(c["on_stripes"][m], c["on_flat"][m])
                e_ref, e_on = _edge_energy(c["decoy_only"][m]), _edge_energy(c["on_stripes"][m])
                ratio = round(e_on / e_ref, 3) if e_ref > 1e-6 else None
                entry["methods"][m] = {
                    "d_toggle": round(d_toggle, 2), "d_behind": round(d_behind, 2),
                    "edge_decoy_only": round(e_ref, 2), "edge_on_stripes": round(e_on, 2),
                    "edge_ratio": ratio,
                    "mean_rgb": {k: _mean_rgb(c[k][m]) for k in
                                 ("decoy_only", "off", "on_stripes", "on_flat")},
                    "verdict": _verdict(d_toggle, d_behind, ratio),
                }
            report["windows"][key] = entry

            for phase in ("decoy_only", "off", "on_stripes", "on_flat"):
                for m in methods:
                    a = caps[key][phase][m]
                    h, wd, _ = a.shape
                    rgb = np.ascontiguousarray(
                        np.dstack([a[:, :, 2], a[:, :, 1], a[:, :, 0]]).astype(np.uint8))
                    QImage(rgb.data, wd, h, wd * 3,
                           QImage.Format.Format_RGB888).copy().save(
                        str(out_dir / f"{key}_{phase}_{m}.png"))

        report["gpu"] = dict(_GL_STRINGS)
        (out_dir / "spike_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

        # ---- console -------------------------------------------------------
        print("\n" + "=" * 96)
        print(f"GL-ISLAND GLASS SPIKE  kind={args.kind} canvas={args.canvas} "
              f"glass_at_birth={glass_at_birth}  build={report['windows_build']} "
              f"qt={report['qt_platform']} supported={report['backdrop_supported']}")
        print(f"screen: {report['screen']['dip']} DIP @ dpr={report['screen']['dpr']}   "
              f"windows: {win_w}x{win_h} from x={x0},y={y0}")
        print(f"capture probe: {method} :: {evidence}")
        for tag, info in _GL_STRINGS.items():
            print(f"GPU [{tag}]: {info.get('GL_RENDERER')} | {info.get('GL_VENDOR')} | "
                  f"{info.get('GL_VERSION')} | ctx {info.get('ctx')}")
        print("=" * 96)
        for key, entry in report["windows"].items():
            dg = entry["diag"]
            print(f"\n### {key}   apply_backdrop -> {entry['backdrop_applied']}")
            print(f"    hwnd={dg['hwnd']} exstyle={dg['ex_style']['raw']} "
                  f"layered={dg['ex_style']['WS_EX_LAYERED']} "
                  f"noredir={dg['ex_style']['WS_EX_NOREDIRECTIONBITMAP']}")
            print(f"    WA_Translucent={dg['WA_TranslucentBackground']} "
                  f"WA_NoSysBg={dg['WA_NoSystemBackground']} "
                  f"autoFill={dg['autoFillBackground']} "
                  f"fmt_alpha={dg['format_alpha']} palette={dg['palette_window']}")
            if "gl_window" in dg:
                g = dg["gl_window"]
                print(f"    GL window: {g['class']} winId={g['winId']} "
                      f"surface={g['surface_type']} alpha={g['format_alpha']}")
            print(f"    child HWNDs: {len(entry['child_hwnds'])}")
            for c in entry["child_hwnds"]:
                print(f"      - 0x{c['hwnd']:X} class={c['class']!r} rect_px={c['rect_px']}")
            for c in entry["qt_children"]:
                print(f"      qt: {c['class']:<20} internalWinId={c['internalWinId']:<12} "
                      f"native={c['WA_NativeWindow']}")
            for m, r in entry["methods"].items():
                print(f"    [{m:10s}] d_toggle={r['d_toggle']:<7} d_behind={r['d_behind']:<7} "
                      f"edge_ratio={r['edge_ratio']}")
                print(f"       mean_rgb decoy_only={r['mean_rgb']['decoy_only']} "
                      f"off={r['mean_rgb']['off']} on_stripes={r['mean_rgb']['on_stripes']} "
                      f"on_flat={r['mean_rgb']['on_flat']}")
                print(f"       -> {r['verdict']}")
        print(f"\nartifacts: {out_dir}")
        print("=" * 96 + "\n")

        if args.hold > 0:
            # The measured windows now sit in the OFF state, and re-applying a
            # backdrop to an already-shown window is the broken path (see the
            # preapply finding). So build a FRESH set the working way — backdrop
            # attached before show() — for the eyeball.
            for w in wins:
                w.close()
            wins = []
            for i, (name, sub, kind) in enumerate(specs):
                w = SpikeWindow(name, sub, kind, args.canvas, win_w, win_h,
                                glass_at_birth=True)
                w.move(x0 + i * (win_w + GAP), y0)
                backdrop.apply_backdrop(w, args.kind, dark=True)
                w.show()
                w.raise_()
                wins.append(w)
            print(f"holding the windows on screen for {args.hold}s — LOOK AT THE MARGINS "
                  "(the wide empty band under each GL square).")
            sys.stdout.flush()
            QTimer.singleShot(args.hold * 1000, app.quit)
            app.exec()
        return 0
    finally:
        for w in wins:
            try:
                backdrop.apply_backdrop(w, "none")
                w.close()
            except Exception:
                pass
        for d in decoys:
            d.close()


if __name__ == "__main__":
    sys.exit(main())
