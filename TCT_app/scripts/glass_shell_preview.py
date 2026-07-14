"""THE GLASS SHELL — a walking skeleton of the full-QML cockpit, in a REAL
translucent ``QQuickWindow``.

    cd TCT_app
    .venv/Scripts/python.exe scripts/glass_shell_preview.py
    .venv/Scripts/python.exe scripts/glass_shell_preview.py --dark --backdrop acrylic
    .venv/Scripts/python.exe scripts/glass_shell_preview.py --tier flat     # the FLAT rung
    .venv/Scripts/python.exe scripts/glass_shell_preview.py --probe         # measure & exit

WHAT THIS IS
------------
A **launcher beside the app, not a change to it.** Nothing in ``main.py`` /
``tct_gui.py`` is touched; the shipped cockpit is byte-for-byte unaffected. This
process builds the thing the classic shell structurally CANNOT be:

* ``scripts/qml_preview.py`` (the design loop) hosts QML as a ``QQuickWidget``
  **island inside a QWidget window** — which IS the classic shell, and is
  therefore capped at the ``WINDOW`` glass rung by ``gui/glass_env.py``.
* This hosts a **``QQuickWindow`` ROOT** (``shell=SHELL_GLASS``), which is what
  unlocks the ``SCENE`` rung. Same theme feed, same DWM chain, same tier
  contract — a different *window*.

WHAT IS REAL (measured on this stack, 2026-07-14, Qt 6.11.1 / Win11 26200)
--------------------------------------------------------------------------
1. **The window.** ``QQuickView`` root, OpenGL RHI (the pin is load-bearing: a
   Quick shell renders FLAT WHITE on D3D11 and real glass on OpenGL — 353007f
   finding 3), 8-bit alpha surface, transparent scene clear, and the DWM chain
   attached at HWND level: ExtendFrame + attr 20 (tint) + attr 38 (material),
   all three S_OK.
2. **The island.** A REAL ``gui/bias_panel.py`` ``BiasPanel`` on a
   ``SimulatedBiasSupply``, inside a REAL ``DetachableTabWidget``, hosted as a
   native child window of the QQuickWindow (``QWidget.winId()`` →
   ``windowHandle().setParent(view)``). It renders, it takes input, it stays
   OPAQUE (a native child composites above the scene graph), and its HV controls
   go through its own ``DangerGate`` — the shell chrome cannot energize anything.
3. **The vitals.** HV voltage, leakage current and compliance are fed by the
   BiasPanel's OWN readout poller (a ``QThread`` — instrument I/O never runs on
   the GUI thread), by listening to the same signal the panel listens to. Not a
   second poll, not a fake number.
4. **The detach.** ``gui/detachable_tabs.py`` stays the ENGINE; the QML pill
   shelf is a VIEW over it through ``gui.qml_shell._TabShelfAdapter`` (imported,
   never forked). The ⧉ glyph really tears the page into a floating window.
5. **The theme + the tier.** ``gui/qml_theme.py``'s ``Theme`` singleton (fed from
   ``gui/style.py``) and ``gui/glass_env.py``'s ``decide_tier``/``plan_transition``.
   Zero copied colours, zero re-derived policy.

WHAT IS STUBBED is stamped **in the window** with a ``STUB`` badge (see
``gui/qml/glassshell/StubBadge.qml``): the phase rail, and the motion / scan /
laser / scope vitals. A skeleton whose fakes look real is worse than no skeleton.

KNOWN BLOCKER (not fixed here, under separate investigation): minimize → restore
kills the DWM material on a ``QQuickWindow`` root and a full re-assert does not
heal it. This launcher re-asserts anyway (it is the correct thing to do), logs
what it sees, and — because of the underlay law — falls back to the OPAQUE token
canvas rather than leaving a translucent window with nothing behind it. So the
worst case is "the glass went away", never a black hole.

SAFETY. Simulation only. No ``DeviceManager``, no config, no real driver, no
auto-connect: the simulated supply is connected only when you click CONNECT
(SIM) — hardware safety rule 1 is honoured even though there is no hardware to
honour it with. HV enable/ramp lives in the panel, behind its gate, exactly as
in the shipped app.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_TCT_APP = _SCRIPTS.parent
for _p in (str(_TCT_APP), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import (
    Property, QObject, QPointF, QTimer, QUrl, Qt, Signal, Slot,
)
from PySide6.QtGui import QColor, QSurfaceFormat
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from gui import backdrop, glass_env, qml_theme, style
from gui.glass_env import GlassTier
from gui.qml_shell import _ensure_qml_dll_path, _TabShelfAdapter, pin_opengl_rhi
from gui.style import apply_theme, load_theme_customization, palette

logger = logging.getLogger("glass_shell")

_QML_DIR = _TCT_APP / "gui" / "qml"
_SHELL_QML = _QML_DIR / "glassshell" / "GlassShell.qml"

BACKDROP_CYCLE = ("none", "mica", "acrylic")
TIER_CYCLE = glass_env.CANONICAL_OVERRIDES          # auto, flat, token, window, scene


# --------------------------------------------------------------------------- #
# Bridges — the ONLY things QML may see                                        #
# --------------------------------------------------------------------------- #
class GlassBridge(QObject):
    """The glass verdict, bindable. Reports the DECIDED tier and whether a real
    OS material is verifiably attached to THIS window's CURRENT hwnd — never
    merely "the preference is acrylic"."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tier = glass_env.SAFE_FLOOR
        self._backdrop = "none"
        self._material = False
        self._truth = ""

    def update(self, *, tier: GlassTier, backdrop_kind: str, material: bool,
               truth: str) -> None:
        self._tier = tier
        self._backdrop = backdrop_kind
        self._material = material
        self._truth = truth
        self.changed.emit()

    @Property(str, notify=changed)
    def tier(self) -> str: return self._tier.name.lower()

    @Property(bool, notify=changed)
    def flat(self) -> bool: return self._tier == GlassTier.FLAT

    @Property(bool, notify=changed)
    def material(self) -> bool: return self._material

    @Property(str, notify=changed)
    def backdrop(self) -> str: return self._backdrop

    @Property(bool, notify=changed)
    def dark(self) -> bool: return qml_theme.current_mode() == "dark"

    @Property(str, notify=changed)
    def truth(self) -> str: return self._truth


