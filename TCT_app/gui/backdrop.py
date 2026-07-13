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

Beat G-B1 (2026-07-13 night, glass council SYNTHESIS §2.4) added the **event
spine** on top of that mechanism, because a DWM attribute is not a setting — it
is state on ONE HWND, and it dies with it:

* :func:`reassert_backdrop` is the single ordered chain (ExtendFrame → attr 20 →
  attr 38 → canvas prep → truth log) that every path goes through.
* :class:`_BackdropGuard` (via :func:`install_backdrop_guard`) re-runs it on
  ``WinIdChange`` (Qt re-created the native window — Fenrir K9), ``Show``
  (close-and-reopen), ``WindowStateChange`` (minimize/restore) and the
  theme/palette events Windows' ``WM_THEMECHANGED``/``WM_SETTINGCHANGE`` arrive
  as. Deliberately NOT a ``QAbstractNativeEventFilter``: that would put a Python
  callback in the raw window-message path of an app that must not jitter a 30 Hz
  acquisition loop, and Qt already translates the two messages we care about
  into widget events.
* :func:`nudge_repaint` heals the stale-surface class after a re-assert.
* The **underlay law** (:data:`CANVAS_GLASS_PROPERTY`, :func:`_fail_safe_opaque`)
  makes the failure mode structurally impossible: no window is ever translucent
  while its material is not verifiably attached to its current HWND.

The theme-aware entry point every caller actually uses is
``gui.style.reassert_window_backdrop`` (it owns the mode → attr-20 tint and the
``WS_EX_LAYERED`` opacity pin); this module stays theme-blind.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import weakref
from ctypes import wintypes
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import QMainWindow, QWidget

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Public constants                                                            #
# --------------------------------------------------------------------------- #

BACKDROP_KINDS = ("none", "mica", "acrylic")

# THE UNDERLAY LAW (glass council, SYNTHESIS §4.1, promoted to LAW):
#
#   No surface may ever be translucent with nothing behind it.
#
# A window only carries the translucent canvas (WA_TranslucentBackground + the
# rgba QSS canvas fill) while a DWM material is VERIFIABLY attached to its
# CURRENT HWND. The moment that is not true — attach failed, the HWND was
# recreated (Fenrir K9), the material was reset, the host cannot do it at all —
# the window falls back to the opaque TOKEN pre-blend by construction. That is
# what this dynamic property carries: ``glassCanvas="true"`` is set on the
# window (and its ``#mainShell`` central widget) by _prepare_window_canvas ONLY
# after both DWM calls returned S_OK, and cleared by _clear_window_canvas on
# every failure/reset path. gui/style.py's QSS paints the rgba glass fill only
# behind that selector; the unqualified canvas rule stays an opaque hex.
#
# Consequence (this is the whole point): a lost DWM attribute degrades to
# "looks like token glass", NEVER to the black hole Kaya saw on 2026-07-13
# (a translucent canvas over a material that was no longer there).
CANVAS_GLASS_PROPERTY = "glassCanvas"

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

# DWMWA_USE_IMMERSIVE_DARK_MODE attribute id (dwmapi.h). A per-window BOOL that
# tells DWM to tint the window's non-client frame AND its Mica/Acrylic material
# DARK. It is NOT read from the system app-mode automatically: a window that
# never sets it composes the material in the LIGHT tint by default — a bright,
# near-white frosted pane regardless of the desktop or the app's own palette
# ("komplett weiss"). Qt sets this implicitly during a stylesheet-driven
# repolish when it detects a dark colour scheme, but that is a fragile side
# effect (a same-QSS apply that skips the repolish — the Phase-0 perf guard in
# gui.style.apply_theme — never re-triggers it). So the backdrop path asserts it
# EXPLICITLY from the caller's theme mode (see apply_backdrop's ``dark`` arg),
# and re-asserts it on every theme switch, instead of trusting the repolish.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20

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

