"""QML chrome shell — bootstrap, RHI pin, and the thin QWidget<->QML adapters.

This is the opt-in QML-hybrid frontend (``docs/research/qml_hybrid_architecture.md``
slice 1). It is built ONLY when ``TCT_QML_SHELL=1``; the classic QWidget shell is
otherwise untouched. Composition (per §1/§4 of the assessment):

* the top rail + pill tab shelf become a single ``QQuickWidget`` island
  (``gui/qml/Shell.qml``) that sits above the tabs;
* ``DetachableTabWidget`` stays the tab/detach **engine** (its native ``QTabBar``
  is merely hidden) — the QML pill shelf is a synced **view** over it via
  ``_TabShelfAdapter`` (§4's "QML renders the pill strip; the widget stays the
  model" rule), so detach/redock/persistence keep working with ZERO changes to
  ``gui/detachable_tabs.py``;
* all colours/sizes come from the ``Theme`` QML singleton (``gui/qml_theme.py``),
  which is fed from ``gui/style.py`` — no inline hex in the ``.qml``;
* the rail's device dots / HV / motion / scan / laser / scope readouts mirror the
  SAME cached state the classic ribbon uses (via ``_ShellBridge`` polling a
  provider callable) — no new hardware I/O;
* Connect All / Disconnect All / theme-toggle route to the SAME existing window
  handlers — no new logic.

RHI: the whole app is pinned to OpenGL BEFORE any ``QQuickWidget`` exists
(``pin_opengl_rhi``) so the chrome ``QQuickWidget`` and the Motor Stage
``GLViewWidget`` agree on one backend in the shared top-level window (§6 — the
D3D11-vs-OpenGL collision). pyqtgraph 2D raster is unaffected.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QColor

from gui.style import palette

logger = logging.getLogger(__name__)

_QML_DIR = Path(__file__).resolve().parent / "qml"

# Whether pin_opengl_rhi() has run this process (test/inspection hook — the pin
# is a one-shot global that later calls no-op).
_RHI_PINNED = False


def _ensure_qml_dll_path() -> None:
    """Windows: let the QML engine resolve the QtQuick/Layouts plugin DLLs that
    live in the PySide6 package root (same fix the spike used headless)."""
    try:
        import PySide6
    except Exception:
        return
    ps = os.path.dirname(PySide6.__file__)
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(ps)
        except (OSError, FileNotFoundError):
            pass
    os.environ["PATH"] = ps + os.pathsep + os.environ.get("PATH", "")


def pin_opengl_rhi() -> None:
    """Pin the Qt Quick scene-graph to OpenGL for the whole process.

    MUST be called before any ``QQuickWidget``/``QQuickWindow`` is created (from
    ``main.py`` when ``TCT_QML_SHELL=1``; also called defensively from
    ``build_qml_chrome``). Idempotent: after the first Quick window exists this
    is a no-op at the Qt level, and we guard the flag so it is cheap to re-call.
    """
    global _RHI_PINNED
    if _RHI_PINNED:
        return
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    _RHI_PINNED = True


def rhi_pinned() -> bool:
    """Whether pin_opengl_rhi() has been applied this process."""
    return _RHI_PINNED


# --------------------------------------------------------------------------- #
# Tab-shelf adapter — QML pill strip is a VIEW; DetachableTabWidget is engine   #
# --------------------------------------------------------------------------- #
class _TabShelfAdapter(QObject):
    """Two-way bind between the QML pill shelf and the real ``DetachableTabWidget``.

    Titles/current-index are mirrored FROM the widget; pill clicks and the pill
    detach glyph are forwarded TO the widget's existing API
    (``setCurrentIndex``/``detach``). Never owns pages — the widget stays the
    single source of truth, so the detach/redock/persistence contract is intact.
    """

    changed = Signal()

    def __init__(self, tabs, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tabs = tabs
        self._titles: list[str] = []
        self._current = 0
        # currentChanged also fires on redock (DetachableTabWidget re-inserts the
        # page and calls setCurrentIndex), so this covers the redock refresh too.
        tabs.currentChanged.connect(self._on_current_changed)
        self.sync()

    def _on_current_changed(self, _idx: int) -> None:
        self.sync()

    def sync(self) -> None:
        """Re-read titles + current index from the engine and notify QML.

        Cheap; called on ``currentChanged``, right after a QML-initiated detach,
        and as a safety net from the shell bridge's cached-state poll (so any
        tab add/remove that did not move the current index still reaches QML).
        """
        titles = [self._tabs.tabText(i) for i in range(self._tabs.count())]
        current = self._tabs.currentIndex()
        if titles == self._titles and current == self._current:
            return
        self._titles = titles
        self._current = current
        self.changed.emit()

    @Property("QVariantList", notify=changed)
    def titles(self) -> list[str]:
        return self._titles

    @Property(int, notify=changed)
    def currentIndex(self) -> int:
        return self._current

    @Property(int, notify=changed)
    def count(self) -> int:
        return len(self._titles)

    @Slot(int)
    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)

    @Slot(int)
    def detach(self, index: int) -> None:
        """Tear tab *index* into a floating window via the engine's own path."""
        if 0 <= index < self._tabs.count():
            self._tabs.detach(index)
            self.sync()