class VitalsBridge(QObject):
    """DISPLAY ONLY (ratified law). Read-only bias vitals — voltage, leakage
    current, compliance — fed from the BiasPanel's own worker-thread poller.

    It exposes no slot that can change hardware state, and it never will: the
    shell may display hazard state; it may never trigger it.
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._v = ("--", "neutral")
        self._i = ("--", "neutral")
        self._c = ("--", "neutral")

    @Slot(object)
    def on_reading(self, r) -> None:
        """Slot for ``BiasPanel._read_poller.reading`` (BiasReading | None).

        Guarded whole-body: this is invoked from a queued Qt connection, and an
        uncaught exception out of a Qt-invoked slot can abort the process.
        """
        try:
            if r is None:
                self._connected = False
                self._v = ("--", "neutral")
                self._i = ("--", "neutral")
                self._c = ("--", "neutral")
            else:
                self._connected = True
                v = float(getattr(r, "voltage_V", 0.0))
                i = float(getattr(r, "current_A", 0.0))
                comp = bool(getattr(r, "compliant", False))
                self._v = (f"{v:+.1f} V", "good" if abs(v) < 1.0 else "warn")
                self._i = (_format_current(i), "crit" if comp else "good")
                self._c = (("IN COMPLIANCE", "crit") if comp else ("OK", "good"))
            self.changed.emit()
        except Exception:                       # pragma: no cover - belt
            logger.debug("vitals update failed", exc_info=True)

    def set_connected(self, connected: bool) -> None:
        self._connected = bool(connected)
        self.changed.emit()

    @Property(bool, notify=changed)
    def connected(self) -> bool: return self._connected

    @Property(str, notify=changed)
    def hvText(self) -> str: return self._v[0]

    @Property(str, notify=changed)
    def hvState(self) -> str: return self._v[1]

    @Property(str, notify=changed)
    def currentText(self) -> str: return self._i[0]

    @Property(str, notify=changed)
    def currentState(self) -> str: return self._i[1]

    @Property(str, notify=changed)
    def complianceText(self) -> str: return self._c[0]

    @Property(str, notify=changed)
    def complianceState(self) -> str: return self._c[1]


class SkeletonBridge(QObject):
    """What this skeleton is honest about. Bound by the QML so a broken island
    or an unwired detach is a MESSAGE on screen, not a mystery."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._island_attached = False
        self._island_note = ""
        self._detach_note = ""

    def update(self, *, island_attached: bool, island_note: str,
               detach_note: str) -> None:
        self._island_attached = island_attached
        self._island_note = island_note
        self._detach_note = detach_note
        self.changed.emit()

    @Property(bool, notify=changed)
    def islandAttached(self) -> bool: return self._island_attached

    @Property(str, notify=changed)
    def islandNote(self) -> str: return self._island_note

    @Property(str, notify=changed)
    def detachNote(self) -> str: return self._detach_note