# Per-window bookkeeping for the event spine (beat G-B1):
#   _guarded_windows — windows that already carry a _BackdropGuard event filter,
#       so install_backdrop_guard() is idempotent under the app-wide fan-out.
#   _window_hwnds — the HWND each window carried at its last successful attach.
#       DWM attributes (ExtendFrame margins, attr 20, attr 38) live on the HWND
#       and die with it, silently, S_OK-history and all (Fenrir K9). Comparing
#       the live handle against this map is the ONLY way to see that happen —
#       so the truth log calls it out by name (see _log_truth).
_guarded_windows: "weakref.WeakSet[QWidget]" = weakref.WeakSet()
_window_hwnds: "weakref.WeakKeyDictionary[QWidget, int]" = weakref.WeakKeyDictionary()
# Re-entrancy guard: a re-assert touches attributes/palette/properties, which
# can post the very events (PaletteChange, WinIdChange) the guard listens for.
# Never recurse — one re-assert per window at a time.
_reasserting: "weakref.WeakSet[QWidget]" = weakref.WeakSet()


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


def _repolish(widget: QWidget) -> None:
    """Re-evaluate the QSS attribute selectors on ONE widget after its
    ``glassCanvas`` property flipped (Qt does not do it on its own).

    Deliberately NOT ``gui.style.repolish``: that primitive is reserved for the
    palette RESYNC path (``style._reassert_window_palette``), which
    ``tests/test_backdrop.py::
    test_backdrop_reassert_never_runs_while_a_real_material_is_applied`` pins to
    the ``kind == "none"`` branch only — a live material must never have its
    transparent Window-role palette painted over. This one only re-runs the
    style pass so the ``[glassCanvas="true"]`` rule starts/stops applying, and
    it only ever runs when the property ACTUALLY CHANGED (see
    :func:`_set_canvas_translucent`), so a same-kind reissue — which the app-wide
    fan-out performs on every single theme toggle — does exactly nothing."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _set_surface_translucent(widget: QWidget, translucent: bool) -> None:
    """The SURFACE half: give one widget the translucency ATTRIBUTE — which is
    what makes Qt request a per-pixel-alpha native surface for it.

    **This must run BEFORE the native window is created.** Qt decides a
    top-level's surface alpha exactly once, in ``QWidgetPrivate::create()``, from
    ``WA_TranslucentBackground``; setting the attribute afterwards only calls
    ``QWindow::setFormat``, which is documented to have no effect on an
    already-created window. Measured on this exact stack (Qt 6.11.1 / Win11
    26200, ``scripts/spikes/gl_island_glass_spike.py``, finding 2): attribute
    after creation ⇒ ``format().alphaBufferSize() == -1`` ⇒ the canvas renders
    fully opaque and acrylic-on is PIXEL-IDENTICAL to acrylic-off. The material
    is attached, DWM says S_OK, and nothing composites. The old code called
    ``winId()`` (which creates the HWND) before its canvas prep, so the
    "turn the backdrop on for a live window" path could not work by construction
    — the spike's words.

    IDEMPOTENT: a no-op when the widget is already in the requested state, so the
    event spine (which re-asserts on WinIdChange/Show/theme events) never churns
    the attribute.
    """
    if _CANVAS_MODE == "no_system_background":
        if widget.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground) != translucent:
            widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, translucent)
        return
    if translucent:
        if not widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            palette = widget.palette()
            palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
            widget.setPalette(palette)
            widget.setAutoFillBackground(False)
    else:
        if widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            widget.setPalette(QPalette())
            widget.setAutoFillBackground(True)


def _set_glass_canvas(widget: QWidget, glass: bool) -> None:
    """The PIXEL half: the ``glassCanvas`` dynamic property — the UNDERLAY LAW's
    carrier.

    The QSS canvas rule paints the rgba (alpha) fill only behind
    ``[glassCanvas="true"]``; without it the canvas is the opaque token
    pre-blend. So this — and ONLY this — is what actually opens an alpha hole in
    the window, and it is set only after both DWM calls returned S_OK on the
    window's CURRENT HWND.

    Splitting the surface (above) from the pixels (here) is what lets us obey
    both laws at once: the alpha SURFACE must be negotiated *before* the HWND
    exists (or the material can never composite), while the alpha PIXELS must
    appear only *after* the material is verified (or a lost material shows as a
    black hole). A translucent-capable surface painted with an opaque fill is
    simply an opaque window — harmless."""
    want = "true" if glass else None
    if widget.property(CANVAS_GLASS_PROPERTY) == want:
        return
    widget.setProperty(CANVAS_GLASS_PROPERTY, want)
    _repolish(widget)


def _prepare_window_surface(window: QWidget) -> None:
    """Give the window (and, for a ``QMainWindow``, its central ``#mainShell``
    child) an alpha-capable surface — BEFORE anything realizes the HWND.

    The central widget matters as much as the top-level: a ``QMainWindow``'s
    client area is painted by that child, so an opaque child over a translucent
    window carries no alpha down to DWM (see :func:`_canvas_widgets`)."""
    for w in _canvas_widgets(window):
        _set_surface_translucent(w, True)


def _prepare_window_canvas(window: QWidget) -> None:
    """Open the alpha hole: glass pixels on the window + its central widget.

    Callers MUST have verified the material is attached to the window's CURRENT
    HWND first — the underlay law says an alpha hole may never exist without a
    material behind it."""
    for w in _canvas_widgets(window):
        _set_glass_canvas(w, True)


def _close_glass_canvas(window: QWidget) -> None:
    """Close the alpha hole (glass pixels off) but KEEP the translucency
    attribute — the state for "the material is attached but this surface has no
    alpha channel to carry it".

    Keeping the attribute is what lets the window heal itself: the next time Qt
    re-creates its native handle, ``QWidgetPrivate::create()`` sees
    ``WA_TranslucentBackground`` and grants a real alpha surface, and the very
    next re-assert (the WinIdChange one) turns the glass on for real."""
    for w in _canvas_widgets(window):
        _set_glass_canvas(w, False)


def _clear_window_canvas(window: QWidget) -> None:
    """The fail-safe opaque state: no glass pixels, no translucency attribute.

    The enforcement arm of the underlay law — called on a reset to "none" AND on
    every failure path. Dropping the attribute does not un-do the surface's alpha
    capability (that was baked in at HWND creation and outlives the attribute),
    so a later successful re-attach still composites: this is a paint-time
    fallback, not a one-way door."""
    for w in _canvas_widgets(window):
        _set_glass_canvas(w, False)
        _set_surface_translucent(w, False)


def _fail_safe_opaque(window: QWidget) -> None:
    """Underlay law, enforcement arm: drop ``window`` back to the opaque TOKEN
    canvas because its material is not (or no longer) verifiably attached.

    A window that never had a material is left alone (nothing to undo — the
    setters are no-ops for it). A window that DID have one — and whose re-assert
    has just failed, e.g. because DWM rejected the call on a freshly recreated
    HWND — loses its glass pixels and its translucency attribute in the same
    breath, so the QSS falls back to the opaque pre-blend instead of painting an
    alpha hole over nothing (the BLACK bug)."""
    if window in _backdrop_applied_windows:
        logger.warning(
            "backdrop: material lost on %s — falling back to the opaque token "
            "canvas (underlay law)", type(window).__name__)
    _clear_window_canvas(window)
    _backdrop_applied_windows.discard(window)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

def apply_backdrop(window: QWidget, kind: str, *, dark: bool | None = None) -> bool:
    """Apply (or reset) a DWM system backdrop material on ``window``.

    ``kind`` must be one of :data:`BACKDROP_KINDS` — anything else raises
    ``ValueError``. Returns ``True`` only if ``window`` now matches the
    requested state; ``False`` on any unsupported host or DWM failure, in
    which case ``window`` is left fail-safe opaque (never half-applied —
    ``WA_TranslucentBackground`` is only set after BOTH DWM calls succeed).

    ``kind == "none"`` resets a previously-applied backdrop; on a window that
    never had one applied, it is a true no-op (no DWM calls at all).

    ``dark`` — when not ``None``, asserts ``DWMWA_USE_IMMERSIVE_DARK_MODE``
    (True → dark tint, False → light tint) on the HWND *before* the material
    is attached, so Mica/Acrylic composes in the tint that matches the app
    theme instead of DWM's light default ("komplett weiss" — see that
    constant's comment). Set BEFORE the ``SYSTEMBACKDROP_TYPE`` attribute per
    the documented recipes (order matters on some builds). ``None`` (the
    default, and what every non-theme caller/test uses) leaves the flag
    untouched — byte-identical to the pre-fix behaviour. The theme layer
    (``gui.style.apply_window_backdrop_to``) passes the live mode; this module
    stays theme-blind and only relays the boolean. A non-zero HRESULT here is
    logged but does NOT abort the material (it is a tint refinement, not the
    material itself).
    """
    return reassert_backdrop(window, kind, dark=dark, reason="apply")


def reassert_backdrop(window: QWidget, kind: str, *, dark: bool | None = None,
                      reason: str = "reassert") -> bool:
    """THE ordered DWM chain — the single re-assert every path goes through.

    Order (glass council SYNTHESIS §2.3 / Fenrir rider 1, amended by the
    GL-island spike's finding 2 — the surface step now comes FIRST, and it is the
    highest-value line in this module):

        translucency ATTRIBUTE (alpha surface)   ← BEFORE the HWND exists
          → realize the native window (winId)
          → DwmExtendFrameIntoClientArea(-1)
          → attr 20  DWMWA_USE_IMMERSIVE_DARK_MODE   (tint, from the live theme)
          → attr 38  DWMWA_SYSTEMBACKDROP_TYPE        (the material itself)
          → ``glassCanvas`` glass PIXELS             (underlay law: only on S_OK)
          → one-line truth log (incl. the surface's real alphaBufferSize)

    Why the surface step leads: Qt fixes a top-level's surface alpha once, in
    ``QWidgetPrivate::create()``. Set ``WA_TranslucentBackground`` after the HWND
    exists and the window never gets an alpha channel — DWM reports S_OK,
    attaches the material, and nothing composites (acrylic-on is pixel-identical
    to acrylic-off; measured, ``scripts/spikes/gl_island_glass_spike.py``).
    Splitting surface from pixels (see :func:`_set_glass_canvas`) is what lets
    this run early WITHOUT violating the underlay law.

    (The caller pins window opacity afterwards — ``gui.style
    .reassert_window_backdrop`` — because ``WS_EX_LAYERED`` suppresses the
    material outright, and style.py is the layer that owns that knob.)

    IDEMPOTENT, CHEAP, and it NEVER RAISES: it is called from an event filter
    on WinIdChange / Show / theme events, so a throw here would take down an
    unrelated Qt event delivery. Every native call is already exception-guarded;
    the Qt-side prep is a no-op when nothing changed.

    ``reason`` is a free-text tag for the truth log ("apply", "show",
    "winidchange", "theme", ...) — the greppable evidence of WHY the chain ran.

    Returns True iff the material is now verifiably attached to ``window``'s
    CURRENT HWND. On False, the window is left fail-safe opaque (underlay law:
    never a translucent canvas with nothing behind it).
    """
    if kind not in BACKDROP_KINDS:
        raise ValueError(
            f"unknown backdrop kind {kind!r}; expected one of {BACKDROP_KINDS}")

    if not is_backdrop_supported():
        return False

    if window in _reasserting:          # see _reasserting's comment
        return window in _backdrop_applied_windows

    _reasserting.add(window)
    try:
        if kind == "none":
            return _reset_backdrop(window)

        # STEP 0 — the alpha SURFACE, before anything realizes the HWND. This is
        # the line the GL-island spike says is worth more than the rest of the
        # module: after creation it is unfixable, and its absence is invisible
        # (S_OK everywhere, zero pixels). Safe to do up front because the glass
        # PIXELS are still gated on the DWM calls below (underlay law).
        was_realized = window.windowHandle() is not None
        _prepare_window_surface(window)

        hwnd = _native_hwnd(window)
        if hwnd is None:
            _fail_safe_opaque(window)
            return False

        # Read back what Qt actually negotiated. A window realized BEFORE the
        # attribute was set reports alpha < 8 here, and can never composite the
        # material until its native handle is re-created.
        alpha = _surface_alpha(window)
        if alpha < 8 and was_realized:
            alpha = _renegotiate_alpha_surface(window, alpha)
            hwnd = _native_hwnd(window) or hwnd

        previous_hwnd = _window_hwnds.get(window)
        if previous_hwnd is not None and previous_hwnd != hwnd:
            # Fenrir K9, caught in the act: Qt destroyed and re-created the
            # native window (re-parenting, some setWindowFlags paths, a
            # WA_NativeWindow toggle, certain screen migrations). Every DWM
            # attribute we ever set died with the old HWND — silently, with a
            # full history of S_OK. This log line is the ONLY evidence that
            # exists; nothing "failed".
            logger.warning(
                "backdrop: HWND recreated for %s (0x%X -> 0x%X) — all DWM "
                "attributes were lost with it; re-asserting the full chain "
                "(reason=%s)", type(window).__name__, previous_hwnd, hwnd, reason)

        ok, hrs = _attach_material(hwnd, kind, dark)
        if not ok:
            _fail_safe_opaque(window)
            return False

        if alpha < 8:
            # THE BLACK BUG, closed at its root. The material is attached (S_OK)
            # but the surface has no alpha channel, so nothing can composite
            # through it. Painting the rgba canvas here is precisely what turns
            # the window BLACK: the alpha fill blends against a zeroed backing
            # store instead of a material. Underlay law ⇒ keep the OPAQUE token
            # canvas, report no material, say so out loud. (The translucency
            # attribute stays set, so the next HWND recreation gets a real alpha
            # surface and the glass simply appears.)
            logger.warning(
                "glass: %s attached kind=%s on hwnd=0x%X but its surface has NO "
                "alpha (alphaBufferSize=%s) — the material cannot composite. "
                "Canvas stays the opaque token pre-blend (underlay law); this "
                "window was realized before its translucency attribute.",
                type(window).__name__, kind, hwnd, alpha)
            _close_glass_canvas(window)
            _backdrop_applied_windows.discard(window)
            _window_hwnds[window] = hwnd
            return False

        # Both native calls succeeded on THIS hwnd AND the surface can carry
        # alpha — only now is it safe to open the alpha hole (underlay law).
        _prepare_window_canvas(window)
        _backdrop_applied_windows.add(window)
        _window_hwnds[window] = hwnd

        # The truth log (Ymir I5 format): one greppable INFO line per
        # (re-)assert. HRESULTs included because the DWM path can return S_OK and
        # still not composite the material — a *silent* rejection is only ever
        # visible as "we said S_OK, Kaya says black". ``alpha`` is the other half
        # of that story: alpha<8 means the material is attached to a window that
        # physically cannot show it.
        # INFO for windows the operator can actually see; DEBUG for the long tail
        # of hidden/never-shown top-levels the app-wide fan-out also touches (Qt
        # keeps a surprising number of them around — a live run logged ~20). The
        # greppable truth line stays, without burying it.
        emit = logger.info if window.isVisible() else logger.debug
        emit(
            "glass: %s window=%s hwnd=0x%X kind=%s tint=%s alpha=%s canvas=glass "
            "(extend hr=%s, attr20 hr=%s, attr38=%s hr=%s)",
            reason, type(window).__name__, hwnd, kind,
            ("dark" if dark else "light") if dark is not None else "system",
            alpha, hrs[0], hrs[1], _KIND_TO_DWMSBT[kind], hrs[2])
        return True
    finally:
        _reasserting.discard(window)


def _surface_alpha(window: QWidget) -> int:
    """The per-pixel alpha the window's REALIZED native surface actually has.

    ``-1``/``0`` means DWM can attach whatever it likes and nothing will ever
    composite through this window (GL-island spike, finding 2). Cheap read; the
    only honest way to tell a live material from a dead one without a screenshot.
    """
    handle = window.windowHandle()
    if handle is None:
        return -1
    try:
        return int(handle.format().alphaBufferSize())
    except Exception:
        return -1


def _renegotiate_alpha_surface(window: QWidget, alpha: int) -> int:
    """Try to give an ALREADY-REALIZED window the alpha surface it never got.

    ``QWindow::setFormat`` is documented to have no effect after creation, so the
    only way is to destroy and re-create the native window with
    ``WA_TranslucentBackground`` already set (which :func:`_prepare_window_surface`
    has just done). That is safe on a window that is not on screen yet — the
    normal case, because every material-capable window now runs the chain in its
    constructor.

    On a VISIBLE window we refuse and log instead: yanking the HWND out from
    under a live cockpit would take its native children (the GL view, any QQuick
    island) with it, and a cosmetic material is never worth that. The warning is
    the actionable bit — it names the window whose material is attached but
    physically cannot render, which is exactly the class of bug that has cost
    this project two nights."""
    if window.isVisible():
        logger.warning(
            "glass: %s has NO alpha surface (alphaBufferSize=%s) — it was "
            "realized before the translucency attribute was set, so the DWM "
            "material is attached but CANNOT composite (S_OK, zero pixels). Not "
            "re-creating the native window of a visible window; the canvas stays "
            "the opaque token pre-blend. Fix the call order at the window's "
            "construction site.", type(window).__name__, alpha)
        return alpha

    logger.info(
        "glass: %s was realized without an alpha surface (alphaBufferSize=%s); "
        "re-creating its native window with the translucency attribute set",
        type(window).__name__, alpha)
    try:
        window.destroy()
        window.create()
    except Exception:
        logger.exception("glass: alpha-surface renegotiation failed")
        return alpha
    return _surface_alpha(window)


def _attach_material(hwnd: int, kind: str,
                     dark: bool | None) -> tuple[bool, tuple]:
    """The three native calls, in the ratified order, on ONE hwnd.

    ExtendFrame → attr 20 (tint) → attr 38 (material). Returns
    ``(ok, (extend_hr, immersive_hr, attr_hr))``; ``ok`` is False if the
    material is not attached (a bad tint HRESULT is logged but does not abort —
    it is a refinement, not the material)."""
    try:
        extend_hr = _dwm_extend_frame(hwnd)
    except Exception:
        logger.exception("backdrop: _dwm_extend_frame raised")
        extend_hr = -1
    if extend_hr != 0:
        logger.warning(
            "backdrop: DwmExtendFrameIntoClientArea failed (hr=%s, kind=%s)",
            extend_hr, kind)
        return False, (extend_hr, None, None)

    # Immersive-dark tint BEFORE the material attach (see the
    # DWMWA_USE_IMMERSIVE_DARK_MODE comment: some builds ignore a post-attach
    # flip, and the light default is the "komplett weiss").
    immersive_hr: int | None = None
    if dark is not None:
        try:
            immersive_hr = _dwm_set_window_attribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        except Exception:
            logger.exception("backdrop: immersive-dark-mode set raised")
            immersive_hr = -1
        if immersive_hr != 0:
            logger.warning(
                "backdrop: DwmSetWindowAttribute USE_IMMERSIVE_DARK_MODE=%s "
                "failed (hr=%s) — material may render in the wrong tint",
                1 if dark else 0, immersive_hr)

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
        return False, (extend_hr, immersive_hr, attr_hr)

    return True, (extend_hr, immersive_hr, attr_hr)


def prepare_surface(window: QWidget) -> bool:
    """Give ``window`` an alpha-capable native surface — call this as the FIRST
    line of a material-capable top-level's ``__init__``, before it builds any
    children.

    Qt negotiates a top-level's surface alpha exactly once, when the native
    window is created, from ``WA_TranslucentBackground`` (GL-island spike,
    finding 2). Anything that realizes the HWND early — a child that calls
    ``winId()``, a QQuickWidget, a ``show()`` — locks the window out of ever
    carrying alpha, and then the material attaches with S_OK and composites
    nothing. Setting the attribute up front makes that unreachable.

    Only touches the window when a material is actually the active preference
    (the caller decides — ``gui.style.prepare_window_surface`` relays it) and the
    host can do materials at all, so the shipped default ("none") is
    byte-identical. Opening the alpha hole is still gated on the DWM calls
    succeeding (underlay law) — this only negotiates the surface, it does not
    make a single pixel translucent."""
    if not is_backdrop_supported():
        return False
    _prepare_window_surface(window)
    return True


def window_has_material(window: QWidget) -> bool:
    """True iff a DWM material is currently attached to ``window``'s HWND (i.e.
    the last :func:`reassert_backdrop` on it succeeded and nothing has reset it
    since).

    The per-window truth the underlay law and the ``WS_EX_LAYERED`` opacity pin
    both key off — deliberately NOT "the user's backdrop preference is not
    none", which says nothing about whether THIS window actually got it."""
    return window in _backdrop_applied_windows


