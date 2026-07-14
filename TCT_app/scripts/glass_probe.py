"""GLASS PROBE — does the material actually shine through the REAL app?

The GL-island spike (``scripts/spikes/gl_island_glass_spike.py``) answered the
question for *toy* windows it built itself. This script asks the same question of
the **shipped cockpit** — ``tct_gui.TCTMainWindow``, in both shells (QML chrome,
the ``run.ps1`` default, and ``-Classic``) — and it does not ask it about "the
window" as a blob: it measures a **named list of surfaces** and gives each one a
verdict.

THE METHOD (inherited from the spike — the only method that cannot lie)
----------------------------------------------------------------------
A frameless **decoy** covering the whole available desktop is shown FIRST, so it
sits behind every window we then build, painting loud magenta/cyan vertical
stripes. Each measured rect is grabbed in four states, with BOTH OS-level capture
methods (``QScreen.grabWindow`` AND a GDI ``BitBlt`` of the screen DC — reused
verbatim from ``scripts/capture_onscreen.py``; a verdict is only trusted when the
two agree):

  1. ``decoy_only``  — the app lowered below the decoy (raw stripes reference)
  2. ``on_stripes``  — material + panel-glass ON, decoy striped
  3. ``on_flat``     — same, decoy repainted flat dark (**z-order untouched** —
                       ONLY the content behind the window changed)
  4. ``off``         — backdrop "none" + panel glass off (opaque baseline)

Derived per surface (mean abs channel delta, 0..255):

  ``d_toggle``   = |on_stripes − off|      → the glass config changed these pixels at all
  ``d_behind``   = |on_stripes − on_flat|  → **the decisive one**: the surface TRACKS
                   what is behind the WINDOW. Nothing but a live see-through path
                   can do that; an opaque surface physically cannot fake it.
  ``edge_ratio`` = edge energy(on_stripes) / edge energy(decoy_only) → ≈1 means the
                   stripes arrive CRISP (an alpha hole, no material blurring them);
                   ≪1 means a real acrylic/mica material is compositing.

Verdicts: ``MATERIAL_LIVE`` / ``TRANSPARENT_HOLE`` (alpha but no material — the
"black hole" class) / ``TOKEN_ONLY`` (pixels changed, but nothing behind shows —
the pre-blended fake) / ``OPAQUE`` (nothing at all) / ``NO_CANVAS`` (the surface
does not exist: no unclaimed background to show a material in).

**Use ``--kind acrylic`` (the default) for any see-through claim.** Mica
(``DWMSBT_MAINWINDOW``) samples the *wallpaper*, not the windows behind it, so a
Mica surface is expected to score ``d_behind ≈ 0`` BY MECHANISM and land on
TOKEN_ONLY here — that is not a bug, it is what Mica is.

THE SURFACES
------------
* ``window_canvas``     — the largest region of the window's client area that no
  child covers, found by an actual coverage mask (never a hard-coded rect). This
  IS the canvas the underlay law talks about. If it does not exist, the material
  has nowhere to show and the answer is NO_CANVAS *regardless* of DWM.
* ``pane:<n>:<class>``  — every REGISTERED glass pane (``gui.panel_kit
  .registered_glass_panes()``) that can be brought on screen; the probe walks the
  tab widget to make each one visible.
* ``hazard:kill_switch`` — the bias-supply kill switch (``objectName
  "killSwitchBtn"``). **The hazard invariant, measured for the first time:** a
  danger control must show ZERO ``d_behind``. A see-through kill switch would be
  a safety defect, not a style one. Failing this is a BLOCKER.
* ``theme_dialog_canvas`` — the known-good reference. The theme editor is a
  freshly-built dialog that gets its alpha surface before it is realized, and it
  is the ONE surface Kaya has seen real blur on. If it comes out dead, the probe
  itself is broken and every other verdict here is void.
* ``detached_panel_canvas`` — a torn-off panel (``DetachableTabWidget.detach``).

Non-pixel evidence, gathered in the same run (this is what actually names the
bug): every top-level's realized ``alphaBufferSize`` (the spike's finding 2 — an
attribute set after the HWND exists yields ``-1`` and a DEAD material that still
reports S_OK), its Win32 ex-style bits (``WS_EX_LAYERED`` suppresses a material
outright), whether the live QSS even contains the ``[glassCanvas="true"]`` rules,
and — for one pane — a full **ancestor chain** with each layer's *own* background
alpha, obtained by rendering that layer alone into a transparent image
(``_bg_alpha_stats``). The first ancestor that renders ``opaque_frac == 1.0`` is
the layer that blocks the material, and it is named in the report.

RUN (real desktop session only — refuses under offscreen/minimal)
-----------------------------------------------------------------
::

    cd TCT_app
    .venv/Scripts/python.exe scripts/glass_probe.py                 # both shells
    .venv/Scripts/python.exe scripts/glass_probe.py --shell qml     # one shell
    .venv/Scripts/python.exe scripts/glass_probe.py --shell classic
    .venv/Scripts/python.exe scripts/glass_probe.py --kind mica
    .venv/Scripts/python.exe scripts/glass_probe.py --live-toggle   # the runtime-flip path

``--shell both`` (the default) re-execs ITSELF once per shell: the QML shell is
selected by ``TCT_QML_SHELL`` *and* an RHI pin that must happen before the
``QApplication`` exists (``main.py``), so the two shells cannot share a process.

SAFETY / HYGIENE
----------------
Simulation only: it refuses to build anything until every device in
``configs/devices.yaml`` is simulated (``capture_onscreen._assert_all_simulated``),
exactly like the capture harness. It snapshots and restores every
``QSettings("TCT", "TCTSetup")`` key it could touch, in a ``finally`` — a probe
run must never leave Kaya's persisted theme/backdrop/tab layout changed. It is a
MANUAL TOOL: not imported by the app, not part of the test suite (the suite runs
``QT_QPA_PLATFORM=offscreen``, which has no compositor and would refuse anyway).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# TCT_app/ and TCT_app/scripts/ on sys.path — `capture_onscreen` owns the two
# OS-level grab implementations and the settings snapshot/restore this reuses
# (imported, never forked), and the app packages must import from any cwd.
_SCRIPTS = Path(__file__).resolve().parent
_TCT_APP = _SCRIPTS.parent
_REPO_ROOT = _TCT_APP.parent
for _p in (str(_TCT_APP), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QPoint, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage,  # noqa: E402
                           QPainter, QPen, QRegion, QSurfaceFormat)
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import capture_onscreen as cap  # noqa: E402
from gui import backdrop  # noqa: E402

logger = logging.getLogger("glass_probe")

CONFIG_PATH = str(_TCT_APP / "configs" / "devices.yaml")

# mean-abs-channel-delta thresholds (0..255), same scale as the spike.
T_CHANGED = 6.0
T_UNCHANGED = 2.0
# edge_ratio above this = the stripes came through UNBLURRED (alpha hole, no
# material compositing).
T_CRISP = 0.75
# A canvas region smaller than this is not a surface, it is a seam.
MIN_CANVAS_W = 6
MIN_CANVAS_H = 6
MIN_CANVAS_AREA = 900          # DIP px² — e.g. a 12 px margin strip 75 px long

_WATCHED_TAB_TITLES_FIRST = ("Bias Supply",)   # hazard surface lives here

# Every time a window was caught moving mid-sweep (see sweep()'s drift guard).
# Non-empty = at least one number in the run was measured against a stale rect.
DRIFT: list[str] = []
# Every time a measured rect turned out to show a DIFFERENT window (occlusion).
# Non-empty = at least one number in the run is about somebody else's pixels.
OCCLUDED: list[str] = []

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_NOREDIRECTIONBITMAP = 0x00200000
WS_EX_COMPOSITED = 0x02000000


# --------------------------------------------------------------------------- #
# Surfaces                                                                     #
# --------------------------------------------------------------------------- #

@dataclass
class Surface:
    """One named, measured region of one window."""
    name: str
    kind: str                       # window_canvas | glass_pane | hazard | dialog_canvas | detached_canvas
    rect: QRect                     # GLOBAL (screen) DIP rect
    tab_index: int | None = None    # tab that must be current for this rect to be visible
    expect: str | None = None       # the invariant, if this surface has one
    note: str = ""
    caps: dict = field(default_factory=dict)   # state -> method -> ndarray


class Decoy(QWidget):
    """The content BEHIND the app: a frameless, screen-filling window shown before
    anything else (so it stays below every window we build), toggled between loud
    magenta/cyan stripes and near-black — WITHOUT ever touching z-order. A
    hide()/show() would re-raise it above the app and silently invalidate every
    ``d_behind`` in the run."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.pattern = "stripes"

    def set_pattern(self, pattern: str) -> None:
        self.pattern = pattern
        self.update()
        self.repaint()

    def paintEvent(self, event) -> None:      # noqa: N802
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
# Pixel metrics (identical maths to the spike — deliberately)                  #
# --------------------------------------------------------------------------- #