class ChromeBridge(QObject):
    """Shell-chrome actions. VIEW actions only (theme / backdrop / tier) plus a
    connect of a SIMULATED supply. Nothing here can energize, home or scan."""

    def __init__(self, shell: "GlassShell", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell = shell

    @Slot()
    def toggleTheme(self) -> None: self._shell.toggle_theme()

    @Slot()
    def cycleBackdrop(self) -> None: self._shell.cycle_backdrop()

    @Slot()
    def cycleTier(self) -> None: self._shell.cycle_tier()

    @Slot()
    def connectSim(self) -> None: self._shell.connect_simulated_supply()


def _format_current(amps: float) -> str:
    """Leakage in the unit an operator actually reads it in."""
    a = abs(amps)
    if a < 1e-9:
        return f"{amps * 1e12:+.1f} pA"
    if a < 1e-6:
        return f"{amps * 1e9:+.2f} nA"
    if a < 1e-3:
        return f"{amps * 1e6:+.3f} µA"
    return f"{amps * 1e3:+.3f} mA"


# --------------------------------------------------------------------------- #
# The shell                                                                    #
# --------------------------------------------------------------------------- #
class GlassShell(QObject):
    """A translucent ``QQuickWindow`` root + one REAL QWidget island.

    Not a QWidget itself: the top-level IS the ``QQuickView``. That is the whole
    architectural difference from the classic shell, and it is why every
    ``gui/style.py`` / ``gui/backdrop.py`` entry point that takes a ``QWidget``
    is unusable here — those call ``QWidget.windowHandle()`` /
    ``setAttribute(WA_TranslucentBackground)``, which a ``QQuickWindow`` does not
    have. This class therefore drives ``gui/backdrop.py``'s **HWND-level**
    primitives directly (``_attach_material`` — the same three DWM calls, in the
    same ratified order). Reuse, not a fork; the extraction of a public
    HWND-level entry point is the follow-up beat this skeleton is evidence for.
    """

    def __init__(self, *, mode: str, backdrop_kind: str,
                 tier_override: str | None) -> None:
        super().__init__()
        from PySide6.QtQuick import QQuickView, QQuickWindow

        self._backdrop_kind = backdrop_kind
        self._tier_override = tier_override
        self._tier = glass_env.SAFE_FLOOR
        self._material = False
        # What the SHIPPED app would cap at with the operator's saved settings —
        # surfaced on screen, never silently applied (see main()).
        self.persisted_override: str | None = None
        self._island_host: QWidget | None = None
        self._panel = None
        self._tabs = None
        self._supply = None
        self._slot_item = None

        # Alpha BEFORE the window exists (a QQuickWindow's alpha comes from
        # setDefaultAlphaBuffer + a transparent scene clear, not from a widget
        # attribute — it has no QWidget surface to prepare).
        QQuickWindow.setDefaultAlphaBuffer(True)

        self._view = QQuickView()
        self._view.setTitle("TCT — Glass Shell (walking skeleton)")
        self._view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self._view.setColor(QColor(Qt.GlobalColor.transparent))
        self._view.setGeometry(140, 90, 1320, 840)

        # THE ORDER LAW, in its QQuickWindow dialect. A QWindow's surface format
        # is fixed exactly once, when the native window is created — same rule as
        # QWidget, different door. ``setDefaultAlphaBuffer`` alone was MEASURED to
        # be insufficient here (this window came up with alphaBufferSize == -1,
        # which is the silent killer: DWM then attaches the material with S_OK
        # and composites ZERO pixels — the "attached, invisible" trap that cost
        # this project two nights). So the alpha is asserted on THIS window's own
        # requested format, before show() realizes it.
        fmt = self._view.format()
        if fmt.alphaBufferSize() < 8:
            fmt.setAlphaBufferSize(8)
            self._view.setFormat(fmt)

        self._glass = GlassBridge(self)
        self._vitals = VitalsBridge(self)
        self._skeleton = SkeletonBridge(self)
        self._chrome = ChromeBridge(self, self)

        # The island is built BEFORE the QML loads, because the QML binds
        # `tabShelf` (the adapter over the real DetachableTabWidget) — a null
        # context property would leave the pill shelf permanently empty.
        self._build_island()
        self._tab_adapter = _TabShelfAdapter(self._tabs)

        ctx = self._view.rootContext()
        ctx.setContextProperty("glass", self._glass)
        ctx.setContextProperty("vitals", self._vitals)
        ctx.setContextProperty("skeleton", self._skeleton)
        ctx.setContextProperty("chrome", self._chrome)
        ctx.setContextProperty("tabShelf", self._tab_adapter)
        self._view.engine().addImportPath(str(_QML_DIR))
        self._view.setSource(QUrl.fromLocalFile(str(_SHELL_QML)))

        self.errors = [e.toString() for e in self._view.errors()]
        for err in self.errors:
            logger.error("GlassShell.qml: %s", err)

        # The known blocker's event: minimize -> restore. We re-assert (the
        # correct thing to do) and log what actually happened. We do NOT try to
        # fix it here.
        self._view.windowStateChanged.connect(self._on_window_state)

    # -- island: a REAL QWidget panel, native-parented into the QQuickWindow -- #
    def _build_island(self) -> None:
        """Construct the island widget tree. NO hardware, NO auto-connect."""
        from controller.danger_gate import DangerAction  # noqa: F401 (documented dep)
        from devices.bias_supply_simulated import SimulatedBiasSupply
        from gui.bias_panel import BiasPanel
        from gui.detachable_tabs import DetachableTabWidget
        from gui.qt_danger_gate import QtDangerGate

        self._island_host = QWidget()           # top-level -> owns a QWindow
        self._island_host.setObjectName("mainShell")   # the QSS canvas contract
        lay = QVBoxLayout(self._island_host)
        lay.setContentsMargins(0, 0, 0, 0)

        self._tabs = DetachableTabWidget(self._island_host)
        lay.addWidget(self._tabs)

        # Simulated supply. NOT connected here — hardware safety rule 1: a
        # constructor never talks to a device, and nothing auto-connects at
        # startup. The operator clicks CONNECT (SIM).
        self._supply = SimulatedBiasSupply(simulation=True, channel_count=1)

        # The SAME QtDangerGate the shipped app injects: every HV-energizing path
        # in the panel asks it to confirm, with the real numbers. The shell chrome
        # has no path to it at all.
        self._gate = QtDangerGate(self._island_host)
        self._panel = BiasPanel(self._supply, gate=self._gate)
        self._tabs.addTab(self._panel, "Bias")

        # A second, deliberately trivial page — so the pill shelf has something
        # to switch to and the detach engine has a second tab to prove itself on.
        placeholder = QWidget()
        placeholder.setObjectName("skeletonPlaceholder")
        self._tabs.addTab(placeholder, "Scan (stub)")

        # THE REAL DATA PATH: the panel's own readout poller already runs in its
        # own QThread and emits BiasReading objects. The vitals strip listens to
        # the SAME signal — it does not poll the supply a second time, and it
        # never touches the device from the GUI thread.
        self._panel._read_poller.reading.connect(self._vitals.on_reading)

        self._tabs.tabBar().hide()      # the QML pill shelf is the tab surface

    def _attach_island(self) -> None:
        """Reparent the island's native window INTO the QQuickWindow.

        Measured on this stack: the widget keeps a genuine child HWND, renders,
        and takes input; it composites ABOVE the scene graph and stays opaque
        (which is exactly what an island must do — glass never goes over a live
        panel).
        """
        host = self._island_host
        if host is None:
            return
        try:
            host.winId()                        # realize -> gives it a QWindow
            handle = host.windowHandle()
            if handle is None:
                raise RuntimeError("the island widget has no QWindow to reparent")
            handle.setParent(self._view)        # QWindow::setParent -> child HWND
            host.show()
            self._skeleton.update(
                island_attached=True,
                island_note="",
                detach_note="pill click = switch · ⧉ / double-click = detach "
                            "(the REAL DetachableTabWidget engine)")
        except Exception as exc:
            logger.exception("island: native reparent failed")
            self._skeleton.update(
                island_attached=False,
                island_note=f"{type(exc).__name__}: {exc}",
                detach_note="detach: unavailable — the island did not attach")
            return

        self._slot_item = self._find_slot()
        if self._slot_item is None:
            self._skeleton.update(
                island_attached=False,
                island_note="the QML root has no item named 'islandSlot' — the "
                            "host cannot know where to put the panel.",
                detach_note="detach: unavailable")
            host.hide()
            return

        for sig in (self._slot_item.xChanged, self._slot_item.yChanged,
                    self._slot_item.widthChanged, self._slot_item.heightChanged):
            sig.connect(self._sync_island_geometry)
        self._view.widthChanged.connect(self._sync_island_geometry)
        self._view.heightChanged.connect(self._sync_island_geometry)
        self._sync_island_geometry()

    def _find_slot(self):
        from PySide6.QtQuick import QQuickItem

        root = self._view.rootObject()
        if root is None:
            return None
        if root.objectName() == "islandSlot":
            return root
        return root.findChild(QQuickItem, "islandSlot")

    def _sync_island_geometry(self) -> None:
        """Keep the native island exactly over the QML slot rectangle.

        QQuickItem scene coordinates and the child QWindow's geometry are both in
        device-INDEPENDENT pixels and share the same origin (the QQuickWindow's
        client area), so this is a direct copy — Qt applies the DPI scale on both
        sides. (Measured: at 250% scale the child HWND lands pixel-exact.)
        """
        item, host = self._slot_item, self._island_host
        if item is None or host is None:
            return
        try:
            top_left = item.mapToScene(QPointF(0.0, 0.0))
            w, h = int(item.width()), int(item.height())
            if w <= 0 or h <= 0:
                return
            host.setGeometry(int(top_left.x()), int(top_left.y()), w, h)
        except RuntimeError:                    # C++ side gone during teardown
            pass

    # -- glass: the REAL contract, the REAL chain (at HWND level) ------------ #
    def _environment(self) -> glass_env.GlassEnvironment:
        env = glass_env.probe_environment(
            shell=glass_env.SHELL_GLASS,        # <- THE point of this launcher
            scan_active=False,                  # a preview never runs an acquisition
            rtt_children=("QQuickWindow(root)",),
            user_override=self._tier_override,  # None => the persisted ceiling
        )
        # The RHI is not guessable from the environment (glass_env's own probe can
        # only report what was REQUESTED via env vars); we PINNED it in main(), so
        # we state it — exactly as that probe's docstring instructs.
        return glass_env.normalize(replace(env, rhi_backend="opengl"))

    def apply_glass(self, *, reason: str) -> None:
        decision = glass_env.explain_tier(self._environment())
        plan = glass_env.plan_transition(self._tier, decision.tier, scan_active=False)
        logger.info(glass_env.format_truth_log(decision, window="glassshell",
                                               reason=reason))
        if plan.action != glass_env.TRANSITION_NONE:
            logger.info("glass: %s %s -> %s (%s)", plan.action,
                        plan.current.name.lower(), plan.target.name.lower(),
                        plan.reason)
        self._tier = decision.tier

        # The tier GATES the material: below WINDOW there is no OS material to
        # attach, whatever the operator picked.
        kind = self._backdrop_kind if decision.tier >= GlassTier.WINDOW else "none"
        dark = qml_theme.current_mode() == "dark"
        self._material = self._attach_material(kind, dark)

        # THE UNDERLAY LAW, applied to a QQuickWindow: the scene clear may be
        # transparent ONLY while a material is verifiably attached to this
        # window's current hwnd. Otherwise the canvas is the opaque token
        # pre-blend. A translucent window with nothing behind it is the black
        # hole; here it is unreachable by construction.
        self._view.setColor(
            QColor(Qt.GlobalColor.transparent) if self._material
            else QColor(palette(qml_theme.current_mode())["canvas"]))

        binding = "+".join(decision.binding)
        alpha = self._view.format().alphaBufferSize()
        truth = (f"glass: tier={decision.tier.name.lower()} shell=glass "
                 f"rhi=opengl backdrop={kind} surface_alpha={alpha} "
                 f"material={'ATTACHED' if self._material else 'none'} "
                 f"cap={decision.cap.name.lower()} by={binding} "
                 f"| island=QWidget(native child hwnd, opaque) "
                 f"| detach=DetachableTabWidget (real engine)")
        if self.persisted_override is not None:
            truth += (f"  | your PERSISTED ceiling is "
                      f"'{glass_env.canonical_override(self.persisted_override)}' "
                      f"— the shipped cockpit would cap there.")
        if decision.tier < GlassTier.WINDOW:
            truth += "  — no OS material on this rung; the canvas is the OPAQUE " \
                     "token pre-blend (underlay law)."
        if self._material and alpha < 8:
            truth += ("  — WARNING: the material is attached but this surface has "
                      "NO alpha channel, so it composites ZERO pixels (S_OK, "
                      "invisible).")
        self._glass.update(tier=decision.tier, backdrop_kind=kind,
                           material=self._material, truth=truth)

    def _attach_material(self, kind: str, dark: bool) -> bool:
        """The DWM chain, at HWND level, through gui/backdrop.py's own primitives.

        ``gui.backdrop.reassert_backdrop`` cannot be used: it takes a ``QWidget``
        (``windowHandle()``, ``WA_TranslucentBackground``, the ``glassCanvas``
        QSS property, ``style().polish``) and none of those exist on a
        ``QQuickWindow``. The three DWM calls it makes, however, take a raw HWND —
        so this calls exactly those, in exactly that order, and re-implements
        nothing. Never raises.
        """
        if not backdrop.is_backdrop_supported():
            return False
        try:
            hwnd = int(self._view.winId())
            if kind == "none":
                backdrop._dwm_set_window_attribute(
                    hwnd, backdrop.DWMWA_SYSTEMBACKDROP_TYPE, backdrop.DWMSBT_NONE)
                return False
            ok, hrs = backdrop._attach_material(hwnd, kind, dark)
            logger.info("glass: hwnd=0x%X kind=%s tint=%s -> %s (hrs=%s)",
                        hwnd, kind, "dark" if dark else "light",
                        "ATTACHED" if ok else "FAILED", hrs)
            return bool(ok)
        except Exception:
            logger.exception("glass: material attach failed")
            return False

    def _on_window_state(self, _state) -> None:
        """THE KNOWN BLOCKER's event. Minimize → restore is measured to kill the
        DWM material on a QQuickWindow root, and a full re-assert does not heal
        it. We re-assert anyway — it is the correct thing to do, it costs one
        event-loop turn, and the underlay law guarantees the failure mode is
        "the glass went away", never a black hole. Under separate investigation;
        deliberately NOT worked around here."""
        if self._view.windowState() == Qt.WindowState.WindowMinimized:
            return
        QTimer.singleShot(0, lambda: self.apply_glass(reason="windowstate"))

    # -- actions ------------------------------------------------------------- #
    def toggle_theme(self) -> None:
        mode = "light" if qml_theme.current_mode() == "dark" else "dark"
        qml_theme.set_theme_mode(mode)              # QML bindings re-evaluate
        apply_theme(QApplication.instance(), mode)  # the QSS side (the island!)
        if self._panel is not None:
            self._panel.refresh_theme(mode)         # cached axis/plot colours
        self.apply_glass(reason="theme")            # re-tints the live material

    def cycle_backdrop(self) -> None:
        i = BACKDROP_CYCLE.index(self._backdrop_kind) \
            if self._backdrop_kind in BACKDROP_CYCLE else 0
        self._backdrop_kind = BACKDROP_CYCLE[(i + 1) % len(BACKDROP_CYCLE)]
        self.apply_glass(reason="backdrop")

    def cycle_tier(self) -> None:
        current = self._tier_override or glass_env.OVERRIDE_AUTO
        i = TIER_CYCLE.index(current) if current in TIER_CYCLE else 0
        self._tier_override = TIER_CYCLE[(i + 1) % len(TIER_CYCLE)]
        self.apply_glass(reason="tier")

    def connect_simulated_supply(self) -> None:
        """Explicit, user-initiated connect of a SIMULATED supply.

        Not done at construction and not done on show: nothing in this app
        auto-connects at startup (hardware safety rule 1). Connecting a fake
        supply is harmless, but the habit is the point — and it means the vitals
        strip visibly goes from '--' to live numbers because a REAL poller in a
        REAL worker thread started returning readings.
        """
        try:
            self._supply.connect()
            self._vitals.set_connected(True)
            logger.info("simulated bias supply connected (no hardware)")
        except Exception:
            logger.exception("simulated supply connect failed")

    # -- lifecycle ----------------------------------------------------------- #
    def show(self) -> None:
        # Show FIRST, attach the material after the scene graph is up: attaching
        # DWM attributes to a not-yet-shown QQuickWindow and then calling show()
        # crashed the backend intermittently on this host (gl-island spike). A
        # QQuickWindow, unlike a QWidget, does not need the surface prep before
        # creation — its alpha comes from setDefaultAlphaBuffer + the transparent
        # scene clear.
        self._view.show()
        self.apply_glass(reason="startup")
        self._attach_island()

    def shutdown(self) -> None:
        """Release the island's threads and the QML object graph, in that order.

        Idempotent. The BiasPanel owns a QThread (its readout poller); letting the
        process exit with it running is how a teardown turns into an access
        violation in an unrelated place later.
        """
        try:
            if self._tabs is not None:
                self._tabs.redock_all()         # close any floating windows
            if self._panel is not None:
                self._panel.shutdown()          # stops the poller QThread
            if self._island_host is not None:
                handle = self._island_host.windowHandle()
                if handle is not None:
                    handle.setParent(None)      # un-child it before it dies
                self._island_host.hide()
                self._island_host.deleteLater()
                self._island_host = None
            self._view.setSource(QUrl())
        except Exception:
            logger.debug("shutdown: partial", exc_info=True)

    # -- accessors (tests) --------------------------------------------------- #
    @property
    def view(self): return self._view

    @property
    def panel(self): return self._panel

    @property
    def tabs(self): return self._tabs

    @property
    def vitals(self) -> VitalsBridge: return self._vitals

    @property
    def glass(self) -> GlassBridge: return self._glass

    @property
    def tier(self) -> GlassTier: return self._tier


# --------------------------------------------------------------------------- #
# Boot                                                                         #
# --------------------------------------------------------------------------- #
def _enable_translucent_window_surface() -> None:
    """8-bit alpha on the DEFAULT surface, before the QApplication exists.
    (The same three lines as ``main.py``; duplicated deliberately — importing
    ``main`` would drag in ``tct_gui`` → ``controller/`` → ``devices/``.)"""
    fmt = QSurfaceFormat.defaultFormat()
    if fmt.alphaBufferSize() < 8:
        fmt.setAlphaBufferSize(8)
        QSurfaceFormat.setDefaultFormat(fmt)


def build_shell(*, mode: str, backdrop_kind: str,
                tier: str | None) -> GlassShell:
    """Construct the shell against an EXISTING QApplication.

    Split out from :func:`main` so the headless test builds the real thing —
    same theme feed, same glass chain, same island — without a screen.
    """
    _ensure_qml_dll_path()                 # Windows: QtQuick plugin DLLs
    load_theme_customization()             # the operator's persisted glass/type
    qml_theme.set_theme_mode(mode)         # the QML singleton's mode…
    apply_theme(QApplication.instance(), mode)   # …and the QSS side, in lockstep
    return GlassShell(mode=mode, backdrop_kind=backdrop_kind, tier_override=tier)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="The GlassShell walking skeleton — a real translucent "
                    "QQuickWindow root with one REAL panel island.")
    theme = ap.add_mutually_exclusive_group()
    theme.add_argument("--dark", action="store_true")
    theme.add_argument("--light", action="store_true")
    ap.add_argument("--tier", choices=list(TIER_CYCLE) + ["persisted"],
                    default=glass_env.OVERRIDE_AUTO,
                    help="glass tier CEILING (gui/glass_env.py). An override can "
                         "only force the tier DOWN, never up. Defaults to 'auto' "
                         "(no ceiling) rather than to your PERSISTED setting — "
                         "which on this machine is currently a hard cap that "
                         "would hide the very thing this preview exists to show. "
                         "Pass --tier persisted to honour it instead.")
    ap.add_argument("--backdrop", choices=list(BACKDROP_CYCLE), default="acrylic",
                    help="the DWM material to request (default: acrylic).")
    ap.add_argument("--probe", action="store_true",
                    help="measure the glass (material A/B + minimize/restore), "
                         "print JSON, and exit. No interaction.")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S")

    # THE RHI PIN — before any QQuickWindow exists in this process. Measured
    # (353007f finding 3): a Quick shell renders FLAT WHITE on Qt's Windows
    # default (D3D11) and real glass on OpenGL.
    pin_opengl_rhi()
    _enable_translucent_window_surface()

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("TCT Glass Shell")

    from gui.app_settings import theme_glass_tier, theme_mode

    # The persisted operator ceiling is NOT silently applied here (see --tier),
    # but it is never hidden either: the preview says out loud what the shipped
    # app would do with the same settings, and the truth line on screen repeats
    # it. A dev tool that quietly disagrees with the app is worse than no tool.
    persisted = theme_glass_tier()
    tier = None if args.tier == "persisted" else args.tier
    if tier is not None and glass_env.override_ceiling(persisted) < glass_env.GlassTier.SCENE:
        logger.warning(
            "glass: your PERSISTED ceiling is %r (-> %s). The shipped cockpit "
            "would cap there. This preview is running at --tier %s instead, so "
            "the shell can actually show its glass; pass '--tier persisted' to "
            "see what you would really get today.",
            persisted, glass_env.canonical_override(persisted), tier)

    mode = "dark" if args.dark else ("light" if args.light else theme_mode())
    shell = build_shell(mode=mode, backdrop_kind=args.backdrop, tier=tier)
    shell.persisted_override = persisted
    shell.show()

    if args.probe:
        return _run_probe(app, shell)

    try:
        return app.exec()
    finally:
        shell.shutdown()


