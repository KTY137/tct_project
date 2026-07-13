"""Windows 11 acrylic/mica *background-only* translucency.

Ratified scope (2026-07-13): this is real DWM compositor translucency behind
the window, not the existing whole-window alpha slider
(``QWidget.setWindowOpacity`` in ``gui/style.py`` / ``gui/theme_editor.py``,
which dims content and chrome together and is untouched by this module).
Content stays opaque: plots, the camera view, and every panel surface keep
painting through their own opaque QSS (design law — see
``gui/qml/Shell.qml:91``, "translucency over a live camera/plot is banned").
Only the window's own unclaimed background shows the OS backdrop material.

This module is the ONLY place in the GUI package that imports ``ctypes`` or
touches DWM. Every other module stays ctypes-free and calls the functions
below, which are clean no-ops (returning ``False``) on anything that is not
Windows 11 22H2+ running the real "windows" Qt platform plugin — in
particular the whole test suite, which runs headless under
``QT_QPA_PLATFORM=offscreen`` (offscreen has no DWM).

Two Qt-side candidates for "let the backdrop paint through the window's own
background" are implemented behind the single module constant
``_CANVAS_MODE``:

* ``"translucent_attr"`` (default) — ``Qt.WA_TranslucentBackground`` plus a
  transparent ``Window`` palette role on the top-level widget only.
* ``"no_system_background"`` — ``Qt.WA_NoSystemBackground`` instead, which
  skips Qt's own background fill without opting the widget into a full ARGB
  surface.

**Which candidate actually renders correctly under Mica/Acrylic cannot be
verified headless** — offscreen has no compositor, so this needs Kaya's
eyeball on the real display. If candidate A shows artifacts (e.g. white/black
flash, wrong redraw on resize), flip ``_CANVAS_MODE`` to
``"no_system_background"`` and re-test; nothing else in this module needs to
change for that swap.

Wiring this into ``gui/style.py`` / ``tct_gui.py`` (settings fan-out, the
theme-editor toggle) is the next beat — this module only provides the
mechanism.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import weakref
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import QMainWindow, QWidget

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Public constants                                                            #
# --------------------------------------------------------------------------- #

BACKDROP_KINDS = ("none", "mica", "acrylic")

# Windows 11 22H2 (build 22621) is the first release with the public
# DWMWA_SYSTEMBACKDROP_TYPE attribute. Deliberately NO Windows-10
# SetWindowCompositionAttribute/ACCENT_POLICY fallback below this — that path
# is known-jank (drag lag) and stays out of this codebase; older/other hosts
# just stay opaque.
_MIN_SUPPORTED_BUILD = 22621

# DWM_SYSTEMBACKDROP_TYPE enum values (dwmapi.h).
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2       # Mica
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic

# DWMWA_SYSTEMBACKDROP_TYPE attribute id for DwmSetWindowAttribute.
DWMWA_SYSTEMBACKDROP_TYPE = 38

_KIND_TO_DWMSBT = {
    "mica": DWMSBT_MAINWINDOW,
    "acrylic": DWMSBT_TRANSIENTWINDOW,
}

# Candidate Qt-side canvas strategy — see module docstring. Flip this ONE
# constant for the real-display eyeball test; nothing else needs to change.
_CANVAS_MODE = "translucent_attr"  # or "no_system_background"

# Per-window bookkeeping of "does this window currently have a real backdrop
# applied", so apply_backdrop(w, "none") only issues the DWM reset call when
# there is actually something to reset (true no-op otherwise). WeakSet so a
# closed/destroyed window is never kept alive by this module.
_backdrop_applied_windows: "weakref.WeakSet[QWidget]" = weakref.WeakSet()


# --------------------------------------------------------------------------- #
# Support probe — injectable so the full matrix is testable on any host      #
# --------------------------------------------------------------------------- #

def _version_probe() -> int:
    """Return the running Windows build number, or 0 if it cannot be read.

    Isolated in its own function (rather than inlined into
    :func:`is_backdrop_supported`) so tests can monkeypatch the OS build the
    support check sees without needing a matching host OS build.
    """
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)  # type: ignore[attr-defined]
    except Exception:
        return 0


def _platform_probe() -> str:
    """Return Qt's active platform plugin name (``"windows"``, ``"offscreen"``, ...).

    Isolated for the same monkeypatch reason as :func:`_version_probe` — the
    whole test suite runs under ``QT_QPA_PLATFORM=offscreen``, so a test that
    wants to exercise the real-Windows branch has to override this too.
    """
    app = QGuiApplication.instance()
    if app is None:
        return ""
    return app.platformName()


def is_backdrop_supported() -> bool:
    """True only on Windows 11 22H2+ running the real 'windows' Qt platform.

    False (and therefore a clean opaque no-op everywhere else in this module)
    on any other OS, any older Windows build, and any non-native Qt platform
    plugin (offscreen, minimal, ...).
    """
    if sys.platform != "win32":
        return False
    if _version_probe() < _MIN_SUPPORTED_BUILD:
        return False
    if _platform_probe() != "windows":
        return False
    return True


# --------------------------------------------------------------------------- #
# Native DWM calls — the only functions in this module that touch ctypes     #
# --------------------------------------------------------------------------- #

class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


def _dwm_extend_frame(hwnd: int) -> int:
    """Call ``DwmExtendFrameIntoClientArea`` with a full sheet-of-glass margin.

    Returns the raw HRESULT (``0`` == ``S_OK``). Monkeypatchable so tests
    never touch ctypes/dwmapi.
    """
    try:
        margins = _MARGINS(-1, -1, -1, -1)
        hr = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(  # type: ignore[attr-defined]
            wintypes.HWND(hwnd), ctypes.byref(margins))
        return int(hr)
    except Exception:
        logger.exception("backdrop: DwmExtendFrameIntoClientArea raised")
        return -1


def _dwm_set_window_attribute(hwnd: int, attribute: int, value: int) -> int:
    """Call ``DwmSetWindowAttribute`` with a DWORD-sized value.

    Returns the raw HRESULT (``0`` == ``S_OK``). Monkeypatchable so tests
    never touch ctypes/dwmapi.
    """
    try:
        c_value = ctypes.c_int(value)
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            wintypes.HWND(hwnd), wintypes.DWORD(attribute),
            ctypes.byref(c_value), ctypes.sizeof(c_value))
        return int(hr)
    except Exception:
        logger.exception("backdrop: DwmSetWindowAttribute raised")
        return -1


def _native_hwnd(window: QWidget) -> Optional[int]:
    """Return the win32 HWND for ``window``, creating the native window first.

    ``QWidget.winId()`` forces native-window creation as a side effect; DWM
    calls need a real HWND, which does not exist until then.
    """
    if window.windowHandle() is None:
        window.winId()
    if window.windowHandle() is None:
        return None
    return int(window.winId())


# --------------------------------------------------------------------------- #
# Qt-side canvas prep — candidate A/B, see module docstring                  #
# --------------------------------------------------------------------------- #

def _canvas_widgets(window: QWidget) -> list[QWidget]:
    """The widget(s) whose background must go translucent for a DWM material to
    reach the compositor.

    Always the top-level window; ADDITIONALLY the ``QMainWindow`` central
    widget (``#mainShell`` — ``tct_gui.py``). A ``QMainWindow``'s client area is
    painted by that opaque child, not by the window itself, so making only the
    top-level translucent never carries per-pixel alpha down to DWM — the
    translucent regions fall straight through to a crisp desktop, no blur (the
    "alpha hole punched, no material behind" failure — see
    ``docs/research/dwm_backdrop_blur_recipe.md`` item 1). A flat ``QDialog``
    needs no such step because it *is* the widget covering its own client.
    """
    widgets = [window]
    if isinstance(window, QMainWindow):
        central = window.centralWidget()
        if central is not None:
            widgets.append(central)
    return widgets


def _set_canvas_translucent(widget: QWidget, translucent: bool) -> None:
    """Toggle one widget between the translucent-canvas prep (so a DWM material
    shows through its own unclaimed background) and the fail-safe opaque state.
    The ``_CANVAS_MODE`` candidate switch (see the module docstring) applies
    identically to the window and its central widget."""
    if _CANVAS_MODE == "no_system_background":
        widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, translucent)
        return
    if translucent:
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
        widget.setPalette(palette)
        widget.setAutoFillBackground(False)
    else:
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        widget.setPalette(QPalette())
        widget.setAutoFillBackground(True)


def _prepare_window_canvas(window: QWidget) -> None:
    """Let the backdrop paint through the window's own unclaimed background.

    Touches the top-level widget AND (for a ``QMainWindow``) its central
    ``#mainShell`` child — but NOT the panels/plots/camera inside, which keep
    their own opaque QSS untouched (design law). The child that actually covers
    a ``QMainWindow`` client must be translucent too, or the top-level's
    translucency never reaches DWM (see :func:`_canvas_widgets`).
    """
    for w in _canvas_widgets(window):
        _set_canvas_translucent(w, True)


def _clear_window_canvas(window: QWidget) -> None:
    """Undo :func:`_prepare_window_canvas` (window + central widget) when a
    backdrop is reset to "none" — symmetric with the prep above."""
    for w in _canvas_widgets(window):
        _set_canvas_translucent(w, False)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

def apply_backdrop(window: QWidget, kind: str) -> bool:
    """Apply (or reset) a DWM system backdrop material on ``window``.

    ``kind`` must be one of :data:`BACKDROP_KINDS` — anything else raises
    ``ValueError``. Returns ``True`` only if ``window`` now matches the
    requested state; ``False`` on any unsupported host or DWM failure, in
    which case ``window`` is left fail-safe opaque (never half-applied —
    ``WA_TranslucentBackground`` is only set after BOTH DWM calls succeed).

    ``kind == "none"`` resets a previously-applied backdrop; on a window that
    never had one applied, it is a true no-op (no DWM calls at all).
    """
    if kind not in BACKDROP_KINDS:
        raise ValueError(
            f"unknown backdrop kind {kind!r}; expected one of {BACKDROP_KINDS}")

    if not is_backdrop_supported():
        return False

    if kind == "none":
        return _reset_backdrop(window)

    hwnd = _native_hwnd(window)
    if hwnd is None:
        return False

    try:
        extend_hr = _dwm_extend_frame(hwnd)
    except Exception:
        logger.exception("backdrop: _dwm_extend_frame raised")
        extend_hr = -1
    if extend_hr != 0:
        logger.warning(
            "backdrop: DwmExtendFrameIntoClientArea failed (hr=%s, kind=%s)",
            extend_hr, kind)
        return False

    try:
        attr_hr = _dwm_set_window_attribute(
            hwnd, DWMWA_SYSTEMBACKDROP_TYPE, _KIND_TO_DWMSBT[kind])
    except Exception:
        logger.exception("backdrop: _dwm_set_window_attribute raised")
        attr_hr = -1
    if attr_hr != 0:
        logger.warning(
            "backdrop: DwmSetWindowAttribute failed (hr=%s, kind=%s)",
            attr_hr, kind)
        return False

    # Both native calls succeeded — only now is it safe to make the Qt side
    # translucent (fail-safe ordering: never a translucent window with no
    # backdrop material actually behind it). Log the HRESULTs at INFO so a
    # *silent* rejection (S_OK returned but nothing renders) is still visible
    # in the log — the DWM path can return S_OK yet not composite the material.
    logger.info(
        "backdrop: applied kind=%s (DwmExtendFrameIntoClientArea hr=%s, "
        "DwmSetWindowAttribute SYSTEMBACKDROP_TYPE=%s hr=%s)",
        kind, extend_hr, _KIND_TO_DWMSBT[kind], attr_hr)
    _prepare_window_canvas(window)
    _backdrop_applied_windows.add(window)
    return True


def _reset_backdrop(window: QWidget) -> bool:
    if window not in _backdrop_applied_windows:
        return True  # already opaque with no backdrop -- true no-op

    hwnd = _native_hwnd(window)
    if hwnd is None:
        return False

    try:
        hr = _dwm_set_window_attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
    except Exception:
        logger.exception("backdrop: _dwm_set_window_attribute raised while resetting")
        hr = -1
    if hr != 0:
        logger.warning("backdrop: failed to reset backdrop to DWMSBT_NONE (hr=%s)", hr)
        return False

    _clear_window_canvas(window)
    _backdrop_applied_windows.discard(window)
    return True