def _reset_backdrop(window: QWidget) -> bool:
    if window not in _backdrop_applied_windows:
        return True  # already opaque with no backdrop -- true no-op

    hwnd = _native_hwnd(window)
    if hwnd is None:
        # No handle to reset — but the Qt side must not stay translucent over
        # nothing (underlay law).
        _fail_safe_opaque(window)
        _window_hwnds.pop(window, None)
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
    _window_hwnds.pop(window, None)
    return True


# --------------------------------------------------------------------------- #
# The event spine (beat G-B1) — every event that can silently lose the attrs  #
# --------------------------------------------------------------------------- #

class _BackdropGuard(QObject):
    """Event filter that re-asserts the DWM chain whenever the window's native
    state can have dropped it. One per material-capable top-level, parented to
    it (so it dies with the window), installed by :func:`install_backdrop_guard`.

    The events, and what each one is here for:

    * ``WinIdChange`` — **the K9 fix.** Qt destroyed and re-created the native
      window (re-parenting, some ``setWindowFlags`` paths, ``WA_NativeWindow``
      toggles, screen migration). Every per-HWND DWM attribute died with it,
      silently. This is the single cheapest life-saver in the whole design; it
      had ZERO hits in the codebase before this beat.
    * ``Show`` — a window that was hidden and is shown again (Kaya's
      close-and-reopen of the theme editor). Covers the HWND-recreation path
      even when Qt does not deliver ``WinIdChange``, and it covers a stale
      redirection surface: the re-assert ends in a forced full repaint.
    * ``WindowStateChange`` — minimize → restore, the other surface-recreation
      path (and the documented trigger of the stale white/black box).
    The theme-class events are handled DIFFERENTLY, and the difference is not
    cosmetic — it is a crash fix:

    * ``ThemeChange`` / ``ApplicationPaletteChange`` — the OS flipped its
      app-mode or its accent/transparency settings. Qt delivers Windows'
      ``WM_THEMECHANGED``/``WM_SETTINGCHANGE`` to widgets as these events, so
      attr 20 (the tint) follows the OS without this app installing a native
      event filter in the message hot path (a per-message Python callback would
      tax the acquisition loop for no gain — see the module docstring).
      **These are delivered while Qt is iterating every widget in the
      application** (an app-palette fan-out). Re-asserting inline from inside
      that iteration — creating native handles, re-polishing widgets, writing
      palettes, on windows that may already be pending deletion — corrupts the
      very list Qt is walking: an access violation, reproduced in the suite.
      So they NEVER do work inline; they schedule ONE coalesced app-wide
      re-assert for the next event-loop turn (which is also exactly Fenrir's
      rider-2 "post-toggle re-assert one turn later", beating Qt's own palette
      heuristic to the last write of attr 20).

    NOT watched, deliberately: ``QEvent.PaletteChange``. Every ``setPalette`` and
    every stylesheet repolish in the app emits it — including the ones the
    re-assert itself performs — so hooking it is a feedback source with no
    unique signal.

    The filter NEVER consumes an event (always returns False) and never raises.
    """

    # Per-window events — safe to handle inline, and the promptness matters
    # (the first frame after a Show/WinIdChange must already have the material).
    _IMMEDIATE = {
        QEvent.Type.WinIdChange: "winidchange",
        QEvent.Type.Show: "show",
        QEvent.Type.WindowStateChange: "windowstate",
    }
    # App-wide fan-out events — schedule only, NEVER inline (see above).
    _DEFERRED = frozenset({
        QEvent.Type.ThemeChange,
        QEvent.Type.ApplicationPaletteChange,
    })
    _WATCHED = frozenset(_IMMEDIATE) | _DEFERRED

    def __init__(self, window: QWidget,
                 reapply: Callable[[QWidget, str], None],
                 schedule: Callable[[], None]) -> None:
        super().__init__(window)
        self._reapply = reapply
        self._schedule = schedule

    def eventFilter(self, obj, event) -> bool:      # noqa: N802 (Qt override)
        try:
            etype = event.type()
            if etype in self._DEFERRED:
                self._schedule()
            elif etype in self._IMMEDIATE:
                self._reapply(obj, self._IMMEDIATE[etype])
        except Exception:
            # An exception here would abort an unrelated Qt event delivery.
            logger.exception("backdrop: guard re-assert failed")
        return False