# --------------------------------------------------------------------------- #
# Shell bridge — mirrors cached ribbon state into QML; routes rail actions      #
# --------------------------------------------------------------------------- #
class _ShellBridge(QObject):
    """Feeds the QML rail from cached state and routes its buttons to handlers.

    ``state_provider`` returns a dict of already-cached values (no I/O — it reads
    the same device flags / status-chip text the classic ribbon AND toolbar
    show). This bridge owns NO timer of its own (slice 2a — coffee-retro item):
    the composition root's existing ``_light_timer`` (``tct_gui.py``, the same
    1 Hz GUI-thread timer that already drives ``_refresh_lights``/
    ``_sync_app_state``) also drives ``pull()``, so there is exactly one poll
    of the same cached state per tick rather than two independent QTimers doing
    duplicate work. ``start()`` only seeds the QML properties once, synchronously,
    so the rail isn't empty for the first tick.
    ``connectAll``/``disconnectAll``/``toggleTheme``/``openDeviceManager``/
    ``openSettings``/``toggleLog``/``toggleDeviceDebug`` invoke the window's
    existing handlers — the QML rail is a second SURFACE for the same actions
    the (now-hidden, in QML mode) classic toolbar exposed, never a duplicate
    implementation.
    """

    changed = Signal()

    def __init__(
        self,
        *,
        state_provider,
        on_connect,
        on_disconnect,
        on_toggle_theme,
        on_open_devices=None,
        on_open_settings=None,
        on_toggle_log=None,
        on_toggle_debug=None,
        scope_vm=None,
        tab_adapter=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = state_provider
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_toggle_theme = on_toggle_theme
        self._on_open_devices = on_open_devices
        self._on_open_settings = on_open_settings
        self._on_toggle_log = on_toggle_log
        self._on_toggle_debug = on_toggle_debug
        self._scope_vm = scope_vm
        self._tab_adapter = tab_adapter

        self._devices: list[list[str]] = []
        self._readouts: dict[str, list[str]] = {
            "hv": ["HV --", "neutral"],
            "motion": ["Motion offline", "neutral"],
            "scan": ["Scan --", "neutral"],
            "laser": ["Laser --", "neutral"],
            # The toolbar's app-state readout (see gui/qml/Shell.qml's "State"
            # StatChip) — separate from "scan" above.
            "app": ["State --", "neutral"],
        }
        self._log_visible = False
        self._debug_visible = False

    def start(self) -> None:
        """Seed the QML properties once. No owned timer — see the class docstring;
        the composition root connects its shared ``_light_timer.timeout`` to
        ``pull`` for every tick after this initial one."""
        self.pull()

    @Slot()
    def pull(self) -> None:
        """Re-read cached state and push it to QML (and the scope view-model).

        The WHOLE body is guarded: this slot is invoked directly by a C++
        QTimer, and an uncaught Python exception raised from a Qt-invoked slot
        can abort the process rather than merely fail the call — the same
        "never let a routine, no-I/O poll step crash the process" rule
        ``_refresh_lights``/``_sync_app_state`` already follow in tct_gui.py.
        """
        try:
            state = self._provider() or {}
            self._devices = list(state.get("devices", []))
            for key in ("hv", "motion", "scan", "laser", "app"):
                val = state.get(key)
                if val:
                    self._readouts[key] = list(val)
            self._log_visible = bool(state.get("log_visible", False))
            self._debug_visible = bool(state.get("debug_visible", False))
            scope = state.get("scope")
            if scope is not None and self._scope_vm is not None:
                try:
                    self._scope_vm.update(**scope)
                except Exception:
                    logger.debug("scope view-model update failed", exc_info=True)
            self.changed.emit()
            # Safety net: reflect any tab add/remove that did not move the
            # current index (currentChanged would have missed it).
            if self._tab_adapter is not None:
                self._tab_adapter.sync()
        except Exception:
            logger.debug("shell bridge pull failed", exc_info=True)

    # -- rail actions (route to the SAME existing window handlers) -------- #
    @Slot()
    def connectAll(self) -> None:
        if self._on_connect is not None:
            self._on_connect()

    @Slot()
    def disconnectAll(self) -> None:
        if self._on_disconnect is not None:
            self._on_disconnect()

    @Slot()
    def toggleTheme(self) -> None:
        if self._on_toggle_theme is not None:
            self._on_toggle_theme()

    @Slot()
    def openDeviceManager(self) -> None:
        if self._on_open_devices is not None:
            self._on_open_devices()

    @Slot()
    def openSettings(self) -> None:
        if self._on_open_settings is not None:
            self._on_open_settings()

    @Slot()
    def toggleLog(self) -> None:
        if self._on_toggle_log is not None:
            self._on_toggle_log()

    @Slot()
    def toggleDeviceDebug(self) -> None:
        if self._on_toggle_debug is not None:
            self._on_toggle_debug()

    # -- QML-facing properties ------------------------------------------- #
    @Property("QVariantList", notify=changed)
    def devicesModel(self) -> list[list[str]]:
        return self._devices

    @Property(str, notify=changed)
    def hvText(self) -> str: return self._readouts["hv"][0]

    @Property(str, notify=changed)
    def hvState(self) -> str: return self._readouts["hv"][1]

    @Property(str, notify=changed)
    def motionText(self) -> str: return self._readouts["motion"][0]

    @Property(str, notify=changed)
    def motionState(self) -> str: return self._readouts["motion"][1]

    @Property(str, notify=changed)
    def scanText(self) -> str: return self._readouts["scan"][0]

    @Property(str, notify=changed)
    def scanState(self) -> str: return self._readouts["scan"][1]

    @Property(str, notify=changed)
    def laserText(self) -> str: return self._readouts["laser"][0]

    @Property(str, notify=changed)
    def laserState(self) -> str: return self._readouts["laser"][1]

    @Property(str, notify=changed)
    def appText(self) -> str: return self._readouts["app"][0]

    @Property(str, notify=changed)
    def appState(self) -> str: return self._readouts["app"][1]

    @Property(bool, notify=changed)
    def logVisible(self) -> bool: return self._log_visible

    @Property(bool, notify=changed)
    def debugVisible(self) -> bool: return self._debug_visible


# --------------------------------------------------------------------------- #
# Builder                                                                       #
# --------------------------------------------------------------------------- #
def build_qml_chrome(
    window,
    tabs,
    *,
    state_provider,
    scope_vm,
    on_connect,
    on_disconnect,
    on_toggle_theme,
    on_open_devices=None,
    on_open_settings=None,
    on_toggle_log=None,
    on_toggle_debug=None,
    run_vm=None,
    theme_mode: str = "light",
):
    """Build the QML chrome ``QQuickWidget`` and its adapters.

    Returns ``(chrome_widget, bridge)`` on success, or ``(None, None)`` if
    ``Shell.qml`` fails to load. Fail-safe (rule-5 spirit — never leave the
    user with a running-but-unusable frame): on a load error nothing here
    hides the classic toolbar or the native tab bar, no half-built chrome is
    adopted, and every object this call constructed (bridge, tab adapter,
    the QQuickWidget itself) is released. The caller (``tct_gui._build_central``)
    must check for ``None`` and keep the classic shell fully operable —
    toolbar, ribbon strip and native tab bar all stay visible — instead of
    hiding them unconditionally.

    On success: the bridge (and the tab adapter, held on the widget) are kept
    alive by the caller. The native tab bar is hidden so the QML pill shelf is
    the only visible tab surface, and the classic toolbar is hidden by the
    caller — its non-duplicated affordances (Device Manager / Settings / Show
    Log / Show Device Debug / the app-state readout) are re-exposed as a rail
    cluster routed through ``on_open_devices``/``on_open_settings``/
    ``on_toggle_log``/``on_toggle_debug``, the SAME handlers the toolbar
    actions call. ``bridge.start()`` seeds the cached-state poll once; the
    caller (``tct_gui._build_central``) connects its shared ``_light_timer``
    to ``bridge.pull`` for every tick after that — this bridge owns no timer
    of its own (see ``_ShellBridge``'s docstring).
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtQuickWidgets import QQuickWidget

    pin_opengl_rhi()              # defensive — main.py already pinned in QML mode
    _ensure_qml_dll_path()

    # Importing the module registers the @QmlElement Theme singleton and sets the
    # active QML theme mode to match the app before the QML is loaded.
    from gui import qml_theme
    qml_theme.set_theme_mode(theme_mode)

    tab_adapter = _TabShelfAdapter(tabs)
    bridge = _ShellBridge(
        state_provider=state_provider,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        on_toggle_theme=on_toggle_theme,
        on_open_devices=on_open_devices,
        on_open_settings=on_open_settings,
        on_toggle_log=on_toggle_log,
        on_toggle_debug=on_toggle_debug,
        scope_vm=scope_vm,
        tab_adapter=tab_adapter,
    )

    chrome = QQuickWidget(window)
    chrome.setObjectName("qmlShellChrome")
    chrome.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    chrome.setClearColor(QColor(palette(theme_mode)["canvas"]))
    ctx = chrome.rootContext()
    ctx.setContextProperty("shell", bridge)
    ctx.setContextProperty("tabShelf", tab_adapter)
    ctx.setContextProperty("scopeVm", scope_vm)
    # Read-only run/scan-state facade for the QML Scan Viewer (may be None in a
    # future caller; QML then sees null and simply binds nothing). The bridge
    # does NOT feed it — the composition root's shared _light_timer does, in
    # both shells — so no run_vm plumbing lives on _ShellBridge.
    ctx.setContextProperty("runState", run_vm)
    chrome.setSource(QUrl.fromLocalFile(str(_QML_DIR / "Shell.qml")))

    if chrome.status() == QQuickWidget.Status.Error:
        for err in chrome.errors():
            logger.error("Shell.qml load error: %s", err.toString())
        # Fail safe: do NOT adopt a broken chrome and do NOT touch the
        # toolbar/native tab bar here — the caller keeps the classic shell
        # fully operable. Release everything this call constructed.
        try:
            chrome.setSource(QUrl())
        except Exception:
            pass
        chrome.setParent(None)
        chrome.deleteLater()
        bridge.deleteLater()
        tab_adapter.deleteLater()
        return None, None

    # Fixed-height chrome strip (rail 48 + pill shelf 44 + the
    # ScanStatusStrip section 112 = 204 — see Shell.qml's matching
    # `implicitHeight` comment); the tabs take the rest.
    chrome.setFixedHeight(204)

    # Keep adapters alive with the widget and expose them for teardown/tests.
    chrome._shell_bridge = bridge
    chrome._tab_adapter = tab_adapter

    # DetachableTabWidget stays the engine; hide only its native tab bar so the
    # QML pill shelf is the visible tab surface. Pages/detach are unchanged.
    tabs.tabBar().hide()

    bridge.start()
    return chrome, bridge