def _to_array(img) -> np.ndarray:
    if hasattr(img, "toImage"):
        img = img.toImage()
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    h, w = img.height(), img.width()
    raw = bytes(img.constBits())
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w, :3]
    return arr.astype(np.float32)   # BGR


def _delta(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None or a.shape != b.shape or a.size == 0:
        return float("nan")
    return float(np.abs(a - b).mean())


def _edge_energy(a: np.ndarray) -> float:
    """Mean horizontal gradient. The decoy's stripes are VERTICAL, so a crisp view
    of them scores high and a blurred (acrylic) view scores low."""
    if a is None or a.size == 0 or a.shape[1] < 2:
        return 0.0
    return float(np.abs(np.diff(a, axis=1)).mean())


def _mean_rgb(a: np.ndarray) -> list[float]:
    if a is None or a.size == 0:
        return [0.0, 0.0, 0.0]
    m = a.reshape(-1, 3).mean(axis=0)
    return [round(float(m[2]), 1), round(float(m[1]), 1), round(float(m[0]), 1)]


def _verdict(d_toggle: float, d_behind: float, edge_ratio: float | None) -> str:
    """d_behind is the only signal that cannot be faked: a region that changes when
    ONLY the content behind the WINDOW changed is compositing something through."""
    if any(v != v for v in (d_toggle, d_behind)):     # NaN
        return "ERROR"
    if d_behind > T_CHANGED:
        if edge_ratio is not None and edge_ratio > T_CRISP:
            return "TRANSPARENT_HOLE"                 # alpha reaches DWM, nothing blurs it
        return "MATERIAL_LIVE"
    if d_toggle > T_CHANGED:
        return "TOKEN_ONLY"                           # changed on toggle, but sees nothing behind
    if d_toggle < T_UNCHANGED and d_behind < T_UNCHANGED:
        return "OPAQUE"
    return "INCONCLUSIVE"


def _combine(verdicts: dict[str, str]) -> str:
    """Both capture methods must agree, or the verdict is not evidence."""
    vals = set(verdicts.values())
    if len(vals) == 1:
        return next(iter(vals))
    return "DISAGREE(" + ", ".join(f"{m}={v}" for m, v in sorted(verdicts.items())) + ")"


# --------------------------------------------------------------------------- #
# Structural probes — Qt/Win32 state, no pixels involved                       #
# --------------------------------------------------------------------------- #

HWND_TOPMOST = -1
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
GA_ROOT = 2


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def pin_topmost(w: QWidget) -> None:
    """Put a window in the TOPMOST band via Win32, in the order it is called.

    Why not ``Qt.WindowStaysOnTopHint``: changing window FLAGS destroys and
    re-creates the native window, which is the very thing (HWND recreation, surface
    re-negotiation) this probe is measuring. ``SetWindowPos`` touches only the
    z-order.

    Why at all: without it the run is at the mercy of Windows' foreground rules. One
    run of this probe measured — with total confidence — the pixels of **VS Code**,
    which had stayed on top of both the app and the decoy. Every number in it was
    real, reproducible, and about the wrong window."""
    try:
        ctypes.windll.user32.SetWindowPos(
            wintypes.HWND(int(w.winId())), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        logger.warning("pin_topmost failed for %s", type(w).__name__, exc_info=True)


def raise_within_topmost(w: QWidget) -> None:
    """Lift an already-topmost window to the top OF THE TOPMOST BAND (so the app
    stays above the decoy, which is topmost too)."""
    try:
        ctypes.windll.user32.SetWindowPos(
            wintypes.HWND(int(w.winId())), wintypes.HWND(HWND_TOP), 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass


def hwnd_at(global_pt: QPoint) -> int:
    """The top-level HWND actually visible at a screen point (physical px).

    The occlusion oracle. A rect is only evidence about a widget if that widget's
    window is what the OS says is on screen there."""
    dpr = _screen().devicePixelRatio()
    pt = _POINT(int(round(global_pt.x() * dpr)), int(round(global_pt.y() * dpr)))
    h = ctypes.windll.user32.WindowFromPoint(pt)
    if not h:
        return 0
    root = ctypes.windll.user32.GetAncestor(wintypes.HWND(h), GA_ROOT)
    return int(root or h)


def surface_is_visible(window: QWidget, rect: QRect) -> tuple[bool, dict]:
    """Is ``rect`` REALLY showing ``window`` right now — not something on top of it?

    Checked at the rect's centre and its four inset corners; all five must resolve
    to this window's HWND. This is the check that would have caught, in one second,
    the run this probe wasted measuring VS Code."""
    try:
        want = int(window.winId())
    except RuntimeError:
        return False, {"reason": "window gone"}
    pts = [QPoint(rect.center().x(), rect.center().y()),
           QPoint(rect.x() + 2, rect.y() + 2),
           QPoint(rect.right() - 2, rect.y() + 2),
           QPoint(rect.x() + 2, rect.bottom() - 2),
           QPoint(rect.right() - 2, rect.bottom() - 2)]
    seen = [hwnd_at(p) for p in pts]
    ok = all(h == want for h in seen)
    return ok, {"want_hwnd": f"0x{want:X}",
                "hwnd_at_points": [f"0x{h:X}" for h in seen],
                "occluded": not ok}


def _ex_style(hwnd: int) -> dict:
    ex = ctypes.windll.user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    return {"raw": f"0x{ex & 0xFFFFFFFF:08X}",
            "WS_EX_LAYERED": bool(ex & WS_EX_LAYERED),
            "WS_EX_NOREDIRECTIONBITMAP": bool(ex & WS_EX_NOREDIRECTIONBITMAP),
            "WS_EX_COMPOSITED": bool(ex & WS_EX_COMPOSITED)}


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def child_hwnds(hwnd: int) -> list[dict]:
    """Every descendant HWND of a window (class name + rect).

    The STRUCTURAL half of the QQuickWidget question. A ``QQuickWidget`` is an
    *alien* render-to-texture widget: it owns NO child HWND, it renders its scene
    into an FBO and hands the texture to the top-level's flush path — which is
    exactly the path that can cost the whole window its per-pixel alpha. A
    ``QQuickView`` in a ``createWindowContainer`` is the opposite: a real child
    window, composited by DWM on its own, which is why the GL-island spike found the
    parent keeps its material. This enumeration tells the two apart without
    believing anybody's theory."""
    out: list[dict] = []
    user32 = ctypes.windll.user32

    def _cb(h, _l):    # noqa: ANN001
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, buf, 256)
        r = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(h), ctypes.byref(r))
        out.append({"hwnd": f"0x{int(h):X}", "class": buf.value,
                    "rect_px": [r.left, r.top, r.right - r.left, r.bottom - r.top]})
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), _WNDENUMPROC(_cb), 0)
    return out


def rtt_children(win: QWidget) -> list[dict]:
    """Every QQuickWidget / QOpenGLWidget in the window, with the one fact that
    decides the flush path: does it own a native window (``internalWinId`` != 0) or
    is it an alien RTT widget? ``internalWinId`` is used deliberately —
    ``winId()`` would CREATE the native handle we are testing for, i.e. the probe
    would manufacture its own answer."""
    rows: list[dict] = []
    for child in win.findChildren(QWidget):
        name = type(child).__name__
        if name not in ("QQuickWidget", "QOpenGLWidget", "GLViewWidget"):
            continue
        get = getattr(child, "internalWinId", None)
        rows.append({
            "class": name,
            "objectName": child.objectName(),
            "visible": child.isVisible(),
            "internalWinId": int(get()) if callable(get) else -1,
            "WA_NativeWindow": bool(child.testAttribute(
                Qt.WidgetAttribute.WA_NativeWindow)),
        })
    return rows