# --------------------------------------------------------------------------- #
# --probe: measure the glass instead of asserting it                           #
# --------------------------------------------------------------------------- #
def _run_probe(app, shell: GlassShell) -> int:
    """A/B the DWM material against itself, then minimize/restore, then say what
    actually happened. No pixels are asserted in the test suite (offscreen has no
    compositor) — this is how the claim gets evidence on a real display."""
    from PySide6.QtGui import QGuiApplication

    out: dict = {"qml_errors": shell.errors}
    view = shell.view

    def sample_gutter() -> list:
        """Mean RGB of the window's GUTTER — the band between the window edge and
        the panes, which is the ONLY place the glass shows (no information lives
        in the glass). If the material composites, this band changes when the DWM
        attribute changes; if it does not, the two samples are identical."""
        screen = QGuiApplication.primaryScreen()
        g = view.geometry()
        pm = screen.grabWindow(0, g.x() + 2, g.y() + 120, 8, 320)
        img = pm.toImage()
        n = img.width() * img.height()
        if n == 0:
            return [-1, -1, -1]
        r = g_ = b = 0
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                r += c.red(); g_ += c.green(); b += c.blue()
        return [round(r / n, 1), round(g_ / n, 1), round(b / n, 1)]

    steps = []

    def step_connect():
        shell.connect_simulated_supply()
        steps.append(("connected_sim", None))

    def step_a():
        out["tier"] = shell.tier.name.lower()
        out["material_attached"] = shell.glass.material
        out["surface_alpha"] = view.format().alphaBufferSize()
        out["scene_clear_alpha"] = view.color().alpha()
        out["A_acrylic_gutter_rgb"] = sample_gutter()

    def step_b():
        # Flip ONLY the DWM attribute; keep the transparent scene clear, so the
        # difference between A and B isolates the MATERIAL (this is a probe, not
        # the shipped path — the underlay law governs apply_glass, not this).
        hwnd = int(view.winId())
        backdrop._dwm_set_window_attribute(
            hwnd, backdrop.DWMWA_SYSTEMBACKDROP_TYPE, backdrop.DWMSBT_NONE)

    def step_b2():
        out["B_nomaterial_gutter_rgb"] = sample_gutter()

    def step_c():
        shell.apply_glass(reason="probe-reattach")

    def step_c2():
        out["C_reattached_gutter_rgb"] = sample_gutter()
        out["vitals_after_connect"] = {
            "connected": shell.vitals.connected,
            "hv": shell.vitals.hvText,
            "leakage": shell.vitals.currentText,
            "compliance": shell.vitals.complianceText,
        }
        out["island"] = _island_report(shell)

    def step_min():
        view.showMinimized()

    def step_restore():
        view.showNormal()
        view.requestActivate()

    def step_after_restore():
        # The shell's own windowStateChanged handler already re-asserted; this is
        # a second, explicit re-assert so nobody can say we did not try.
        shell.apply_glass(reason="probe-after-restore")

    def step_verdict():
        out["D_after_min_restore_gutter_rgb"] = sample_gutter()
        out["material_after_min_restore"] = shell.glass.material
        a = out.get("A_acrylic_gutter_rgb", [0, 0, 0])
        b = out.get("B_nomaterial_gutter_rgb", [0, 0, 0])
        d = out.get("D_after_min_restore_gutter_rgb", [0, 0, 0])
        out["delta_A_vs_B"] = round(sum(abs(x - y) for x, y in zip(a, b)), 1)
        out["delta_A_vs_D"] = round(sum(abs(x - y) for x, y in zip(a, d)), 1)
        out["reading"] = (
            "delta_A_vs_B > ~6 means the DWM material really composites (the "
            "gutter changed when ONLY the DWM attribute changed). "
            "delta_A_vs_D near 0 means minimize/restore healed; a large "
            "delta_A_vs_D means the KNOWN BLOCKER bit.")
        print("PROBE " + json.dumps(out, indent=2))
        shell.shutdown()
        app.quit()

    schedule = [(500, step_connect), (900, step_a), (1200, step_b),
                (1700, step_b2), (1900, step_c), (2400, step_c2),
                (2700, step_min), (3400, step_restore), (3900, step_after_restore),
                (4600, step_verdict)]
    for ms, fn in schedule:
        QTimer.singleShot(ms, fn)
    QTimer.singleShot(12000, app.quit)          # hard belt
    return app.exec()


def _island_report(shell: GlassShell) -> dict:
    """Is the island a genuine child window of the QQuickWindow, or a lie?"""
    host = shell._island_host
    if host is None:
        return {"attached": False}
    handle = host.windowHandle()
    return {
        "attached": handle is not None and handle.parent() is shell.view,
        "hwnd": f"0x{int(host.winId()):X}",
        "geometry_dip": [host.x(), host.y(), host.width(), host.height()],
        "visible": host.isVisible(),
        "tabs": [shell.tabs.tabText(i) for i in range(shell.tabs.count())],
        "panel": type(shell.panel).__name__,
    }


if __name__ == "__main__":
    sys.exit(main())