def install_backdrop_guard(window: QWidget,
                           reapply: Callable[[QWidget, str], None],
                           schedule: Callable[[], None]) -> bool:
    """Install the :class:`_BackdropGuard` event filter on ``window`` once.

    ``reapply(window, reason)`` and ``schedule()`` are injected by the theme
    layer (``gui.style``) — this module stays theme-blind and never imports
    style.py (that dependency only runs one way).

    Returns True if a guard was installed by this call, False if the window was
    already guarded (idempotent — the app-wide fan-out calls this on every
    theme toggle). Installed on EVERY material-capable top-level, including
    while the shipped "none" kind is active, so that switching a material on
    later needs no second wiring pass."""
    if window in _guarded_windows:
        return False
    window.installEventFilter(_BackdropGuard(window, reapply, schedule))
    _guarded_windows.add(window)
    return True


def nudge_repaint(window: QWidget) -> None:
    """Force a FULL repaint of a live-material window after a re-assert.

    ``QWidget.update()`` alone is not enough for the failure class Frigg
    documented (and Ymir calls W4): after a surface/HWND recreation the window
    can keep compositing a STALE backing store — the white (or, over a lost
    material, black) box that sits there until the user resizes the window by
    hand. The documented heal is a real resize, so this schedules a 1-px
    resize-and-restore on the next event-loop turn (never inline: it must not
    re-enter the paint/event handler that triggered the re-assert).

    Deliberately inert unless a real compositor is in play
    (:func:`is_backdrop_supported`) and the window is actually on screen — so
    the headless test suite and every non-Windows host never resize anything.
    Never raises (the window may be gone by the time the timer fires)."""
    if not is_backdrop_supported():
        return
    try:
        if not window.isVisible() or window.isMinimized():
            return
    except RuntimeError:                    # C++ side already gone
        return

    window.update()
    ref = weakref.ref(window)

    def _resize_nudge() -> None:
        w = ref()
        if w is None:
            return
        try:
            if not w.isVisible() or w.isMinimized():
                return
            size = w.size()
            w.resize(size.width(), size.height() + 1)
            QTimer.singleShot(0, lambda: _restore(ref, size))
        except RuntimeError:
            return

    def _restore(win_ref, size) -> None:
        w = win_ref()
        if w is None:
            return
        try:
            w.resize(size)
            w.update()
        except RuntimeError:
            return

    QTimer.singleShot(0, _resize_nudge)
