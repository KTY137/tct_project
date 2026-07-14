"""SPIKE — minimize -> restore "kills" the DWM material. WHAT exactly died?

THE CLAIM UNDER TEST
--------------------
``scripts/spikes/qml_multieffect_glass_spike.py`` (commit bbe3b10) measured, on a
translucent ``QQuickWindow`` root with an acrylic DWM material:

    M5 after_resize            d_behind = 64.0   MATERIAL ALIVE
    M5 after_minimize_restore  d_behind =  0.0   margin = [84, 84, 84]  DEAD
    M5 after_reassert          d_behind =  0.0   margin = [84, 84, 84]  STILL DEAD

...in EVERY configuration including the plain control, and a full manual DWM
re-assert (ExtendFrame(-1) -> attr 20 -> attr 38, all S_OK) did not heal it. It
was read as a HARD BLOCKER for a QQuickWindow-root GlassShell.

Two things in that record do not fit "the window broke":

1. The saved ``control_after_restore_bitblt.png`` shows the QML scene STILL
   RENDERING (title text, striped panel, the mover) — only the TRANSPARENT
   regions went flat gray. A dead swapchain does not keep painting your scene.
2. A flat, uniform, *neutral* gray is what Windows 11 composites for a
   ``DWMSBT_*`` material it has decided not to render live — its fallback solid.
   The most common reason for that is not a broken surface. It is that the window
   is **not active**: DWM renders acrylic/mica live for the ACTIVE window and
   drops inactive ones to the fallback color.

And #2 would explain all three of the rig's observations at once — including the
weird one: a ``showMinimized()`` hands the foreground to whatever was underneath,
the process loses foreground rights, ``showNormal()`` brings the window back
VISIBLE (and topmost, via its flags) but NOT ACTIVE — and every window the
process builds afterwards comes up inactive too, which is exactly why "a config's
minimize poisoned every window built later in the same process" and why three
different configs returned byte-identical ``[84, 84, 84]``. Byte-identical is not
physics; it is a constant.

So this spike does NOT assume the surface died. It measures, at every stage:

  * ``QWindow.format().alphaBufferSize()`` and ``requestedFormat()`` — the brief's
    first hypothesis (the swapchain lost its alpha, the ORDER-LAW failure class of
    ``git show 081da40``: DWM keeps returning S_OK with nowhere to land),
  * the HWND (did Qt re-create it? Fenrir K9),
  * ``WS_EX_LAYERED`` / ``WS_EX_NOREDIRECTIONBITMAP``,
  * a ``DwmGetWindowAttribute`` read-back of attr 38 and DWMWA_CLOAKED,
  * **is the window ACTIVE / is it the foreground window**,
  * whether the SCENE is still presenting frames at all (an opaque animated beacon
    inside the window: its temporal delta is nonzero iff frames are still coming),
  * and the un-fakeable pixel signal: ``d_behind`` — does the margin change when
    the content BEHIND the window changes.

PROBES (``--probe``; each runs in its OWN process — the rig's own law)
---------------------------------------------------------------------
``lifecycle``   QQuickWindow root: baseline -> minimize/restore -> the HEAL LADDER,
                in increasing order of violence, stopping at the first thing that
                works.  ``--ladder activate_first`` (default) vs
                ``--ladder reassert_first`` (reproduces the prior spike's order, so
                "a re-assert does not heal it" is confirmed or refuted on the record
                BEFORE activation is tried).  ``--cycles N`` repeats the whole
                minimize/restore/heal cycle N times: N and variance, as required.
``activation``  THE DECISIVE ONE, and it never minimizes anything: the shell is
                alive and active; a thief window (elsewhere on screen, never
                overlapping, never above it — the shell is TOPMOST) steals the
                FOREGROUND; the shell's margin is re-measured. If the material dies
                there, minimize was never the cause, and the "blocker" is Windows 11
                rendering an inactive window's backdrop as a solid fallback.
``second``      process-wide or window-local: poison window A (minimize/restore),
                then build a fresh QQuickView B and a fresh translucent QWidget C in
                the SAME process and measure both, before and after activating them.
``app``         **THE HEADLINE.** The REAL shipped cockpit (``TCTMainWindow``),
                ``--shell classic`` or ``--shell qml``, acrylic + the Glass preset,
                driven through the same slots the Settings UI uses. Minimize,
                restore, measure; then activate (what a user's taskbar click does)
                and measure again. If the shipped app loses its material on a
                restore-and-click, that is a LIVE BUG and outranks the GlassShell
                question entirely.

RIG TRAPS (both are documented failures of the earlier harness, not theory)
--------------------------------------------------------------------------
* A ``showMinimized()`` lets another window rise BETWEEN the decoy and the window
  under test, and then you measure DWM faithfully blurring VS Code — a confident
  false positive. Countered three ways: decoy and shell are both pinned TOPMOST
  (via ``SetWindowPos``, never ``setWindowFlags`` — that re-creates the HWND, which
  is one of the things being measured), the z-order is re-asserted before every
  grab, and every measurement runs a **Win32 z-order audit** that lists any visible
  window sitting between them and overlapping the probe rect. A measurement with an
  intruder is REJECTED, not reported.
* A periodic stripe decoy is invisible to a wide blur kernel, so the decoy toggles
  between loud stripes and near-black (a LOCAL-MEAN change, which survives any
  blur), never between two phases of the same pattern.

Two independent capture methods (GDI ``BitBlt`` + ``QScreen.grabWindow``) must
AGREE, or the verdict is ``DISAGREE`` and is not evidence.

RUN (real desktop session only — refuses under offscreen/minimal)
-----------------------------------------------------------------
::

    cd TCT_app
    .venv/Scripts/python.exe scripts/spikes/qml_restore_material_spike.py --all
    .venv/Scripts/python.exe scripts/spikes/qml_restore_material_spike.py --probe activation
    .venv/Scripts/python.exe scripts/spikes/qml_restore_material_spike.py --probe app --shell classic

NOT app code. NOT imported by the app. NOT part of the test suite. Simulated
devices only (the ``app`` probe refuses to construct anything against a
non-simulated config, and snapshots/restores every QSettings key it touches).
Single host = Intel UHD iGPU, Win11 26200: a one-host result is a signal, not a
universal law.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_SPIKES = Path(__file__).resolve().parent
_SCRIPTS = _SPIKES.parent
_TCT_APP = _SCRIPTS.parent
_REPO_ROOT = _TCT_APP.parent
for _p in (str(_TCT_APP), str(_SCRIPTS), str(_SPIKES)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QPoint, QRect, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QSurfaceFormat  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import capture_onscreen as cap  # noqa: E402
from gui import backdrop  # noqa: E402  (the DWM chain — imported, never forked)

# The rig — reused verbatim from the spike whose finding is under test, so the
# numbers are directly comparable (same decoy, same metrics, same grab path).
from qml_multieffect_glass_spike import (  # noqa: E402
    DECOY_INFLATE, METHODS, PROBE_FROM_BOTTOM, PROBE_H, PROBE_INSET_X, T_CHANGED,
    T_UNCHANGED, Decoy, _delta, _edge_energy, _grab_rect, _inset, _mean_rgb,
    _save_arr, ex_style_flags)

logger = logging.getLogger("qml_restore_material_spike")

PROBES = ("lifecycle", "activation", "second", "app")
CONFIG_PATH = str(_TCT_APP / "configs" / "devices.yaml")

# --------------------------------------------------------------------------- #
# Win32 — z-order, activation, DWM read-back                                   #
# --------------------------------------------------------------------------- #

_USER32 = ctypes.windll.user32
_DWMAPI = ctypes.windll.dwmapi

HWND_TOPMOST = -1
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SW_RESTORE = 9

DWMWA_CLOAKED = 14
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def pin_topmost(hwnd: int) -> None:
    """Put a window into the TOPMOST band, in the order it is called.

    ``SetWindowPos``, deliberately NOT ``Qt.WindowStaysOnTopHint`` on a live
    window: changing window FLAGS destroys and re-creates the native window — the
    very event this spike is trying to observe. This touches z-order only."""
    try:
        _USER32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST),
                             0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        logger.warning("pin_topmost failed for 0x%X", hwnd, exc_info=True)


def lift_within_topmost(hwnd: int) -> None:
    """Lift an already-topmost window to the top of the topmost band (so the shell
    stays above the decoy, which is topmost too) — WITHOUT activating it."""
    try:
        _USER32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOP), 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass


def foreground_hwnd() -> int:
    try:
        return int(_USER32.GetForegroundWindow() or 0)
    except Exception:
        return 0


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


def active_hwnd() -> int:
    """The ACTIVE window of the foreground thread (``GetGUIThreadInfo(0)``).

    Not the same question as ``GetForegroundWindow`` — and it is the one that
    matters: Windows draws a window's frame (and, this spike says, composites its
    DWM material) in the ACTIVE style. A cheap post-hoc ``GetForegroundWindow`` was
    the first instrument here and it produced two mutually contradictory cycles,
    because it was sampled a second and a half after the pixels were."""
    info = _GUITHREADINFO()
    info.cbSize = ctypes.sizeof(_GUITHREADINFO)
    try:
        if _USER32.GetGUIThreadInfo(0, ctypes.byref(info)):
            return int(info.hwndActive or 0)
    except Exception:
        pass
    return 0


def _activation_now(hwnd: int) -> dict:
    """The activation truth AT THIS INSTANT — sampled next to every grab, never
    after the fact."""
    fg = foreground_hwnd()
    act = active_hwnd()
    return {"foreground_hwnd": f"0x{fg:X}", "active_hwnd": f"0x{act:X}",
            "is_foreground": fg == hwnd, "is_active_window": act == hwnd,
            "foreground_title": _win_title(fg)[:48] if fg else ""}


def force_foreground(hwnd: int) -> dict:
    """Try to make ``hwnd`` the foreground (ACTIVE) window and report what worked.

    Windows' foreground lock can refuse ``SetForegroundWindow`` from a process that
    is not currently in the foreground — which is precisely the state a process is
    left in after it minimizes its own window. Escalation ladder, in order:
    ``SetForegroundWindow`` -> ``ShowWindow(SW_RESTORE)`` + ``SetForegroundWindow``
    -> ``SwitchToThisWindow`` (the shell's own alt-tab entry point; undocumented but
    stable and, unlike the usual ALT-keystroke hack, it injects nothing into other
    applications' input queues — this spike must never type into Kaya's editor)."""
    tried: list[str] = []
    for name in ("SetForegroundWindow", "ShowWindow+SetForegroundWindow",
                 "SwitchToThisWindow", "AttachThreadInput+SetForegroundWindow"):
        try:
            if name == "SetForegroundWindow":
                _USER32.SetForegroundWindow(wintypes.HWND(hwnd))
            elif name == "ShowWindow+SetForegroundWindow":
                _USER32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
                _USER32.SetForegroundWindow(wintypes.HWND(hwnd))
            elif name == "SwitchToThisWindow":
                _USER32.SwitchToThisWindow(wintypes.HWND(hwnd), True)
            else:
                _attach_thread_input_activate(hwnd)
        except Exception:
            pass
        tried.append(name)
        cap._settle(250)
        if foreground_hwnd() == hwnd:
            return {"ok": True, "worked": name, "tried": tried}
    return {"ok": False, "worked": None, "tried": tried,
            "foreground_is": f"0x{foreground_hwnd():X}"}


def _attach_thread_input_activate(hwnd: int) -> None:
    """Activate ``hwnd`` by temporarily attaching this thread's input queue to the
    foreground thread's — the standard way past Windows' foreground lock.

    Needed because a process that has just minimized its own window is no longer the
    foreground process, and Windows then REFUSES its ``SetForegroundWindow`` (measured:
    all three simpler rungs returned "denied" after every minimize in this spike). The
    usual alternative — synthesising an ALT keystroke — is deliberately NOT used here:
    this spike must never inject input into whatever app currently has focus (Kaya's
    editor). ``AttachThreadInput`` injects nothing; it only shares an input queue for
    the duration of the call, and is detached in a ``finally``."""
    fg = _USER32.GetForegroundWindow()
    if not fg:
        return
    _USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                 ctypes.POINTER(wintypes.DWORD)]
    _USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
    tid_fg = _USER32.GetWindowThreadProcessId(wintypes.HWND(fg), None)
    tid_me = ctypes.windll.kernel32.GetCurrentThreadId()
    if not tid_fg or tid_fg == tid_me:
        return
    _USER32.AttachThreadInput(wintypes.DWORD(tid_me), wintypes.DWORD(tid_fg), True)
    try:
        _USER32.BringWindowToTop(wintypes.HWND(hwnd))
        _USER32.SetForegroundWindow(wintypes.HWND(hwnd))
    finally:
        _USER32.AttachThreadInput(wintypes.DWORD(tid_me), wintypes.DWORD(tid_fg), False)


def _dwm_get(hwnd: int, attr: int) -> dict:
    """``DwmGetWindowAttribute`` read-back of a DWORD attribute.

    Attr 38 (SYSTEMBACKDROP_TYPE) is documented as settable; whether it is
    *gettable* varies by build, so the HRESULT is reported alongside the value
    instead of being trusted."""
    val = ctypes.c_int(-999)
    try:
        hr = _DWMAPI.DwmGetWindowAttribute(wintypes.HWND(hwnd), wintypes.DWORD(attr),
                                           ctypes.byref(val), ctypes.sizeof(val))
        return {"hr": int(hr), "value": int(val.value)}
    except Exception as exc:
        return {"hr": None, "error": f"{type(exc).__name__}: {exc}"}


def _dwm_composition_enabled() -> bool | None:
    enabled = ctypes.c_int(0)
    try:
        hr = _DWMAPI.DwmIsCompositionEnabled(ctypes.byref(enabled))
        return bool(enabled.value) if int(hr) == 0 else None
    except Exception:
        return None


def _win_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _USER32.GetWindowTextW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def _win_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _USER32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def _win_rect(hwnd: int) -> QRect:
    r = wintypes.RECT()
    _USER32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)


GA_ROOT = 2


def hwnd_at(pt: QPoint) -> int:
    """The TOP-LEVEL window the OS says is actually visible at a screen point.

    The occlusion oracle, and the only honest one: a rect is evidence about a window
    only if that window is what is on screen there. ``WindowFromPoint`` takes PHYSICAL
    pixels, so the DIP point is scaled by the screen's devicePixelRatio first —
    forgetting that on a 250 %-scaled desktop is how a probe ends up hit-testing a
    point 2.5x too far up-left and cheerfully measuring the wrong window."""
    dpr = QGuiApplication.primaryScreen().devicePixelRatio()
    p = ctypes.wintypes.POINT(round(pt.x() * dpr), round(pt.y() * dpr))
    _USER32.WindowFromPoint.restype = wintypes.HWND
    _USER32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
    _USER32.GetAncestor.restype = wintypes.HWND
    _USER32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    h = _USER32.WindowFromPoint(p)
    if not h:
        return 0
    root = _USER32.GetAncestor(wintypes.HWND(h), GA_ROOT)
    return int(root or 0)


def zorder_intruders(top_hwnd: int, bottom_hwnd: int, probe_rect: QRect) -> list[dict]:
    """Every visible, un-cloaked window that sits BETWEEN the shell and the decoy in
    the z-order AND overlaps the probe rect.

    The rig trap this exists for, in the earlier spike's own words: a minimize let
    the terminal rise between the decoy and the glass window, so the next grab showed
    DWM faithfully blurring VS Code — "a perfect, entirely false backdrop-blur
    signal". A measurement with a non-empty list here is not evidence; it is
    REJECTED (see :func:`_measure`).

    ``EnumWindows`` enumerates top-level windows in z-order, topmost first — which
    is what makes "between" answerable at all. Physical-pixel rects from Win32 are
    compared against a physical-pixel probe rect (the DIP rect scaled by the
    screen's devicePixelRatio); mixing the two is how a probe "overlaps" nothing on
    a 250 %-scaled desktop."""
    order: list[int] = []

    def _cb(h, _l):  # noqa: ANN001
        h = int(h)
        if not _USER32.IsWindowVisible(wintypes.HWND(h)):
            return True
        cloaked = _dwm_get(h, DWMWA_CLOAKED)
        if cloaked.get("hr") == 0 and cloaked.get("value"):
            return True
        r = _win_rect(h)
        if r.width() <= 0 or r.height() <= 0:
            return True
        order.append(h)
        return True

    _USER32.EnumWindows(_WNDENUMPROC(_cb), 0)
    try:
        i_top = order.index(top_hwnd)
        i_bottom = order.index(bottom_hwnd)
    except ValueError:
        return [{"error": "shell or decoy not found in the z-order enumeration"}]
    if i_top > i_bottom:
        return [{"error": f"DECOY IS ABOVE THE SHELL (shell idx {i_top} > decoy idx "
                          f"{i_bottom}) — the measurement is inverted"}]

    dpr = QGuiApplication.primaryScreen().devicePixelRatio()
    phys = QRect(round(probe_rect.x() * dpr), round(probe_rect.y() * dpr),
                 round(probe_rect.width() * dpr), round(probe_rect.height() * dpr))
    out: list[dict] = []
    for h in order[i_top + 1:i_bottom]:
        r = _win_rect(h)
        if r.intersects(phys):
            out.append({"hwnd": f"0x{h:X}", "title": _win_title(h)[:60],
                        "class": _win_class(h)[:40],
                        "rect": [r.x(), r.y(), r.width(), r.height()]})
    return out


# --------------------------------------------------------------------------- #
# The QML scene — a transparent root + an OPAQUE ANIMATED BEACON               #
# --------------------------------------------------------------------------- #
#
# The beacon is the whole trick that separates the two failure modes the prior
# spike could not tell apart:
#
#   * if the SWAPCHAIN/scene graph died, the beacon stops changing (no frames);
#   * if only the MATERIAL died, the beacon keeps animating happily while the
#     transparent margin goes flat.
#
# The prior spike's own after-restore PNG already hints at the second (the scene
# still renders) — this measures it instead of eyeballing it.

_QML = """
import QtQuick

Item {
    id: root
    property string tag: ""

    Text {
        x: 24; y: 18; color: "#E6E9EF"; font.pixelSize: 13; font.bold: true
        text: "qml_restore_material_spike — " + root.tag
    }

    // OPAQUE beacon with a continuously animated dot: proof-of-frames.
    Rectangle {
        objectName: "beacon"
        x: root.width - 240; y: 44; width: 200; height: 96; radius: 8
        color: "#FF3B30"
        Rectangle {
            width: 28; height: 28; radius: 14; color: "#FFE066"
            y: 34
            SequentialAnimation on x {
                loops: Animation.Infinite
                NumberAnimation { from: 8; to: 164; duration: 800 }
                NumberAnimation { from: 164; to: 8; duration: 800 }
            }
        }
    }

    // Everything else is TRANSPARENT — the root never paints a background, so the
    // margin band at the bottom is pure DWM material (or pure fallback).
}
"""


# --------------------------------------------------------------------------- #
# Targets — one adapter over "a QQuickWindow" and "a QWidget top-level"        #
# --------------------------------------------------------------------------- #

def _widget_nudge(w: QWidget) -> None:
    """1 px move and back on a QWIDGET — the stale-surface heal, done in FRAME
    coordinates.

    ``QWidget.move()`` positions the FRAME; ``QWidget.geometry()`` returns the CLIENT
    rect. Feeding one into the other walks the window down by one title-bar height on
    every call — and this function is called four times per measurement. MEASURED
    (app probe, second run): the cockpit marched 58 px down the screen per stage, the
    probe rect slid off its canvas onto an opaque panel, and the harness reported a
    confident, entirely fictitious ``d_behind=70.2``. ``pos()`` IS the frame position;
    that is the whole fix."""
    p = w.pos()
    w.move(p.x() + 1, p.y())
    cap._settle(60)
    w.move(p.x(), p.y())
    cap._settle(120)


class Target:
    """Everything a measurement needs from the window under test."""

    label = "target"

    # --- identity / state -------------------------------------------------- #
    def qwindow(self):
        raise NotImplementedError

    @property
    def hwnd(self) -> int:
        h = self.qwindow()
        return int(h.winId()) if h is not None else 0

    def geometry(self) -> QRect:
        raise NotImplementedError

    def probe_rect(self) -> QRect:
        """The band whose pixels ARE the material (no scene content ever paints
        here)."""
        g = self.geometry()
        top = g.y() + g.height() - PROBE_FROM_BOTTOM
        return QRect(g.x() + PROBE_INSET_X, top, g.width() - 2 * PROBE_INSET_X, PROBE_H)

    # --- verbs ------------------------------------------------------------- #
    def nudge(self) -> None:
        raise NotImplementedError

    def lift(self) -> None:
        lift_within_topmost(self.hwnd)

    def activate(self) -> dict:
        w = self.qwindow()
        if w is not None:
            w.requestActivate()
        cap._settle(220)
        if foreground_hwnd() == self.hwnd:
            return {"ok": True, "worked": "QWindow.requestActivate", "tried": ["requestActivate"]}
        res = force_foreground(self.hwnd)
        res["tried"] = ["requestActivate"] + res.get("tried", [])
        return res

    def reassert(self, kind: str = "acrylic") -> dict:
        """The full ordered DWM chain on the CURRENT hwnd — gui/backdrop.py's own
        primitives, in gui/backdrop.py's own order. Imported, never forked."""
        hwnd = self.hwnd
        sbt = {"acrylic": backdrop.DWMSBT_TRANSIENTWINDOW,
               "mica": backdrop.DWMSBT_MAINWINDOW,
               "none": backdrop.DWMSBT_NONE}[kind]
        hr_extend = backdrop._dwm_extend_frame(hwnd)
        hr_dark = backdrop._dwm_set_window_attribute(
            hwnd, backdrop.DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
        hr_attr = backdrop._dwm_set_window_attribute(
            hwnd, backdrop.DWMWA_SYSTEMBACKDROP_TYPE, sbt)
        return {"kind": kind, "hwnd": f"0x{hwnd:X}", "hr_extend_frame": hr_extend,
                "hr_attr20_dark": hr_dark, "hr_attr38_material": hr_attr}

    # --- state snapshot ---------------------------------------------------- #
    def state(self) -> dict:
        w = self.qwindow()
        hwnd = self.hwnd
        fmt_alpha = req_alpha = None
        active = exposed = None
        if w is not None:
            try:
                fmt_alpha = int(w.format().alphaBufferSize())
                req_alpha = int(w.requestedFormat().alphaBufferSize())
                active = bool(w.isActive())
                exposed = bool(w.isExposed())
            except Exception:
                pass
        fg = foreground_hwnd()
        act = active_hwnd()
        return {
            "hwnd": f"0x{hwnd:X}",
            "is_active_window": act == hwnd,
            "active_hwnd": f"0x{act:X}",
            # THE brief's first hypothesis, measured: 8 -> -1 would mean the surface
            # came back without an alpha channel and no re-assert could ever land.
            "surface_alphaBufferSize": fmt_alpha,
            "requested_alphaBufferSize": req_alpha,
            "is_active": active,
            "is_foreground": fg == hwnd,
            "foreground_hwnd": f"0x{fg:X}",
            "foreground_title": _win_title(fg)[:60] if fg else "",
            "is_exposed": exposed,
            "ex_style": ex_style_flags(hwnd) if hwnd else None,
            "dwm_attr38_readback": _dwm_get(hwnd, backdrop.DWMWA_SYSTEMBACKDROP_TYPE),
            "dwm_cloaked": _dwm_get(hwnd, DWMWA_CLOAKED),
            "dwm_composition_enabled": _dwm_composition_enabled(),
        }


class QmlTarget(Target):
    """A translucent ``QQuickView`` top-level with a DWM material — the GlassShell
    endpoint's shape, in miniature."""

    def __init__(self, tag: str, x: int, y: int, w: int, h: int) -> None:
        from PySide6.QtQuick import QQuickView, QQuickWindow

        QQuickWindow.setDefaultAlphaBuffer(True)   # BEFORE the window exists
        tmp = Path(tempfile.gettempdir()) / "tct_qml_restore_spike.qml"
        tmp.write_text(_QML, encoding="utf-8")

        self.label = f"QQuickView[{tag}]"
        self.view = QQuickView()
        self.view.setTitle(f"qml_restore_material_spike — {tag}")
        # Topmost as a QT FLAG, set BEFORE the HWND exists — not only via
        # SetWindowPos. MEASURED (this spike's first run): a Win32-only topmost pin
        # does NOT survive on a QQuickWindow. Qt re-applies the z-band from its own
        # flags on the next geometry change, silently demoting the window BELOW the
        # decoy — and then every d_behind in the run is the DECOY's own pixels
        # (d_behind=123, frac=1.0: a beautiful, entirely false "material alive").
        # The z-order audit caught it; this is the fix. Setting the flag before
        # creation is safe — it is only a setFlags() on a LIVE window that re-creates
        # the HWND (Fenrir K9), which is one of the things under test here.
        self.view.setFlags(self.view.flags() | Qt.WindowType.WindowStaysOnTopHint)
        self.view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.view.setColor(QColor(0, 0, 0, 0))     # transparent scene clear
        self.view.setGeometry(x, y, w, h)
        self.view.setInitialProperties({"tag": tag})
        self.view.setSource(QUrl.fromLocalFile(str(tmp)))
        self.errors = [str(e) for e in self.view.errors()]

        # Scene-graph lifecycle counters. If minimize/restore tears the SG (and with
        # it the RHI swapchain) down and back up, THIS is where it shows — and the
        # rebuilt swapchain is the brief's "lost its alpha channel" suspect.
        self.sg_init = 0
        self.sg_invalidated = 0
        self.frames = 0
        self.view.sceneGraphInitialized.connect(self._on_sg_init)
        self.view.sceneGraphInvalidated.connect(self._on_sg_inv)
        self.view.frameSwapped.connect(self._on_frame)

        self.view.show()
        cap._settle(400)
        pin_topmost(int(self.view.winId()))
        cap._settle(200)
        self.material = self.reassert("acrylic")

    def _on_sg_init(self) -> None:
        self.sg_init += 1

    def _on_sg_inv(self) -> None:
        self.sg_invalidated += 1

    def _on_frame(self) -> None:
        self.frames += 1

    def qwindow(self):
        return self.view

    def geometry(self) -> QRect:
        return self.view.geometry()

    def nudge(self) -> None:
        g = self.view.geometry()
        self.view.setX(g.x() + 1)
        cap._settle(40)
        self.view.setX(g.x())
        cap._settle(80)

    def beacon_rect(self) -> QRect | None:
        from PySide6.QtQuick import QQuickItem
        root = self.view.rootObject()
        if root is None:
            return None
        it = root.findChild(QQuickItem, "beacon")
        if it is None:
            return None
        scene = it.mapToScene(it.boundingRect().topLeft())
        tl = self.view.mapToGlobal(QPoint(int(scene.x()), int(scene.y())))
        return _inset(QRect(tl.x(), tl.y(), int(it.width()), int(it.height())), 6)

    def fps_over(self, ms: int) -> float:
        self.frames = 0
        cap._settle(ms)
        return round(self.frames * 1000.0 / ms, 1)

    def state(self) -> dict:
        s = super().state()
        s["sg_initialized_count"] = self.sg_init
        s["sg_invalidated_count"] = self.sg_invalidated
        return s

    def close(self) -> None:
        try:
            self.reassert("none")
        except Exception:
            pass
        self.view.close()


class WidgetTarget(Target):
    """A plain translucent ``QWidget`` top-level with a DWM material — the SHIPPED
    shape (a QWidget root), applied through ``gui/backdrop.py``'s public API."""

    def __init__(self, tag: str, x: int, y: int, w: int, h: int) -> None:
        self.label = f"QWidget[{tag}]"
        self.w = QWidget()
        self.w.setWindowTitle(f"qml_restore_material_spike — {tag}")
        self.w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)  # before create
        # Alpha SURFACE before the HWND exists — the ORDER LAW (081da40). A widget
        # realized first can never composite, and would fake a "material dead".
        backdrop.prepare_surface(self.w)
        self.w.setGeometry(x, y, w, h)
        self.w.show()
        cap._settle(300)
        pin_topmost(int(self.w.winId()))
        self.applied = backdrop.apply_backdrop(self.w, "acrylic", dark=True)

    def qwindow(self):
        return self.w.windowHandle()

    def geometry(self) -> QRect:
        return self.w.frameGeometry()

    def nudge(self) -> None:
        _widget_nudge(self.w)

    def state(self) -> dict:
        s = super().state()
        s["backdrop_window_has_material"] = backdrop.window_has_material(self.w)
        s["glassCanvas_property"] = self.w.property(backdrop.CANVAS_GLASS_PROPERTY)
        return s

    def close(self) -> None:
        try:
            backdrop.apply_backdrop(self.w, "none")
        except Exception:
            pass
        self.w.close()


class AppTarget(Target):
    """The REAL shipped cockpit — ``TCTMainWindow``, acrylic + Glass preset, driven
    through the same slots the Settings/Theme UI uses (``capture_onscreen`` owns
    that path; this does not re-implement it)."""

    def __init__(self, win, canvas_rect: QRect | None) -> None:
        self.label = "TCTMainWindow"
        self.win = win
        # Stored WINDOW-RELATIVE, never as a global rect. A global rect captured
        # before a minimize is a rect about the DESKTOP afterwards: Windows restores
        # a window at a slightly different frame origin, the cached rect slides off
        # the canvas, and the probe reads the decoy at full strength (measured:
        # d_behind=146.13 of raw stripes — a spectacular false "material alive").
        self._canvas_local: QRect | None = None
        if canvas_rect is not None:
            g = win.frameGeometry()
            self._canvas_local = QRect(canvas_rect.x() - g.x(), canvas_rect.y() - g.y(),
                                       canvas_rect.width(), canvas_rect.height())

    def qwindow(self):
        return self.win.windowHandle()

    def geometry(self) -> QRect:
        return self.win.frameGeometry()

    def probe_rect(self) -> QRect:
        """The window's own CANVAS (the region the material is supposed to show
        through), recomputed from LIVE window geometry every time; otherwise the whole
        window — where the changed-pixel FRACTION, not the mean, carries the signal (a
        cockpit is mostly opaque panels, and a mean over them dilutes a live canvas to
        nothing)."""
        g = self.geometry()
        if self._canvas_local is not None:
            return QRect(g.x() + self._canvas_local.x(), g.y() + self._canvas_local.y(),
                         self._canvas_local.width(), self._canvas_local.height())
        return _inset(g, 10)

    def nudge(self) -> None:
        _widget_nudge(self.win)

    def state(self) -> dict:
        s = super().state()
        s["backdrop_window_has_material"] = backdrop.window_has_material(self.win)
        s["glassCanvas_property"] = self.win.property(backdrop.CANVAS_GLASS_PROPERTY)
        central = self.win.centralWidget()
        if central is not None:
            s["central_glassCanvas_property"] = central.property(
                backdrop.CANVAS_GLASS_PROPERTY)
        return s


# --------------------------------------------------------------------------- #
# The measurement                                                              #
# --------------------------------------------------------------------------- #

def _restack(decoy: Decoy, target: Target) -> None:
    """Re-assert the ONLY z-order this experiment may assume: decoy directly behind
    the target, both above everything else.

    ``SetWindowPos(HWND_TOPMOST)`` on each in turn — decoy first, target last, so the
    target ends up on top of it. Called AFTER every geometry change and immediately
    before every grab, because Qt re-applies its own z-band on a geometry change and
    will happily drop a Win32-pinned window out from under you (measured — see
    QmlTarget's comment)."""
    pin_topmost(int(decoy.winId()))
    cap._settle(100)
    pin_topmost(target.hwnd)
    cap._settle(180)


def _frac_changed(a: np.ndarray, b: np.ndarray, thresh: float = 10.0) -> float:
    """Fraction of pixels whose max channel delta exceeds ``thresh``.

    The mean delta is the right metric for a pure-material band; it is the WRONG one
    for the cockpit, which is 95 % opaque panels — a live glass gap moves the mean by
    almost nothing. This is what answers "did ANY pixel of this window track what is
    behind it"."""
    if a is None or b is None or a.shape != b.shape or a.size == 0:
        return float("nan")
    return float((np.abs(a - b).max(axis=2) > thresh).mean())


def _verdict(d_behind: float) -> str:
    if d_behind != d_behind:                      # NaN
        return "ERROR"
    if d_behind > T_CHANGED:
        return "MATERIAL ALIVE"
    if d_behind < T_UNCHANGED:
        return "MATERIAL DEAD"
    return "INCONCLUSIVE"


def _measure(target: Target, decoy: Decoy, stage: str, out_dir: Path | None = None,
             save: bool = False) -> dict:
    """``d_behind``: does the probe rect change when ONLY the content BEHIND the
    window changes? The one signal that cannot be faked by a tint, a fallback color,
    or a re-assert that returned S_OK.

    Rejects itself if any window sneaked between the decoy and the target."""
    screen = QGuiApplication.primaryScreen()
    rect = target.probe_rect()

    # ORDER MATTERS: nudge (a real geometry change — the documented heal for the
    # Qt 6.11/Win11 stale-surface bug) FIRST, restack SECOND, grab LAST. The nudge is
    # exactly what makes Qt re-apply its z-band, so a restack before it is worthless.
    decoy.set_pattern("stripes")
    target.nudge()
    _restack(decoy, target)
    cap._settle(420)
    rect = target.probe_rect()          # LIVE geometry, never a rect cached before a
                                        # lifecycle event — a minimize/restore can move
                                        # or resize the window, and then a cached rect
                                        # measures the DESKTOP and calls it the window
                                        # (it did: app_classic, first run, d_behind=146
                                        # of pure decoy stripes).
    intruders = zorder_intruders(target.hwnd, int(decoy.winId()), rect)
    # The occlusion oracle: is the target REALLY the window on screen at this rect?
    center = QPoint(rect.x() + rect.width() // 2, rect.y() + rect.height() // 2)
    hwnd_there = hwnd_at(center)
    act_at_stripes = _activation_now(target.hwnd)     # sampled NEXT TO the pixels
    on_stripes = _grab_rect(screen, rect)

    decoy.set_pattern("flat")
    target.nudge()
    _restack(decoy, target)
    cap._settle(620)
    # The window must not have MOVED between the two grabs, or the two images are of
    # different parts of it and their difference is not a measurement of anything.
    rect_now = target.probe_rect()
    moved = rect_now != rect
    act_at_flat = _activation_now(target.hwnd)
    on_flat = _grab_rect(screen, rect)

    decoy.set_pattern("stripes")
    _restack(decoy, target)
    cap._settle(300)

    entry: dict = {
        "stage": stage,
        "probe_rect": [rect.x(), rect.y(), rect.width(), rect.height()],
        "state": target.state(),
        "activation_at_stripes_grab": act_at_stripes,
        "activation_at_flat_grab": act_at_flat,
        "zorder_intruders": intruders,
        "hwnd_on_screen_at_probe": f"0x{hwnd_there:X}",
        "probe_hits_target": hwnd_there == target.hwnd,
        "window_moved_between_grabs": moved,
        "per_method": {},
    }
    for m in METHODS:
        a, b = on_stripes[m], on_flat[m]
        d = _delta(a, b)
        entry["per_method"][m] = {
            "d_behind_stripes_vs_flat": round(d, 2),
            "frac_pixels_changed": round(_frac_changed(a, b), 4),
            "mean_rgb_stripes": _mean_rgb(a),
            "mean_rgb_flat": _mean_rgb(b),
            "edge_energy": round(_edge_energy(a), 2),
            "verdict": _verdict(d),
        }
    verdicts = {m: entry["per_method"][m]["verdict"] for m in METHODS}
    if moved:
        entry["verdict"] = (f"REJECTED (the window MOVED between the two grabs: "
                            f"{[rect.x(), rect.y()]} -> {[rect_now.x(), rect_now.y()]} — "
                            f"the two images are of different pixels)")
    elif intruders:
        entry["verdict"] = "REJECTED (a window sat between the decoy and the target)"
    elif hwnd_there != target.hwnd:
        entry["verdict"] = (f"REJECTED (the window on screen at the probe rect is "
                            f"0x{hwnd_there:X}, not the target 0x{target.hwnd:X} — this "
                            f"measurement is about some other window)")
    elif len(set(verdicts.values())) == 1:
        entry["verdict"] = next(iter(verdicts.values()))
    else:
        entry["verdict"] = "DISAGREE(" + ", ".join(
            f"{m}={v}" for m, v in sorted(verdicts.items())) + ")"

    if save and out_dir is not None:
        g = target.geometry()
        for m in METHODS:
            cap._save(cap._grab(m, screen, g.x() - 16, g.y() - 16,
                                g.width() + 32, g.height() + 32),
                      out_dir / f"{stage}_full_{m}.png")
            if on_stripes[m] is not None:
                _save_arr(on_stripes[m], out_dir / f"{stage}_probe_{m}.png")
    return entry


def _beacon_alive(target: QmlTarget, out_dir: Path | None = None,
                  stage: str = "") -> dict:
    """Is the SCENE still presenting frames? (Two grabs of the animated beacon,
    ~180 ms apart: a nonzero temporal delta means the swapchain is very much alive
    and the window is still being composited — which is the difference between "the
    surface died" and "only the material did".)"""
    screen = QGuiApplication.primaryScreen()
    r = target.beacon_rect()
    if r is None:
        return {"error": "beacon item not found"}
    a = _grab_rect(screen, r)
    cap._settle(180)
    b = _grab_rect(screen, r)
    out = {m: {"temporal_delta": round(_delta(a[m], b[m]), 2),
               "mean_rgb": _mean_rgb(a[m])} for m in METHODS}
    out["fps_over_1s"] = target.fps_over(1000)
    if out_dir is not None and a["bitblt"] is not None:
        _save_arr(a["bitblt"], out_dir / f"{stage}_beacon_bitblt.png")
    return out


# --------------------------------------------------------------------------- #
# PROBE 1 — lifecycle: minimize/restore + the heal ladder                       #
# --------------------------------------------------------------------------- #

LADDERS = {
    # Cheapest first. If activation heals it, everything below is moot AND the
    # "blocker" was never a blocker.
    "activate_first": ["activate", "reassert", "material_toggle", "resize",
                       "hide_show", "recreate_native"],
    # The prior spike's order: prove (or refute) "a full re-assert does not heal it"
    # on the record BEFORE activation is allowed to confound it.
    "reassert_first": ["reassert", "material_toggle", "resize", "hide_show",
                       "activate", "recreate_native"],
}


def _apply_heal(target: QmlTarget, step: str) -> dict:
    """One rung of the heal ladder. Returns what it did (and its HRESULTs)."""
    if step == "activate":
        res = target.activate()
        cap._settle(400)
        return res
    if step == "reassert":
        # The exact chain gui/backdrop.py runs (ExtendFrame -> attr 20 -> attr 38),
        # followed by the stale-surface heal it pairs with (a real geometry change;
        # backdrop.nudge_repaint itself is QWidget-only, so this is its QWindow
        # equivalent — a 1 px move and back).
        res = target.reassert("acrylic")
        target.nudge()
        cap._settle(400)
        return res
    if step == "material_toggle":
        off = target.reassert("none")
        cap._settle(500)
        on = target.reassert("acrylic")
        target.nudge()
        cap._settle(500)
        return {"off": off, "on": on}
    if step == "resize":
        g = target.view.geometry()
        target.view.resize(g.width() + 48, g.height() + 32)
        cap._settle(500)
        target.view.resize(g.width(), g.height())
        cap._settle(500)
        return {"resized": [g.width(), g.height()]}
    if step == "hide_show":
        target.view.hide()
        cap._settle(500)
        target.view.show()
        cap._settle(700)
        pin_topmost(target.hwnd)
        return {"hwnd_after": f"0x{target.hwnd:X}"}
    if step == "recreate_native":
        # The most violent option: destroy and re-create the native handle. This is
        # what gui/backdrop.py::_renegotiate_alpha_surface REFUSES to do on a VISIBLE
        # window (it would take the window's native children with it). Legal here
        # because this shell has none — and the point is to find out whether it even
        # helps before anyone argues for relaxing that refusal.
        before = target.hwnd
        target.view.destroy()
        cap._settle(300)
        target.view.create()
        target.view.show()
        cap._settle(800)
        pin_topmost(target.hwnd)
        res = target.reassert("acrylic")
        cap._settle(500)
        return {"hwnd_before": f"0x{before:X}", "hwnd_after": f"0x{target.hwnd:X}",
                "reassert": res}
    raise ValueError(f"unknown heal step {step!r}")


def probe_lifecycle(decoy: Decoy, out_dir: Path, geom: tuple[int, int, int, int],
                    ladder: str, cycles: int) -> dict:
    x, y, w, h = geom
    target = QmlTarget("lifecycle", x, y, w, h)
    cap._settle(1000)
    report: dict = {"probe": "lifecycle", "ladder": ladder, "cycles": cycles,
                    "qml_errors": target.errors,
                    "material_hresults": target.material,
                    "baseline": {}, "cycle_results": []}
    try:
        report["baseline"] = _measure(target, decoy, "baseline", out_dir, save=True)
        report["baseline_beacon"] = _beacon_alive(target, out_dir, "baseline")

        for c in range(cycles):
            entry: dict = {"cycle": c}
            target.view.showMinimized()
            cap._settle(1000)
            target.view.showNormal()
            cap._settle(1200)
            pin_topmost(target.hwnd)
            cap._settle(200)

            tag = f"c{c}_after_restore"
            entry["after_restore"] = _measure(target, decoy, tag, out_dir,
                                              save=(c == 0))
            entry["after_restore_beacon"] = _beacon_alive(
                target, out_dir if c == 0 else None, tag)

            entry["heal"] = []
            healed_by = None
            for step in LADDERS[ladder]:
                action = _apply_heal(target, step)
                m = _measure(target, decoy, f"c{c}_heal_{step}",
                             out_dir, save=(c == 0))
                entry["heal"].append({"step": step, "action": action,
                                      "measurement": m})
                if m["verdict"] == "MATERIAL ALIVE":
                    healed_by = step
                    break
            entry["healed_by"] = healed_by
            if healed_by is not None:
                cap._settle(400)
                entry["confirm_after_heal"] = _measure(
                    target, decoy, f"c{c}_confirm", out_dir, save=(c == 0))
                entry["confirm_beacon"] = _beacon_alive(target, None, tag)
            entry["not_tried"] = [s for s in LADDERS[ladder]
                                  if s not in [h["step"] for h in entry["heal"]]]
            report["cycle_results"].append(entry)
        return report
    finally:
        target.close()
        cap._settle(300)


# --------------------------------------------------------------------------- #
# PROBE 2 — activation: the decisive experiment (NOTHING is ever minimized)     #
# --------------------------------------------------------------------------- #

class Thief(QWidget):
    """A small opaque window, far from the shell and the decoy, whose only job is to
    STEAL THE FOREGROUND. It is NOT topmost, so it can never rise above the shell and
    can never occlude the probe rect: the ONLY thing it changes is which window
    Windows considers active."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("thief — steals the foreground, occludes nothing")
        self.setStyleSheet("background-color: #1E90FF;")


def probe_activation(decoy: Decoy, out_dir: Path,
                     geom: tuple[int, int, int, int]) -> dict:
    x, y, w, h = geom
    target = QmlTarget("activation", x, y, w, h)
    cap._settle(1000)
    report: dict = {"probe": "activation", "qml_errors": target.errors,
                    "material_hresults": target.material, "steps": []}
    thief = None
    try:
        report["baseline_activation"] = target.activate()
        cap._settle(400)
        report["steps"].append(_measure(target, decoy, "act0_active_baseline",
                                        out_dir, save=True))

        # ---- steal the foreground. No minimize, no resize, no re-assert. -----
        avail = QGuiApplication.primaryScreen().availableGeometry()
        thief = Thief()
        thief.setGeometry(avail.right() - 300, avail.bottom() - 190, 260, 150)
        thief.show()
        cap._settle(300)
        act = force_foreground(int(thief.winId()))
        cap._settle(600)
        report["thief_took_foreground"] = act
        report["thief_rect"] = [thief.geometry().x(), thief.geometry().y(),
                                thief.geometry().width(), thief.geometry().height()]
        report["thief_overlaps_probe"] = thief.frameGeometry().intersects(
            target.probe_rect())
        report["steps"].append(_measure(target, decoy, "act1_shell_inactive",
                                        out_dir, save=True))
        report["inactive_beacon"] = _beacon_alive(target, out_dir, "act1_shell_inactive")

        # ---- give it back. Nothing else changes. -----------------------------
        back = target.activate()
        cap._settle(700)
        report["shell_reactivated"] = back
        report["steps"].append(_measure(target, decoy, "act2_shell_reactivated",
                                        out_dir, save=True))
        return report
    finally:
        if thief is not None:
            thief.close()
        target.close()
        cap._settle(300)


# --------------------------------------------------------------------------- #
# PROBE 3 — second window: process-wide or window-local?                        #
# --------------------------------------------------------------------------- #

def probe_second(decoy: Decoy, out_dir: Path,
                 geom: tuple[int, int, int, int]) -> dict:
    x, y, w, h = geom
    report: dict = {"probe": "second", "windows": {}}
    a = QmlTarget("A", x, y, w, h)
    cap._settle(1000)
    b = c = None
    try:
        a.activate()
        cap._settle(300)
        report["windows"]["A_baseline"] = _measure(a, decoy, "A_baseline",
                                                   out_dir, save=True)

        a.view.showMinimized()
        cap._settle(1000)
        a.view.showNormal()
        cap._settle(1200)
        pin_topmost(a.hwnd)
        report["windows"]["A_after_restore"] = _measure(a, decoy, "A_after_restore",
                                                        out_dir, save=True)

        # A fresh QQuickWindow, built AFTER the poison, in the SAME process. The rig's
        # observation ("it poisoned every window built afterwards") is what makes this
        # the difference between an RHI/process-level failure and a per-HWND one.
        a.view.hide()                      # out of the way; A is already measured
        cap._settle(400)
        b = QmlTarget("B_after_poison", x, y, w, h)
        cap._settle(1000)
        report["windows"]["B_qml_fresh"] = _measure(b, decoy, "B_qml_fresh",
                                                    out_dir, save=True)
        report["B_state_before_activate"] = b.state()
        b.activate()
        cap._settle(600)
        report["windows"]["B_qml_activated"] = _measure(b, decoy, "B_qml_activated",
                                                        out_dir, save=True)
        b.view.hide()
        cap._settle(400)

        # A fresh plain QWidget (the SHIPPED shape) in the same poisoned process.
        c = WidgetTarget("C_widget_after_poison", x, y, w, h)
        cap._settle(800)
        report["windows"]["C_widget_fresh"] = _measure(c, decoy, "C_widget_fresh",
                                                       out_dir, save=True)
        report["C_apply_backdrop_returned"] = c.applied
        c.activate()
        cap._settle(600)
        report["windows"]["C_widget_activated"] = _measure(
            c, decoy, "C_widget_activated", out_dir, save=True)
        return report
    finally:
        for t in (c, b, a):
            if t is not None:
                try:
                    t.close()
                except Exception:
                    pass
        cap._settle(300)


# --------------------------------------------------------------------------- #
# PROBE 4 — THE HEADLINE: the real shipped cockpit                             #
# --------------------------------------------------------------------------- #

class _LogTrap(logging.Handler):
    """The app's own glass verdict, in its own words: ``gui.backdrop`` logs one INFO
    truth line per (re-)assert (with the hwnd and the surface's alphaBufferSize) and
    a WARNING the moment it attaches a material to a window that cannot composite
    it."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith("gui."):
                self.records.append(f"{record.levelname} {record.name}: "
                                    f"{record.getMessage()}")
        except Exception:
            pass


def probe_app(app, decoy: Decoy, out_dir: Path, shell: str,
              whole_window: bool = False) -> dict:
    """Minimize and restore the REAL cockpit with a live acrylic material.

    If the shipped app loses its material here — on the path a user actually takes
    (taskbar click => restore AND activate) — it is a LIVE BUG, not a future
    GlassShell blocker, and it outranks everything in the queue. That distinction is
    the entire reason this probe exists, so BOTH paths are measured: restore-without-
    activation and restore-then-activate."""
    from gui import app_settings, style

    cap._assert_all_simulated(CONFIG_PATH)     # simulation only, before any device
    trap = _LogTrap()
    logging.getLogger().addHandler(trap)
    logging.getLogger().setLevel(logging.INFO)

    settings = app_settings.settings()
    snapshot = cap.snapshot_settings(settings)

    report: dict = {"probe": "app", "shell": shell, "steps": []}
    win = None
    try:
        avail = QGuiApplication.primaryScreen().availableGeometry()
        w = min(1100, avail.width() - 120)
        h = min(680, avail.height() - 120)
        x, y = avail.x() + 40, avail.y() + 40

        # The decoy is already shown (and topmost) by the caller — it must be BEHIND
        # the cockpit, so the cockpit is pinned topmost AFTER it, and lifted within
        # the topmost band before every grab.
        style.reset_theme_customization()
        from tct_gui import TCTMainWindow
        win = TCTMainWindow(config_path=CONFIG_PATH)
        win.resize(w, h)
        win.move(x, y)
        win.show()
        cap._settle(1200)
        pin_topmost(int(win.winId()))
        cap._settle(300)

        # Acrylic + the Glass preset, via the SAME slots the Settings/Theme UI drives
        # (capture_onscreen owns that path — no new GUI logic here).
        cap._apply_scenario_state(win, cap.Scenario(
            key="app_glass_acrylic", backdrop="acrylic", theme="dark",
            preset="Glass", canvas="A"))
        cap._settle(900)
        pin_topmost(int(win.winId()))
        cap._settle(300)

        canvas_rect = None
        canvas_info: dict = {}
        if not whole_window:
            try:                  # the app's own canvas finder, if it is available
                from glass_probe import exposed_canvas_rect
                canvas_rect, canvas_info = exposed_canvas_rect(win)
            except Exception as exc:
                canvas_info = {"unavailable": f"{type(exc).__name__}: {exc}"}
        else:
            # The canvas finder returns the largest region the WINDOW itself owns —
            # and in the QML shell that region is covered by the QQuickWidget chrome
            # island, so the rect it hands back is opaque chrome and reads DEAD in
            # every state, active or not (measured). Falling back to the whole window
            # + frac_pixels_changed asks the honest question instead: does ANY pixel of
            # this cockpit track what is behind it?
            canvas_info = {"skipped": "whole-window mode"}
        report["canvas_search"] = canvas_info

        target = AppTarget(win, canvas_rect)
        report["probe_rect_is"] = ("window_canvas" if canvas_rect is not None
                                   else "whole window (frac_pixels_changed carries "
                                        "the signal)")
        report["baseline_activation"] = target.activate()
        cap._settle(500)
        report["steps"].append(_measure(target, decoy, f"app_{shell}_baseline",
                                        out_dir, save=True))

        # ---- DEACTIVATION ALONE, no minimize: does the shipped cockpit lose its
        #      glass the moment the user clicks another window? (The thief is ours, so
        #      the foreground stays inside this process and can be handed back — the
        #      only activation this rig can perform reliably.)
        thief = Thief()
        thief.setGeometry(avail.right() - 300, avail.bottom() - 190, 260, 150)
        thief.show()
        cap._settle(300)
        report["thief_took_foreground"] = force_foreground(int(thief.winId()))
        cap._settle(600)
        report["steps"].append(_measure(target, decoy, f"app_{shell}_deactivated",
                                        out_dir, save=True))
        report["reactivated"] = target.activate()
        cap._settle(700)
        report["steps"].append(_measure(target, decoy, f"app_{shell}_reactivated",
                                        out_dir, save=True))
        thief.close()
        cap._settle(300)

        # ---- minimize -> restore, WITHOUT activating (the rig's own path) ----
        win.showMinimized()
        cap._settle(1100)
        win.showNormal()
        cap._settle(1400)
        pin_topmost(int(win.winId()))
        cap._settle(300)
        report["steps"].append(_measure(target, decoy, f"app_{shell}_after_restore",
                                        out_dir, save=True))

        # ---- and now the REAL user path: restore AND activate (taskbar click) --
        act = target.activate()
        cap._settle(900)
        report["restore_activation"] = act
        report["steps"].append(_measure(target, decoy, f"app_{shell}_after_activate",
                                        out_dir, save=True))

        # ---- one more full cycle, this time activating immediately on restore --
        win.showMinimized()
        cap._settle(1100)
        win.showNormal()
        target.activate()
        cap._settle(1400)
        pin_topmost(int(win.winId()))
        cap._settle(300)
        report["steps"].append(_measure(
            target, decoy, f"app_{shell}_restore_and_activate", out_dir, save=True))

        # ---- the only heal that worked on the QML shell: hide -> show ---------
        # (Cheap to try, ugly to ship — a top-level hide/show on the cockpit re-creates
        # nothing but does flash the window. Measured here so the fix discussion has a
        # number instead of an opinion.)
        win.hide()
        cap._settle(600)
        win.show()
        cap._settle(900)
        pin_topmost(int(win.winId()))
        cap._settle(300)
        report["steps"].append(_measure(target, decoy, f"app_{shell}_after_hide_show",
                                        out_dir, save=True))

        report["app_log_tail"] = trap.records[-40:]
        return report
    finally:
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
        cap.restore_settings(settings, snapshot)
        logging.getLogger().removeHandler(trap)
        cap._settle(300)


# --------------------------------------------------------------------------- #
# Child / parent plumbing                                                      #
# --------------------------------------------------------------------------- #

def _geometry() -> tuple[int, int, int, int]:
    avail = QGuiApplication.primaryScreen().availableGeometry()
    w = min(980, avail.width() - 80)
    h = min(560, avail.height() - 120)
    return avail.x() + 40, avail.y() + 60, w, h


def run_child(args, out_dir: Path) -> dict:
    geom = _geometry()
    x, y, w, h = geom
    decoy = Decoy()
    decoy.setGeometry(x - DECOY_INFLATE, y - DECOY_INFLATE,
                      w + 2 * DECOY_INFLATE, h + 2 * DECOY_INFLATE)
    if args.probe == "app":
        avail = QGuiApplication.primaryScreen().availableGeometry()
        decoy.setGeometry(avail)          # the cockpit is big; cover the desktop
    decoy.show()
    cap._settle(400)
    pin_topmost(int(decoy.winId()))
    cap._settle(200)
    try:
        if args.probe == "lifecycle":
            return probe_lifecycle(decoy, out_dir, geom, args.ladder, args.cycles)
        if args.probe == "activation":
            return probe_activation(decoy, out_dir, geom)
        if args.probe == "second":
            return probe_second(decoy, out_dir, geom)
        if args.probe == "app":
            return probe_app(QApplication.instance(), decoy, out_dir, args.shell,
                             whole_window=args.whole_window)
        raise ValueError(args.probe)
    finally:
        decoy.close()
        cap._settle(200)


def _child_argv(probe: str, out_dir: Path, args, extra: list[str]) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--probe", probe,
            "--emit", str(out_dir), "--rhi", args.rhi] + extra


# --------------------------------------------------------------------------- #
# Manifest                                                                     #
# --------------------------------------------------------------------------- #

def _fmt_stage(m: dict) -> str:
    b = m["per_method"]["bitblt"]
    g = m["per_method"]["grabwindow"]
    st = m["state"]
    a = m.get("activation_at_stripes_grab", {})
    return (f"    {m['stage']:<28s} d_behind bitblt={b['d_behind_stripes_vs_flat']:<7} "
            f"grab={g['d_behind_stripes_vs_flat']:<7} "
            f"frac={b['frac_pixels_changed']:<7} rgb={b['mean_rgb_stripes']} "
            f"alpha={st['surface_alphaBufferSize']} "
            f"active_at_grab={a.get('is_active_window')} fg_at_grab={a.get('is_foreground')} "
            f"hwnd={st['hwnd']} probe_hits_target={m.get('probe_hits_target')}\n"
            f"        -> {m['verdict']}"
            + (f"   INTRUDERS={m['zorder_intruders']}" if m["zorder_intruders"] else ""))


def write_manifest(report: dict, out_dir: Path) -> None:
    L: list[str] = []
    L.append("qml_restore_material_spike — WHAT dies on minimize->restore: the SURFACE "
             "or the ATTRIBUTES (or neither)?")
    L.append(f"utc={report['utc']}  windows_build={report['windows_build']}  "
             f"pyside={report['pyside']}  rhi={report['rhi']}  "
             f"platform={report['qt_platform']}  "
             f"backdrop_supported={report['backdrop_supported']}")
    L.append(f"screen={report['screen']}  host GPU: Intel UHD iGPU (one host = a signal, "
             f"not a universal law)")
    L.append("")
    L.append("d_behind = does the probe rect change when ONLY what is BEHIND the window "
             "changes (>6 = material alive, <2 = dead)")
    L.append("alpha    = QWindow.format().alphaBufferSize()  (the 'the swapchain lost its "
             "alpha' hypothesis: 8 -> -1 would prove it)")
    L.append("active   = the OS considers this window ACTIVE / foreground")
    L.append("")

    for name, p in report["probes"].items():
        if "FAILED" in p:
            L.append(f"[{name}] FAILED: {p['FAILED']}")
            L.append("")
            continue
        L.append(f"[{name}]")
        if name == "lifecycle":
            L.append(f"  ladder={p['ladder']}  cycles={p['cycles']}  "
                     f"qml_errors={p['qml_errors'] or 'none'}")
            L.append(_fmt_stage(p["baseline"]))
            bb = p.get("baseline_beacon", {}).get("bitblt", {})
            L.append(f"    beacon(baseline): temporal_delta={bb.get('temporal_delta')} "
                     f"fps={p.get('baseline_beacon', {}).get('fps_over_1s')}")
            for cyc in p["cycle_results"]:
                L.append(f"  --- cycle {cyc['cycle']} ---")
                L.append(_fmt_stage(cyc["after_restore"]))
                ab = cyc.get("after_restore_beacon", {}).get("bitblt", {})
                L.append(f"    beacon(after restore): temporal_delta="
                         f"{ab.get('temporal_delta')} rgb={ab.get('mean_rgb')} "
                         f"fps={cyc.get('after_restore_beacon', {}).get('fps_over_1s')}"
                         f"   <- nonzero = the scene graph is ALIVE and presenting")
                for hstep in cyc["heal"]:
                    L.append(f"    heal[{hstep['step']}] -> "
                             f"{hstep['measurement']['verdict']}")
                    L.append(_fmt_stage(hstep["measurement"]))
                L.append(f"    HEALED BY: {cyc['healed_by']}   "
                         f"(not tried: {cyc['not_tried']})")
                if "confirm_after_heal" in cyc:
                    L.append(_fmt_stage(cyc["confirm_after_heal"]))
        elif name == "activation":
            L.append(f"  thief_took_foreground={p.get('thief_took_foreground')}")
            L.append(f"  thief_overlaps_probe={p.get('thief_overlaps_probe')} "
                     f"(must be False)")
            for m in p["steps"]:
                L.append(_fmt_stage(m))
            ib = p.get("inactive_beacon", {}).get("bitblt", {})
            L.append(f"    beacon(while INACTIVE): temporal_delta="
                     f"{ib.get('temporal_delta')} fps="
                     f"{p.get('inactive_beacon', {}).get('fps_over_1s')}")
        elif name == "second":
            for key, m in p["windows"].items():
                L.append(f"  {key}:")
                L.append(_fmt_stage(m))
            L.append(f"  C_apply_backdrop_returned={p.get('C_apply_backdrop_returned')}")
        elif name.startswith("app"):
            L.append(f"  shell={p.get('shell')}  probe_rect={p.get('probe_rect_is')}")
            L.append(f"  restore_activation={p.get('restore_activation')}")
            for m in p["steps"]:
                L.append(_fmt_stage(m))
            for line in p.get("app_log_tail", [])[-12:]:
                L.append(f"    log| {line}")
        L.append("")
    (out_dir / "manifest.txt").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


# --------------------------------------------------------------------------- #
# Main                                                                          #
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Does minimize->restore kill the DWM material — and what exactly "
                    "died?")
    ap.add_argument("--probe", default="lifecycle", choices=list(PROBES))
    ap.add_argument("--all", action="store_true",
                    help="run every probe, each in its own process (the rig's law)")
    ap.add_argument("--ladder", default="activate_first", choices=list(LADDERS),
                    help="order of the heal ladder in the lifecycle probe")
    ap.add_argument("--cycles", type=int, default=3,
                    help="minimize/restore cycles in the lifecycle probe (N, for the "
                         "variance)")
    ap.add_argument("--shell", default="classic", choices=["classic", "qml"],
                    help="which shipped shell the app probe boots")
    ap.add_argument("--rhi", default="opengl", choices=["opengl", "d3d11", "default"],
                    help="Qt Quick RHI. OpenGL is main.py's pin and the only RHI on "
                         "which a QQuickWindow-root shell shows glass on this stack.")
    ap.add_argument("--whole-window", action="store_true",
                    help="app probe: measure the WHOLE window (frac_pixels_changed) "
                         "instead of the canvas rect the finder returns")
    ap.add_argument("--emit", default=None, metavar="DIR", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    reason = cap.check_environment()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    # The app probe's QML shell needs its env var + the RHI pin set BEFORE the
    # QApplication exists — the same ordering law the probe is measuring.
    if args.probe == "app":
        os.environ["TCT_QML_SHELL"] = "1" if args.shell == "qml" else "0"
        if args.shell == "qml":
            from gui.qml_shell import pin_opengl_rhi
            pin_opengl_rhi()
    else:
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

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()

    # ---- CHILD: one probe, its own pristine process -------------------------
    if args.emit:
        out_dir = Path(args.emit)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            entry = run_child(args, out_dir)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            entry = {"FAILED": f"{type(exc).__name__}: {exc}"}
        key = args.probe if args.probe != "app" else f"app_{args.shell}"
        (out_dir / f"probe_{key}.json").write_text(json.dumps(entry, indent=2,
                                                             default=str),
                                                   encoding="utf-8")
        return 0

    out_dir = _REPO_ROOT / "artifacts_claude" / f"qml_restore_material_spike_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    import PySide6
    report: dict = {
        "spike": "qml_restore_material_spike",
        "utc": ts,
        "windows_build": sys.getwindowsversion().build,   # type: ignore[attr-defined]
        "qt_platform": app.platformName(),
        "pyside": PySide6.__version__,
        "rhi": args.rhi,
        "backdrop_supported": backdrop.is_backdrop_supported(),
        "screen": {"dip": [avail.width(), avail.height()],
                   "dpr": screen.devicePixelRatio(),
                   "count": len(QGuiApplication.screens())},
        "out_dir": str(out_dir),
        "probes": {},
    }

    plan: list[tuple[str, list[str]]] = []
    if args.all:
        plan = [
            # The prior spike's order FIRST: does a full re-assert really fail to heal?
            ("lifecycle_reassert_first",
             ["--ladder", "reassert_first", "--cycles", str(args.cycles)]),
            ("lifecycle_activate_first",
             ["--ladder", "activate_first", "--cycles", str(args.cycles)]),
            ("activation", []),
            ("second", []),
            ("app_classic", ["--shell", "classic"]),
            ("app_qml", ["--shell", "qml"]),
        ]
    else:
        key = args.probe if args.probe != "app" else f"app_{args.shell}"
        extra = ["--ladder", args.ladder, "--cycles", str(args.cycles),
                 "--shell", args.shell]
        plan = [(key, extra)]

    for key, extra in plan:
        probe = ("app" if key.startswith("app") else
                 "lifecycle" if key.startswith("lifecycle") else key)
        print(f"\n--- probe: {key} (own process) ---")
        sys.stdout.flush()
        cap._settle(1200)      # let the previous child's teardown settle
        proc = subprocess.run(_child_argv(probe, out_dir, args, extra), timeout=900)
        # The child names its file after the PROBE; the parent may run the same probe
        # twice (two ladders), so each result is renamed to its plan key immediately —
        # otherwise the second child silently overwrites the first one's evidence.
        json_key = f"app_{args.shell}" if probe == "app" else probe
        if probe == "app":
            json_key = "app_qml" if "qml" in extra else "app_classic"
        path = out_dir / f"probe_{json_key}.json"
        if proc.returncode != 0 or not path.exists():
            report["probes"][key] = {"FAILED": f"child exit code {proc.returncode}"}
            print(f"    child FAILED: exit {proc.returncode}")
            continue
        entry = json.loads(path.read_text(encoding="utf-8"))
        report["probes"][key] = entry
        if key != json_key:
            path.replace(out_dir / f"probe_{key}.json")

    (out_dir / "spike_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
    write_manifest(report, out_dir)
    print(f"\nartifacts: {out_dir}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