def window_diag(win: QWidget, label: str) -> dict:
    """Everything that decides whether a material CAN composite on this window —
    read straight off Qt and Win32, before a single pixel is grabbed.

    ``alphaBufferSize`` is the load-bearing number (GL-island spike, finding 2):
    ``-1``/``0`` means Qt realized the native window without per-pixel alpha, and
    from then on DWM can attach whatever it likes — it will composite NOTHING,
    while reporting S_OK the whole way. ``winId()`` is only called on a window
    that is already realized (it is — everything here is shown), so this probe
    never manufactures the handle it is measuring."""
    handle = win.windowHandle()
    fmt = handle.format() if handle is not None else None
    req = handle.requestedFormat() if handle is not None else None
    hwnd = int(win.winId()) if handle is not None else 0
    central = None
    getter = getattr(win, "centralWidget", None)
    if callable(getter):
        central = getter()
    return {
        "label": label,
        "class": type(win).__name__,
        "hwnd": f"0x{hwnd:X}",
        "geometry_dip": [win.x(), win.y(), win.width(), win.height()],
        "alphaBufferSize": fmt.alphaBufferSize() if fmt else None,
        "requested_alphaBufferSize": req.alphaBufferSize() if req else None,
        "WA_TranslucentBackground": bool(win.testAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground)),
        "WA_NoSystemBackground": bool(win.testAttribute(
            Qt.WidgetAttribute.WA_NoSystemBackground)),
        "autoFillBackground": win.autoFillBackground(),
        "windowOpacity": round(float(win.windowOpacity()), 3),
        "palette_window": win.palette().color(
            win.backgroundRole()).name(QColor.NameFormat.HexArgb),
        "glassCanvas_property": win.property(backdrop.CANVAS_GLASS_PROPERTY),
        "central_glassCanvas_property": (
            central.property(backdrop.CANVAS_GLASS_PROPERTY) if central is not None else None),
        "central_class": type(central).__name__ if central is not None else None,
        "backdrop.window_has_material": backdrop.window_has_material(win),
        "ex_style": _ex_style(hwnd) if hwnd else None,
    }


def _bg_alpha_stats(w: QWidget) -> dict:
    """Render ONE widget's own background (no children) into a transparent image
    and report how opaque it actually paints.

    This is the honest answer to "is there an opaque layer between the pane and the
    window canvas?" — it does not ask the QSS, the palette or the attributes what
    they *intend*; it asks the widget to paint and then reads the alpha it
    produced. ``opaque_frac == 1.0`` on any ancestor means the DWM material
    physically cannot reach anything above it, no matter what the pane's own
    ``glassPane`` tint says."""
    try:
        w_px = max(1, min(int(w.width()), 48))
        h_px = max(1, min(int(w.height()), 48))
        img = QImage(w_px, h_px, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        w.render(img, QPoint(0, 0), QRegion(0, 0, w_px, h_px),
                 QWidget.RenderFlag.DrawWindowBackground)
        raw = bytes(img.constBits())
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(
            h_px, img.bytesPerLine() // 4, 4)[:, :w_px, :]
        alpha = arr[:, :, 3].astype(np.float32)      # ARGB32 little-endian -> [B,G,R,A]
        return {"alpha_mean": round(float(alpha.mean()), 1),
                "opaque_frac": round(float((alpha >= 255).mean()), 3),
                "clear_frac": round(float((alpha == 0).mean()), 3)}
    except Exception as exc:                          # a widget can refuse to render
        return {"error": f"{type(exc).__name__}: {exc}"}


def ancestor_chain(pane: QWidget, window: QWidget) -> dict:
    """Walk pane → … → window and describe every layer, bottom-up.

    The report's ``blocking_layer`` is the FIRST layer above the window canvas that
    paints fully opaque: that is the one that has to become translucent (or be
    excluded from the stack) before any pane glass can ever show a material."""
    chain: list[dict] = []
    w: QWidget | None = pane
    while w is not None:
        row = {
            "class": type(w).__name__,
            "objectName": w.objectName(),
            "visible": w.isVisible(),
            "size_dip": [w.width(), w.height()],
            "autoFillBackground": w.autoFillBackground(),
            "WA_TranslucentBackground": bool(w.testAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground)),
            "WA_NoSystemBackground": bool(w.testAttribute(
                Qt.WidgetAttribute.WA_NoSystemBackground)),
            "WA_OpaquePaintEvent": bool(w.testAttribute(
                Qt.WidgetAttribute.WA_OpaquePaintEvent)),
            "palette_window": w.palette().color(
                w.backgroundRole()).name(QColor.NameFormat.HexArgb),
            "glassPane": w.property("glassPane"),
            "glassCanvas": w.property(backdrop.CANVAS_GLASS_PROPERTY),
            "own_styleSheet": (w.styleSheet() or "")[:120],
            "background_render": _bg_alpha_stats(w),
        }
        chain.append(row)
        if w is window:
            break
        w = w.parentWidget()

    blocking = None
    for row in chain:
        stats = row["background_render"]
        if isinstance(stats, dict) and stats.get("opaque_frac", 0) >= 0.999:
            blocking = f"{row['class']}#{row['objectName'] or '-'}"
            break
    return {"chain": chain, "blocking_layer": blocking,
            "note": ("blocking_layer = the FIRST layer (from the pane outwards) that "
                     "paints a fully opaque background; a DWM material cannot reach "
                     "anything above it. None = every layer up to the window canvas "
                     "carries alpha.")}


# --------------------------------------------------------------------------- #
# Where IS the canvas? (never a hard-coded rect)                               #
# --------------------------------------------------------------------------- #

def _largest_free_rect(free: np.ndarray) -> tuple[int, int, int, int] | None:
    """Maximal all-True axis-aligned rectangle in a boolean grid (classic
    histogram/stack method). Coordinates are GRID cells (``SCAN_STEP`` DIP each),
    not pixels — the caller converts.

    ``free[y, x]`` is True where the surface under test owns the pixel (see
    :func:`_scan_owned_region`). The largest such rectangle IS the measurable
    surface — computed from the live widget tree, never hard-coded (a hard-coded
    rect is what made the old capture probe grab an off-screen (60, 1000) and call
    it evidence)."""
    h, w = free.shape
    if h == 0 or w == 0:
        return None
    heights = np.zeros(w, dtype=np.int32)
    best = (0, 0, 0, 0, 0)          # area, x, y, w, h  (grid cells)
    for y in range(h):
        heights = np.where(free[y], heights + 1, 0)
        stack: list[int] = []
        hs = heights.tolist()
        for x in range(w + 1):
            cur = hs[x] if x < w else 0
            start = x
            while stack and hs[stack[-1]] >= cur:
                i = stack.pop()
                height = hs[i]
                width = x - i
                area = height * width
                if area > best[0] and height >= 2 and width >= 2:
                    best = (area, i, y - height + 1, width, height)
                start = i
            stack.append(start)
            hs[start] = cur
    if best[0] == 0:
        return None
    return best[1], best[2], best[3], best[4]


SCAN_STEP = 4          # DIP px between childAt() samples


def _scan_owned_region(window: QWidget, area: QRect,
                       owns) -> tuple[QRect | None, dict]:
    """Largest rect inside ``area`` (window-local) where ``owns(childAt(pt))`` holds.

    **Hit-testing, not arithmetic.** The first version of this probe built the
    coverage mask from ``child.mapTo(window) + child.size()`` — and it silently
    missed the QToolBar, so the "window canvas" it measured was a 12 px band lying
    ON TOP of the toolbar buttons (a confident, fully-derived, completely wrong
    number). ``QWidget.childAt`` is Qt's own hit-test: it knows what is actually
    visible at a point, including stacking, masks and clipping. It is the only
    thing that can answer "whose pixels are these".

    (Known limit: a widget with ``WA_TransparentForMouseEvents`` that still PAINTS
    would be invisible to childAt. Nothing in the cockpit does that today; a
    surface that suddenly reads as glass without a code change should be
    re-checked against the annotated PNG.)"""
    info: dict = {"area_local": [area.x(), area.y(), area.width(), area.height()]}
    if area.width() < MIN_CANVAS_W or area.height() < MIN_CANVAS_H:
        info["reason"] = "area too small to hold a measurable surface"
        return None, info

    nx = max(1, area.width() // SCAN_STEP)
    ny = max(1, area.height() // SCAN_STEP)
    free = np.zeros((ny, nx), dtype=bool)
    for iy in range(ny):
        y = area.y() + iy * SCAN_STEP + SCAN_STEP // 2
        for ix in range(nx):
            x = area.x() + ix * SCAN_STEP + SCAN_STEP // 2
            free[iy, ix] = bool(owns(window.childAt(x, y)))

    info["free_frac"] = round(float(free.mean()), 4)
    found = _largest_free_rect(free)
    if found is None:
        info["reason"] = ("no region of this surface is exposed (its children tile "
                          "it completely) — nothing here can ever show a material")
        return None, info
    x, y, rw, rh = found
    lx = area.x() + x * SCAN_STEP
    ly = area.y() + y * SCAN_STEP
    lw, lh = rw * SCAN_STEP, rh * SCAN_STEP
    if lw * lh < MIN_CANVAS_AREA:
        info["reason"] = f"largest exposed region {lw}x{lh} is below the {MIN_CANVAS_AREA}px^2 floor"
        return None, info
    info["rect_local"] = [lx, ly, lw, lh]
    # Pull in one scan step: the outer ring of a hit-tested region straddles the
    # boundary with whatever is next to it.
    lx, ly, lw, lh = lx + 2, ly + 2, max(4, lw - 4), max(4, lh - 4)
    tl = window.mapToGlobal(QPoint(lx, ly))
    return QRect(tl.x(), tl.y(), lw, lh), info


def exposed_canvas_rect(window: QWidget) -> tuple[QRect | None, dict]:
    """The largest region of ``window``'s client area that belongs to the WINDOW
    CANVAS itself — i.e. where the topmost thing under the cursor is the window or
    (for a QMainWindow) its ``#mainShell`` central widget.

    That is precisely the surface the underlay law talks about: the only place a
    DWM material can show. ``None`` is a first-class finding — a window whose
    children tile its whole client has NO canvas, and then the DWM state does not
    matter at all."""
    canvas_layers = {window}
    getter = getattr(window, "centralWidget", None)
    if callable(getter) and getter() is not None:
        canvas_layers.add(getter())
    rect, info = _scan_owned_region(
        window, window.rect(), lambda w: w is None or w in canvas_layers)
    info["canvas_layers"] = [type(w).__name__ + "#" + (w.objectName() or "-")
                             for w in canvas_layers]
    return rect, info


def own_surface_rect(window: QWidget, widget: QWidget) -> tuple[QRect | None, dict]:
    """The largest region of ``widget`` that ``widget`` ITSELF paints — no child of
    it, nothing on top of it.

    For a glass pane this is the pane's own tinted background (measuring the pane's
    full rect would average in its opaque labels and buttons and dilute the signal);
    for the kill switch it is the button face. It also VALIDATES the widget is
    really on screen where Qt says it is: the bias kill switch's ``mapToGlobal``
    rect, taken right after a tab switch, pointed at the TAB BAR (a stale layout),
    and the probe cheerfully reported the tab bar's live material as a see-through
    kill switch — a false safety alarm. A hit-tested rect cannot do that."""
    if not widget.isVisible():
        return None, {"reason": "widget not visible"}
    top_left = widget.mapTo(window, QPoint(0, 0))
    area = QRect(top_left, widget.size()).intersected(window.rect())
    return _scan_owned_region(window, area, lambda w: w is widget)


# --------------------------------------------------------------------------- #
# Grabbing                                                                     #
# --------------------------------------------------------------------------- #

METHODS = ("grabwindow", "bitblt")


def _screen():
    """ALWAYS fetch the screen fresh — never cache the QScreen.

    Qt can destroy and re-create QScreen objects at runtime (a DPI/display-config
    change is enough, and building the cockpit was enough on this host): a stored
    reference then raises ``Internal C++ object already deleted`` in the middle of
    a sweep, taking the run with it."""
    return QGuiApplication.primaryScreen()


def _avail() -> QRect:
    return _screen().availableGeometry()


def _nudge(win: QWidget) -> None:
    """Move the window 1 px and back — the documented heal for the Qt 6.10/6.11 +
    Win11 stale-surface bug: a window can keep presenting a STALE composite after
    attribute churn until a real geometry change forces a fresh surface.
    ``update()`` is not enough; without this the same command yields different
    pixels run to run.

    ``pos()``, NOT ``geometry()``. For a top-level, ``move()`` positions the FRAME
    while ``geometry()`` returns the CLIENT rect — so ``move(geometry().topLeft())``
    walks the window DOWN by one title-bar height on every call. This probe did
    exactly that for three runs: the window crept downward between states while the
    measured rects stayed put, so the "kill switch" rect ended up over the tab bar
    and the probe reported a see-through HV kill switch (d_behind ≈ 30). A false
    safety alarm, produced by two lines of coordinate sloppiness."""
    try:
        p = win.pos()
        win.move(p.x() + 1, p.y())
        win.move(p.x(), p.y())
    except RuntimeError:
        pass


def _grab_rect(r: QRect) -> dict[str, np.ndarray]:
    screen = _screen()
    return {m: _to_array(cap._grab(m, screen, r.x(), r.y(), r.width(), r.height()))
            for m in METHODS}


def _warm_up(r: QRect) -> None:
    """Throw the first grab away. A DWM material recomposites asynchronously after
    the content behind it changes, so the first read after a state change can catch
    a stale composite (this bit the first version of the spike: two capture methods
    'disagreeing' about the same window)."""
    screen = _screen()
    for m in METHODS:
        try:
            cap._grab(m, screen, r.x(), r.y(), max(8, r.width()), max(8, r.height()))
        except Exception:
            pass
    cap._settle(200)


# --------------------------------------------------------------------------- #
# App state driving — the SAME functions the theme UI calls, never a fork      #
# --------------------------------------------------------------------------- #

class AppGlass:
    """Turn the app's glass configuration on/off through its real entry points.

    ``on()`` before the window is built = the LAUNCH path (Kaya's persisted
    preference: ``gui.style.load_theme_customization`` sets the same globals, then
    ``TCTMainWindow.__init__`` runs ``prepare_window_surface`` FIRST and
    ``reassert_window_backdrop`` last). ``on()`` on a live window = the RUNTIME
    TOGGLE path (what the theme editor's backdrop combo does:
    ``set_window_backdrop`` → ``apply_window_backdrop`` → ``apply_window_opacity``).
    Both are worth measuring, and ``--live-toggle`` picks the second."""

    def __init__(self, kind: str, panel_glass: bool, mode: str = "dark") -> None:
        from gui import panel_kit, style
        self._style = style
        self._panel_kit = panel_kit
        self.kind = kind
        self.panel_glass = panel_glass
        self.mode = mode

    def persist(self, settings) -> None:
        """Write the glass preference to QSettings BEFORE the window is built.

        Not optional, and not merely "faithful": ``TCTMainWindow.__init__`` calls
        ``load_theme_customization(self._settings)`` itself, which RE-READS
        ``theme/window_backdrop`` from the store into ``style._window_backdrop``.
        Setting only the module global here would be silently reverted by the
        window's own constructor to whatever Kaya last persisted, and the probe
        would then measure the wrong configuration and blame the app. (Restored in
        the ``finally`` — see ``cap.restore_settings``.)"""
        from gui import app_settings
        settings.setValue(app_settings.THEME_KEY, self.mode)
        settings.setValue(app_settings.THEME_WINDOW_BACKDROP_KEY, self.kind)
        settings.setValue(app_settings.THEME_PANEL_GLASS_KEY, bool(self.panel_glass))
        settings.setValue(app_settings.THEME_WINDOW_OPACITY_KEY, 1.0)
        settings.setValue(app_settings.DETACHED_TITLES_KEY, [])   # start fully docked
        settings.sync()

    def on(self, app) -> None:
        self._style.set_window_backdrop(self.kind)
        self._style.apply_theme(app, self.mode)          # rebuilds the QSS (glass canvas rules)
        self._panel_kit.set_panel_glass(self.panel_glass)
        self._style.apply_window_backdrop(app)
        self._style.apply_window_opacity(app)

    def off(self, app) -> None:
        self._style.set_window_backdrop("none")
        self._style.apply_theme(app, self.mode)
        self._panel_kit.set_panel_glass(False)
        self._style.apply_window_backdrop(app)
        self._style.apply_window_opacity(app)

    def qss_has_glass_canvas_rule(self, app) -> bool:
        return '[glassCanvas="true"]' in (app.styleSheet() or "")

    def qss_has_glass_pane_rule(self, app) -> bool:
        return '[glassPane="true"]' in (app.styleSheet() or "")


# --------------------------------------------------------------------------- #
# The sweep                                                                    #
# --------------------------------------------------------------------------- #

def _set_tab(win, index: int | None) -> None:
    if index is None:
        return
    tabs = getattr(win, "_tabs", None)
    if tabs is None or index < 0 or index >= tabs.count():
        return
    if tabs.currentIndex() != index:
        tabs.setCurrentIndex(index)
        cap._settle(220)


def _decoy_reference_rect(avail: QRect, windows: list[QWidget], w: int, h: int) -> QRect:
    """A rect of the SAME SIZE as the measured surface that lies on the bare decoy —
    no app window over it. This is the ``edge_ratio`` reference: the stripes as they
    look through nothing at all.

    It replaces the spike's "lower the window below the decoy" step, which does NOT
    survive contact with the real app: an owned dialog (``parent=self``) can never
    be stacked below its owner on Windows, so ``lower()`` silently left the window
    on top and the reference grab measured the WINDOW, not the decoy — an
    ``edge_ratio`` of exactly 1.000 on every surface (garbage that looks like data).
    A rect the windows do not cover cannot lie."""
    for corner in ("bottom_right", "bottom_left", "top_right"):
        if corner == "bottom_right":
            r = QRect(avail.right() - w - 8, avail.bottom() - h - 8, w, h)
        elif corner == "bottom_left":
            r = QRect(avail.left() + 8, avail.bottom() - h - 8, w, h)
        else:
            r = QRect(avail.right() - w - 8, avail.top() + 8, w, h)
        if all(not win.frameGeometry().intersects(r) for win in windows):
            return r
    return QRect(avail.right() - w - 8, avail.bottom() - h - 8, w, h)


def sweep(app, glass: AppGlass, decoy: Decoy, windows: list[QWidget],
          host_window, surfaces: list[Surface], out_dir: Path,
          phase: str) -> None:
    """Grab every surface in three real states + one uncovered-decoy reference.

    Z-ORDER IS NEVER TOUCHED (see :func:`_decoy_reference_rect`): the ONLY thing
    that changes between ``on_stripes`` and ``on_flat`` is what the decoy paints —
    which is exactly what makes ``d_behind`` mean something. A full-screen shot is
    saved in every state, because a probe whose own staging is wrong produces
    confident nonsense, and the screenshot is the only thing that can catch that.
    """
    # THE DRIFT GUARD. Every rect in this sweep was hit-tested ONCE, before the
    # states start; they are only valid while the windows stay exactly where they
    # were. A window that moves by even a title-bar height turns every number in
    # this report into a confident lie about the wrong widget (it did — see
    # _nudge). So: pin the positions, and check them after every state.
    home = {id(w): w.pos() for w in windows}
    subject = windows[0]        # every surface in this sweep belongs to this window

    def _hold_still(state: str) -> None:
        for w in reversed(windows):     # subject last => on top of the topmost band
            try:
                if w.pos() != home[id(w)]:
                    DRIFT.append(f"{type(w).__name__} moved from {home[id(w)]} to "
                                 f"{w.pos()} before state {state!r} — moved back")
                    w.move(home[id(w)])
                    cap._settle(150)
                raise_within_topmost(w)
            except RuntimeError:
                continue
        cap._settle(120)
        for s in surfaces:
            ok, info = surface_is_visible(subject, s.rect)
            if not ok:
                OCCLUDED.append(f"{s.name} was OCCLUDED in state {state!r}: {info}")

    def _fullscreen(state: str) -> None:
        avail = _avail()
        img = cap._grab("bitblt", _screen(), avail.x(), avail.y(),
                        avail.width(), avail.height())
        cap._save(img, out_dir / f"screen_{phase}_{state}.png")

    def _visit(state: str) -> None:
        _hold_still(state)
        by_tab: dict[int | None, list[Surface]] = {}
        for s in surfaces:
            by_tab.setdefault(s.tab_index, []).append(s)
        for tab_index, group in by_tab.items():
            if host_window is not None:
                _set_tab(host_window, tab_index)
            _warm_up(group[0].rect)
            for s in group:
                s.caps[state] = _grab_rect(s.rect)
                s.caps.setdefault("decoy_ref", {})
        _fullscreen(state)

    # 1) on_stripes — the glass config is ON (a re-assert is idempotent).
    for w in windows:
        _nudge(w)
    cap._settle(700)
    _visit("on_stripes")

    # The reference: the bare decoy, in the SAME state, in a rect no window covers.
    refs: dict[str, QRect] = {}
    for s in surfaces:
        refs[s.name] = _decoy_reference_rect(
            _avail(), windows, s.rect.width(), s.rect.height())
        s.caps["decoy_ref"] = _grab_rect(refs[s.name])

    # 2) on_flat — ONLY the content behind the window changes. Nothing else.
    decoy.set_pattern("flat")
    cap._settle(1000)
    _visit("on_flat")
    for s in surfaces:                 # the SAME reference rect, now flat
        s.caps["decoy_ref_flat"] = _grab_rect(refs[s.name])
    decoy.set_pattern("stripes")
    cap._settle(800)

    # 3) off — no material, no panel glass: the opaque baseline.
    glass.off(app)
    cap._settle(800)
    for w in windows:
        _nudge(w)
    cap._settle(700)
    _visit("off")

    # back ON, so later phases (and a --hold eyeball) see the real thing.
    glass.on(app)
    cap._settle(800)


def measure(s: Surface) -> dict:
    out: dict = {"name": s.name, "kind": s.kind, "expect": s.expect, "note": s.note,
                 "rect_dip": [s.rect.x(), s.rect.y(), s.rect.width(), s.rect.height()],
                 "methods": {}}
    verdicts: dict[str, str] = {}
    for m in METHODS:
        try:
            on_s = s.caps["on_stripes"][m]
            on_f = s.caps["on_flat"][m]
            off = s.caps["off"][m]
            ref_s = s.caps["decoy_ref"][m]
            ref_f = s.caps["decoy_ref_flat"][m]
        except KeyError:
            out["methods"][m] = {"error": "state missing"}
            verdicts[m] = "ERROR"
            continue
        d_toggle = _delta(on_s, off)
        d_behind = _delta(on_s, on_f)

        # THE DIFFERENCE IMAGE — the surface's own content cancels out.
        #
        # (on_stripes − on_flat) is EXACTLY the contribution the background makes to
        # this surface, and nothing else: every static pixel the widget itself paints
        # (its text, its borders, its tint) is identical in both states and
        # subtracts away. Comparing that against the same difference taken on the
        # BARE decoy gives two numbers that mean something on their own:
        #
        #   transmission = how much of what is behind reaches the surface (0..1)
        #   edge_ratio   = how SHARP what arrives is, relative to the raw stripes
        #                  (≈1 = crisp alpha hole; ≪1 = a material blurred it)
        #
        # The naive edge_ratio (edge energy of the raw on_stripes grab / the raw
        # decoy) is junk on any surface that has its own content: the tab bar's LABEL
        # TEXT alone pushed it to 1.69 and the probe called a blurred, material-lit
        # strip a "TRANSPARENT_HOLE". A difference image cannot be fooled that way.
        dif_s = on_s.astype(np.float32) - on_f.astype(np.float32)
        dif_r = ref_s.astype(np.float32) - ref_f.astype(np.float32)
        amp_ref = float(np.abs(dif_r).mean())
        transmission = round(d_behind / amp_ref, 3) if amp_ref > 1e-6 else None
        e_ref, e_on = _edge_energy(np.abs(dif_r)), _edge_energy(np.abs(dif_s))
        ratio = round(e_on / e_ref, 3) if e_ref > 1e-6 else None

        v = _verdict(d_toggle, d_behind, ratio)
        verdicts[m] = v
        out["methods"][m] = {
            "d_toggle": round(d_toggle, 2), "d_behind": round(d_behind, 2),
            "transmission": transmission, "edge_ratio": ratio,
            "raw_edge_energy": {"decoy_ref_delta": round(e_ref, 2),
                                "surface_delta": round(e_on, 2)},
            "mean_rgb": {k: _mean_rgb(s.caps[k][m]) for k in
                         ("decoy_ref", "off", "on_stripes", "on_flat")},
            "verdict": v,
        }
    out["verdict"] = _combine(verdicts)
    if s.expect:
        out["pass"] = out["verdict"] == s.expect
    return out


# --------------------------------------------------------------------------- #
# Artifacts                                                                    #
# --------------------------------------------------------------------------- #

_VERDICT_INK = {
    "MATERIAL_LIVE": "#39D98A",
    "TRANSPARENT_HOLE": "#FFB020",
    "TOKEN_ONLY": "#59A9FF",
    "OPAQUE": "#FF6B6B",
    "NO_CANVAS": "#FF6B6B",
}


def annotate(win: QWidget, surfaces: list[Surface], out: Path, tag: str,
             results: dict[str, dict]) -> None:
    """One screenshot of the window with every measured rect outlined and labelled
    with its verdict — so a human can check the probe measured what it claims."""
    screen = _screen()
    g = win.frameGeometry()
    img = cap._grab("bitblt", screen, g.x(), g.y(), g.width(), g.height())
    if hasattr(img, "toImage"):
        img = img.toImage()
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    dpr = screen.devicePixelRatio()
    p = QPainter(img)
    p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    for s in surfaces:
        v = results.get(s.name, {}).get("verdict", "?")
        ink = QColor(_VERDICT_INK.get(v.split("(")[0], "#E6E9EF"))
        r = QRect(int((s.rect.x() - g.x()) * dpr), int((s.rect.y() - g.y()) * dpr),
                  int(s.rect.width() * dpr), int(s.rect.height() * dpr))
        p.setPen(QPen(ink, 2))
        p.drawRect(r)
        label = f"{s.name}: {v}"
        p.fillRect(QRect(r.x(), max(0, r.y() - 16), 9 * len(label), 15), QColor(0, 0, 0, 190))
        p.drawText(r.x() + 3, max(11, r.y() - 4), label)
    p.end()
    img.save(str(out / f"annotated_{tag}.png"))


def save_crops(surfaces: list[Surface], out: Path, prefix: str) -> None:
    for s in surfaces:
        for state in ("decoy_ref", "on_stripes", "on_flat", "off"):
            a = s.caps.get(state, {}).get("bitblt")
            if a is None or a.size == 0:
                continue
            h, w, _ = a.shape
            rgb = np.ascontiguousarray(
                np.dstack([a[:, :, 2], a[:, :, 1], a[:, :, 0]]).astype(np.uint8))
            safe = s.name.replace(":", "_").replace("/", "_")
            QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy().save(
                str(out / f"{prefix}_{safe}_{state}.png"))


# --------------------------------------------------------------------------- #
# The run (one shell, one process)                                             #
# --------------------------------------------------------------------------- #

class _LogTrap(logging.Handler):
    """Capture the app's own glass verdict. ``gui.backdrop`` logs one INFO 'truth'
    line per (re-)assert and a WARNING the moment it attaches a material to a
    window with no alpha surface — that warning IS the bug, in the app's own
    words, and it belongs in the report."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith("gui."):
                self.records.append(
                    f"{record.levelname} {record.name}: {record.getMessage()}")
        except Exception:
            pass


def run_one_shell(args, out_dir: Path) -> dict:
    shell = args.shell
    qml = shell == "qml"
    os.environ["TCT_QML_SHELL"] = "1" if qml else "0"

    # main.py's own pre-QApplication steps, in main.py's order: the RHI pin (QML
    # only) and the alpha channel on the DEFAULT surface format. Both MUST happen
    # before the QApplication — that is exactly the class of ordering bug this
    # probe exists to detect, so it must not introduce one of its own.
    if qml:
        from gui.qml_shell import pin_opengl_rhi
        pin_opengl_rhi()
    fmt = QSurfaceFormat.defaultFormat()
    if fmt.alphaBufferSize() < 8:
        fmt.setAlphaBufferSize(8)
        QSurfaceFormat.setDefaultFormat(fmt)

    reason = cap.check_environment()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return {"status": "refused", "reason": reason}

    app = QApplication.instance() or QApplication(sys.argv[:1])
    reason = cap.check_environment(app)
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return {"status": "refused", "reason": reason}

    cap._assert_all_simulated(CONFIG_PATH)     # simulation only — before any device object

    trap = _LogTrap()
    logging.getLogger().addHandler(trap)
    logging.getLogger().setLevel(logging.INFO)

    from gui import app_settings, panel_kit, style
    settings = app_settings.settings()
    snapshot = cap.snapshot_settings(settings)

    avail = _avail()
    report: dict = {
        "shell": shell,
        "kind": args.kind,
        "panel_glass": bool(args.panel_glass),
        "live_toggle": bool(args.live_toggle),
        "windows_build": sys.getwindowsversion().build,   # type: ignore[attr-defined]
        "qt_platform": app.platformName(),
        "backdrop_supported": backdrop.is_backdrop_supported(),
        "screen_dip": [avail.x(), avail.y(), avail.width(), avail.height()],
        "device_pixel_ratio": _screen().devicePixelRatio(),
        # Multi-monitor is a documented trap for a screen-coordinate probe, so the
        # geometry of every screen is recorded rather than assumed.
        "screens": [{"name": s.name(),
                     "geometry": [s.geometry().x(), s.geometry().y(),
                                  s.geometry().width(), s.geometry().height()],
                     "available": [s.availableGeometry().x(), s.availableGeometry().y(),
                                   s.availableGeometry().width(),
                                   s.availableGeometry().height()],
                     "dpr": s.devicePixelRatio()}
                    for s in QGuiApplication.screens()],
        "surfaces": [], "windows": {}, "ancestors": {}, "app_log": [],
    }
    # Which OS-level grab actually SEES the DWM composite on this host — decided
    # empirically by capture_onscreen's own probe, exactly as the capture harness
    # does, instead of trusting either method blindly.
    try:
        method, evidence = cap._probe_capture_method(app)
        report["capture_probe"] = {"preferred": method, "evidence": evidence}
    except Exception as exc:
        report["capture_probe"] = {"error": f"{type(exc).__name__}: {exc}"}

    win = None
    decoy = Decoy()
    try:
        style.reset_theme_customization()
        glass = AppGlass(args.kind, args.panel_glass, mode="dark")

        # THE DECOY FIRST — shown before any app window, so it can never end up
        # above one (a re-show would silently invalidate every d_behind).
        decoy.setGeometry(avail)
        decoy.show()
        pin_topmost(decoy)          # above VS Code & friends, below the app (next)
        cap._settle(400)

        if not args.live_toggle:
            # LAUNCH path: the glass preference exists BEFORE the window is built,
            # exactly as it does when Kaya starts the app with acrylic persisted —
            # in the STORE as well as in the module globals, because the window's
            # constructor re-reads the store (see AppGlass.persist).
            glass.persist(settings)
            glass.on(app)
        else:
            settings.setValue("theme/window_backdrop", "none")
            settings.setValue(app_settings.THEME_KEY, "dark")
            settings.sync()

        from tct_gui import TCTMainWindow
        win = TCTMainWindow(config_path=CONFIG_PATH)
        w = min(1400, avail.width() - 40)
        h = min(900, avail.height() - 40)
        win.resize(w, h)
        win.move(avail.x() + 20, avail.y() + 20)
        win.show()
        win.raise_()
        pin_topmost(win)            # topmost, and AFTER the decoy => above it
        cap._settle(1200)          # panels built, first frames composited

        if args.live_toggle:
            # RUNTIME-TOGGLE path: the window is already realized when the material
            # is switched on — the case the GL-island spike says cannot work unless
            # the surface was negotiated up front.
            glass.on(app)
            cap._settle(900)

        report["qss_has_glass_canvas_rule"] = glass.qss_has_glass_canvas_rule(app)
        report["qss_has_glass_pane_rule"] = glass.qss_has_glass_pane_rule(app)
        report["windows"]["main"] = window_diag(win, "TCTMainWindow")

        # ---------------- phase 1: the main window ------------------------- #
        surfaces: list[Surface] = []
        canvas_rect, canvas_info = exposed_canvas_rect(win)
        report["windows"]["main"]["canvas_search"] = canvas_info
        if canvas_rect is not None:
            surfaces.append(Surface("window_canvas", "window_canvas", canvas_rect,
                                    note="largest region the window canvas itself owns"))

        tabs = getattr(win, "_tabs", None)
        tab_titles = [tabs.tabText(i) for i in range(tabs.count())] if tabs else []
        report["tabs"] = tab_titles

        # The hazard surface: the bias kill switch must be OPAQUE — a see-through
        # danger control is a safety defect, not a style one. Measured here for the
        # first time. The rect is HIT-TESTED (own_surface_rect), never derived from
        # mapToGlobal alone: right after a tab switch the button's mapped rect can
        # still be stale and land on the tab bar, which reads as a live material and
        # would raise a false safety alarm.
        hazard_tab = tab_titles.index("Bias Supply") if "Bias Supply" in tab_titles else None
        if hazard_tab is not None:
            _set_tab(win, hazard_tab)
            cap._settle(400)
            kill = win.findChild(QWidget, "killSwitchBtn")
            if kill is not None:
                r, hinfo = own_surface_rect(win, kill)
                report["hazard_rect_search"] = hinfo
                if r is not None and avail.contains(r):
                    surfaces.append(Surface(
                        "hazard:kill_switch", "hazard", r, tab_index=hazard_tab,
                        expect="OPAQUE",
                        note="HV kill switch — MUST NOT be see-through (hazard invariant)"))
                else:
                    report.setdefault("warnings", []).append(
                        f"kill switch not hit-testable on screen: {hinfo}")
            else:
                report.setdefault("warnings", []).append(
                    "killSwitchBtn not found — hazard invariant NOT measured")

        # The tab-bar strip. Not on the original surface list — it is on it now
        # because the first full-screen state shot showed that band coming out
        # PURPLE (a blur of the magenta/cyan decoy) while the canvas next to it
        # stayed dead. Chrome that goes see-through by accident is exactly the kind
        # of thing a per-surface probe exists to catch, so it gets measured instead
        # of admired.
        if tabs is not None:
            bar = tabs.tabBar()
            if bar is not None:
                r, binfo = own_surface_rect(win, bar)
                if r is not None and avail.contains(r):
                    surfaces.append(Surface(
                        "chrome:tab_bar", "chrome", r,
                        note="QTabBar strip — reads as translucent in the state shots"))

        # Every registered glass pane we can bring on screen. Panes live on tab
        # pages, so walk the tabs and take whichever panes become visible. The rect
        # is the pane's OWN background (its opaque labels/buttons are excluded by
        # the hit test — averaging them in would dilute d_behind toward zero and
        # make a live pane look dead).
        panes = panel_kit.registered_glass_panes()
        report["registered_glass_panes"] = [
            f"{type(p).__name__}#{p.objectName() or '-'}" for p in panes]
        seen: set[int] = set()
        for idx in range(tabs.count() if tabs else 0):
            _set_tab(win, idx)
            cap._settle(300)
            for pane in panes:
                if id(pane) in seen or pane.window() is not win or not pane.isVisible():
                    continue
                r, pinfo = own_surface_rect(win, pane)
                if r is None or not avail.contains(r):
                    continue
                seen.add(id(pane))
                surfaces.append(Surface(
                    f"pane:{tab_titles[idx]}:{type(pane).__name__}", "glass_pane", r,
                    tab_index=idx,
                    note=f"registered glass pane (objectName={pane.objectName() or '-'}; "
                         f"own-background region {pinfo.get('rect_local')})"))
                # The ancestor chain of the FIRST pane we find: the precise answer to
                # "which layer blocks the material".
                if "first_pane" not in report["ancestors"]:
                    report["ancestors"]["first_pane"] = {
                        "pane": f"{type(pane).__name__}#{pane.objectName() or '-'}",
                        **ancestor_chain(pane, win)}

        sweep(app, glass, decoy, [win], win, surfaces, out_dir, "main")
        results = {s.name: measure(s) for s in surfaces}
        if canvas_rect is None:
            results["window_canvas"] = {
                "name": "window_canvas", "kind": "window_canvas",
                "verdict": "NO_CANVAS", "rect_dip": None,
                "note": canvas_info.get("reason", "no exposed canvas")}
        report["surfaces"].extend(results.values())
        annotate(win, surfaces, out_dir, f"{shell}_main", results)
        save_crops(surfaces, out_dir, shell)

        # PARK THE COCKPIT. For phases 2 and 3 the thing behind the measured window
        # must be the DECOY — but the cockpit is 1400x825 on a 1536x864 desktop, so a
        # dialog opened on top of it samples the COCKPIT, and "change what is behind"
        # then changes almost nothing. (That is exactly why the theme dialog — the one
        # surface Kaya has actually seen blur on — first came back INCONCLUSIVE.)
        # Shrink the cockpit into a corner: it is already measured, and it must stay
        # alive because the dialog is its child.
        win.resize(360, 260)
        win.move(avail.right() - 380, avail.bottom() - 280)
        cap._settle(500)

        # ---------------- phase 2: the theme dialog (the reference) --------- #
        try:
            win._open_theme_editor()
            dlg = win._theme_editor
            dlg.move(avail.x() + 60, avail.y() + 60)
            dlg.show()
            dlg.raise_()
            pin_topmost(dlg)
            cap._settle(900)
            report["windows"]["theme_dialog"] = window_diag(dlg, "ThemeEditorDialog")
            d_rect, d_info = exposed_canvas_rect(dlg)
            report["windows"]["theme_dialog"]["canvas_search"] = d_info
            if d_rect is not None:
                dlg_surfaces = [Surface("theme_dialog_canvas", "dialog_canvas", d_rect,
                                        note="the known-good reference surface")]
                sweep(app, glass, decoy, [dlg, win], None, dlg_surfaces,
                      out_dir, "theme_dialog")
                d_results = {s.name: measure(s) for s in dlg_surfaces}
                report["surfaces"].extend(d_results.values())
                annotate(dlg, dlg_surfaces, out_dir, f"{shell}_theme_dialog", d_results)
                save_crops(dlg_surfaces, out_dir, shell)
            else:
                report["surfaces"].append({
                    "name": "theme_dialog_canvas", "kind": "dialog_canvas",
                    "verdict": "NO_CANVAS", "note": d_info.get("reason", "")})
            dlg.hide()
            cap._settle(300)
        except Exception as exc:
            report.setdefault("warnings", []).append(f"theme dialog phase failed: {exc!r}")

        # ---------------- phase 3: a detached panel ------------------------ #
        try:
            title = "Motor Stage" if "Motor Stage" in tab_titles else (
                tab_titles[0] if tab_titles else None)
            if title and tabs is not None and tabs.detach_by_title(title):
                cap._settle(700)
                entry = tabs._detached.get(title)
                det = entry[0] if entry else None
                if det is not None:
                    det.move(avail.x() + 80, avail.y() + 80)
                    det.raise_()
                    pin_topmost(det)
                    cap._settle(700)
                    report["windows"]["detached_panel"] = window_diag(
                        det, f"detached:{title}")
                    r, info = exposed_canvas_rect(det)
                    report["windows"]["detached_panel"]["canvas_search"] = info
                    if r is not None:
                        det_surfaces = [Surface("detached_panel_canvas", "detached_canvas",
                                                r, note=f"torn-off {title!r} window")]
                        sweep(app, glass, decoy, [det, win], None, det_surfaces,
                              out_dir, "detached")
                        det_results = {s.name: measure(s) for s in det_surfaces}
                        report["surfaces"].extend(det_results.values())
                        annotate(det, det_surfaces, out_dir,
                                 f"{shell}_detached", det_results)
                        save_crops(det_surfaces, out_dir, shell)
                    else:
                        report["surfaces"].append({
                            "name": "detached_panel_canvas", "kind": "detached_canvas",
                            "verdict": "NO_CANVAS", "note": info.get("reason", "")})
                tabs.redock_all()
                cap._settle(300)
        except Exception as exc:
            report.setdefault("warnings", []).append(f"detached phase failed: {exc!r}")

        report["app_log"] = trap.records[-60:]
        report["window_drift"] = list(DRIFT)      # must be empty for the run to count
        report["occlusion"] = list(OCCLUDED)     # must be empty for the run to count
        report["status"] = "done"
        if args.hold > 0:
            print(f"holding the app on screen for {args.hold}s — look at the canvas.")
            sys.stdout.flush()
            QTimer.singleShot(args.hold * 1000, app.quit)
            app.exec()
        return report
    except Exception as exc:
        import traceback
        traceback.print_exc()
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["app_log"] = trap.records[-60:]
        return report
    finally:
        logging.getLogger().removeHandler(trap)
        try:
            if win is not None:
                win.close()
        except Exception:
            pass
        decoy.close()
        cap.restore_settings(settings, snapshot)     # never leave Kaya's theme changed


# --------------------------------------------------------------------------- #
# Console table                                                                #
# --------------------------------------------------------------------------- #

_EXPLAIN = {
    "MATERIAL_LIVE": "real material: the surface tracks what is behind the window, blurred",
    "TRANSPARENT_HOLE": "ALPHA HOLE: see-through but NOT blurred — no material composites",
    "TOKEN_ONLY": "fake glass: pixels changed with the setting, but nothing behind shows",
    "OPAQUE": "nothing: the glass config does not change these pixels at all",
    "NO_CANVAS": "the surface does not exist — children tile the whole client area",
    "ERROR": "measurement failed",
    "INCONCLUSIVE": "weak signals — eyeball needed",
}


def print_table(report: dict) -> None:
    shell = report.get("shell", "?")
    print("\n" + "=" * 100)
    print(f"GLASS PROBE — shell={shell}  kind={report.get('kind')}  "
          f"panel_glass={report.get('panel_glass')}  live_toggle={report.get('live_toggle')}  "
          f"backdrop_supported={report.get('backdrop_supported')}")
    print(f"QSS carries glassCanvas rule: {report.get('qss_has_glass_canvas_rule')}   "
          f"glassPane rule: {report.get('qss_has_glass_pane_rule')}")
    print(f"capture probe: {(report.get('capture_probe') or {}).get('preferred')} :: "
          f"{(report.get('capture_probe') or {}).get('evidence')}")
    for key, w in (report.get("windows") or {}).items():
        print(f"  [{key:14s}] {w.get('class'):22s} alpha={w.get('alphaBufferSize')!s:>4}  "
              f"WA_Translucent={w.get('WA_TranslucentBackground')!s:5s}  "
              f"glassCanvas={w.get('glassCanvas_property')!s:5s}  "
              f"material={w.get('backdrop.window_has_material')!s:5s}  "
              f"layered={(w.get('ex_style') or {}).get('WS_EX_LAYERED')}")
    print("-" * 100)
    print(f"{'surface':40s} {'verdict':17s} {'d_toggle':>8s} {'d_behind':>8s} "
          f"{'transm':>7s} {'edge':>6s}  pass")
    for s in report.get("surfaces", []):
        m = (s.get("methods") or {}).get("bitblt", {})
        dt = m.get("d_toggle", "-")
        db = m.get("d_behind", "-")
        tr = m.get("transmission", "-")
        er = m.get("edge_ratio", "-")
        ok = s.get("pass")
        flag = "" if ok is None else ("PASS" if ok else "**FAIL**")
        print(f"{s['name'][:40]:40s} {s.get('verdict', '?')[:17]:17s} "
              f"{str(dt):>8s} {str(db):>8s} {str(tr):>7s} {str(er):>6s}  {flag}")
    print("-" * 100)
    seen = {s.get("verdict", "").split("(")[0] for s in report.get("surfaces", [])}
    for v in sorted(x for x in seen if x in _EXPLAIN):
        print(f"  {v:18s} {_EXPLAIN[v]}")
    anc = (report.get("ancestors") or {}).get("first_pane")
    if anc:
        print(f"\nancestor chain of {anc['pane']} (bottom-up), 'opaque' = blocks the material:")
        for row in anc["chain"]:
            br = row.get("background_render", {})
            print(f"  {row['class']:24s} #{(row['objectName'] or '-'):16s} "
                  f"alpha_mean={br.get('alpha_mean')!s:>6s} opaque_frac={br.get('opaque_frac')!s:>6s} "
                  f"glassPane={row.get('glassPane')!s:5s} glassCanvas={row.get('glassCanvas')!s}")
        print(f"  -> blocking layer: {anc.get('blocking_layer')}")
    for w in report.get("warnings", []) or []:
        print(f"  WARNING: {w}")
    for d in report.get("window_drift", []) or []:
        print(f"  DRIFT (measurement invalid): {d}")
    for o in report.get("occlusion", []) or []:
        print(f"  OCCLUDED (measurement invalid): {o}")
    print("=" * 100 + "\n")


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def _child_argv(args, shell: str, out_dir: Path) -> list[str]:
    argv = [sys.executable, str(Path(__file__).resolve()),
            "--shell", shell, "--kind", args.kind, "--out", str(out_dir)]
    if not args.panel_glass:
        argv.append("--no-panel-glass")
    if args.live_toggle:
        argv.append("--live-toggle")
    return argv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="glass_probe.py",
        description="Per-surface glass verdict for the REAL TCT app (manual, on-screen).")
    ap.add_argument("--shell", default="both", choices=["both", "qml", "classic"],
                    help="'both' (default) re-execs one child process per shell: the QML "
                         "shell needs TCT_QML_SHELL + an RHI pin set before the QApplication.")
    ap.add_argument("--kind", default="acrylic", choices=["acrylic", "mica"],
                    help="acrylic samples the WINDOWS behind (what d_behind measures); mica "
                         "samples the WALLPAPER and is expected to score d_behind~0 here.")
    ap.add_argument("--no-panel-glass", dest="panel_glass", action="store_false",
                    help="leave the experimental panel-glass switch OFF")
    ap.add_argument("--live-toggle", action="store_true",
                    help="switch the material on AFTER the window is shown (the runtime "
                         "theme-editor path) instead of before it is built (the launch path)")
    ap.add_argument("--hold", type=int, default=0,
                    help="seconds to leave the app on screen after measuring")
    ap.add_argument("--out", default="", help=argparse.SUPPRESS)   # set by the parent
    ap.set_defaults(panel_glass=True)
    args = ap.parse_args(argv)

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = _REPO_ROOT / "artifacts_claude" / f"glass_probe_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.shell != "both":
        report = run_one_shell(args, out_dir)
        (out_dir / f"glass_probe_report_{args.shell}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
        print_table(report)
        print(f"artifacts: {out_dir}")
        return 0 if report.get("status") == "done" else 1

    # Parent: one child per shell, then merge. The settings snapshot is taken here
    # too — a child that dies hard must not leave Kaya's persisted theme changed.
    from gui import app_settings
    settings = app_settings.settings()
    snapshot = cap.snapshot_settings(settings)
    merged: dict = {"probe": "glass_probe", "generated_utc": datetime.now(
        timezone.utc).isoformat(), "kind": args.kind, "shells": {}}
    try:
        for shell in ("qml", "classic"):
            print(f"\n### launching the app — shell={shell} ###", flush=True)
            proc = subprocess.run(_child_argv(args, shell, out_dir),
                                  cwd=str(_TCT_APP), timeout=600)
            path = out_dir / f"glass_probe_report_{shell}.json"
            if path.exists():
                merged["shells"][shell] = json.loads(path.read_text(encoding="utf-8"))
            else:
                merged["shells"][shell] = {"status": "no report",
                                           "returncode": proc.returncode}
    finally:
        cap.restore_settings(settings, snapshot)

    (out_dir / "glass_probe_report.json").write_text(
        json.dumps(merged, indent=2), encoding="utf-8")
    for shell, rep in merged["shells"].items():
        if isinstance(rep, dict) and rep.get("surfaces"):
            print_table(rep)
    print(f"artifacts: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
