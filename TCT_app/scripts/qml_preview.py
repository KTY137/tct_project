"""QML LIVE-PREVIEW HARNESS — the design feedback loop, in the target technology.

WHY THIS AND NOT A BROWSER MOCKUP
---------------------------------
The valuable half of the "Claude-artifact runner" idea is the LOOP (edit → see it
instantly), not the medium. The medium matters, and a browser LIES about ours:
``scripts/spikes/qml_multieffect_glass_spike.py`` MEASURED that Qt Quick has no
``backdrop-filter`` and cannot have one (a frost pane over an alpha hole is
pixel-identical to no pane at all), while CSS does. So the loop is built where the
app actually renders: PySide6 + Qt Quick, the real ``Theme`` singleton, the real
DWM chain, the real tier contract.

    cd TCT_app
    .venv/Scripts/python.exe scripts/qml_preview.py gui/qml/Shell.qml
    .venv/Scripts/python.exe scripts/qml_preview.py gui/qml/MetricTile.qml --dark \
        --backdrop acrylic --decoy
    .venv/Scripts/python.exe scripts/qml_preview.py path/to/Panel.qml --tier token

Live keys (no restart — that is the whole point):

    T           theme  light ⇄ dark          (gui.style.apply_theme + qml_theme)
    B           backdrop  none → mica → acrylic → none
    G           glass tier ceiling  auto → flat → token → window → scene → auto
    D           decoy  live ⇄ stripes ⇄ flat  (only with --decoy)
    R           re-stack the decoy behind this window (see the z-order trap)
    F5 / Ctrl+R force reload
    Esc         quit

FOUR THINGS IT DOES NOT FAKE
----------------------------
1. **The theme is the REAL token path.** ``gui/qml_theme.py``'s ``Theme`` QML
   singleton, fed from ``gui/style.py``'s LIGHT/DARK dicts — the same objects the
   app binds. Zero copied colours here; if the preview and the app could disagree
   about a token, the tool would be worthless.
2. **The glass is the REAL chain.** ``gui.qml_shell.pin_opengl_rhi`` (the RHI pin
   is load-bearing: a Quick shell renders FLAT WHITE on D3D11 and real glass on
   OpenGL — 353072f finding 3) → ``gui.style.prepare_window_surface`` as the first
   line of the window (the ORDER LAW: Qt fixes surface alpha once, at HWND
   creation) → ``gui.style.reassert_window_backdrop`` (the shipped DWM chain +
   the WS_EX_LAYERED opacity pin + the event spine's guard). Nothing about DWM is
   re-implemented here.
3. **The tier is the REAL contract.** ``gui/glass_env.py``'s ``decide_tier`` /
   ``plan_transition`` / ``format_truth_log`` decide what may be painted — this
   harness is the contract's FIRST consumer. The tier switch is an *override
   ceiling*, exactly as the operator's persisted setting is, so ``--tier flat``
   here exercises the same code path a flat-tier operator gets.
4. **The backdrop can be hostile.** ``--decoy`` reuses the spike's ``Decoy``
   (imported, not forked) — including its two hard-won traps: a periodic stripe is
   invisible to a blur kernel wider than its period (hence the moving blob), and
   another window rising between the decoy and the target produces a perfect,
   entirely FALSE glass reading (hence the topmost flags + ``R``).

DEV TOOL ONLY. Never imported by the app. No hardware, no ``devices/``, no
``controller/``, no ``DeviceManager``, no scan. It reads QSettings (theme, glass
override) and never writes them.
"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
from dataclasses import replace
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_TCT_APP = _SCRIPTS.parent
for _p in (str(_TCT_APP), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, QUrl, Property, QObject, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QSurfaceFormat
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget,
)

from gui import backdrop, glass_env, qml_theme, style
from gui.glass_env import GlassTier
from gui.qml_shell import _ensure_qml_dll_path, pin_opengl_rhi
from gui.style import apply_theme, load_theme_customization, palette

logger = logging.getLogger("qml_preview")

_QML_DIR = _TCT_APP / "gui" / "qml"
_SPIKE = _SCRIPTS / "spikes" / "qml_multieffect_glass_spike.py"

RELOAD_DEBOUNCE_MS = 120
"""Editors save in bursts (write → flush → rename). One reload per burst."""

BACKDROP_CYCLE = ("none", "mica", "acrylic")
TIER_CYCLE = glass_env.CANONICAL_OVERRIDES          # auto, flat, token, window, scene
DECOY_CYCLE = ("live", "stripes", "flat")


# --------------------------------------------------------------------------- #
# The QML-facing bridge — what the harness itself tells the scene              #
# --------------------------------------------------------------------------- #
class PreviewBridge(QObject):
    """Context property ``preview``: the harness's own state, bindable from QML.

    Deliberately tiny. It exposes the *decided* tier (not the requested one) so a
    glass-aware component can bind ``preview.flat`` / ``preview.tier`` and be
    previewed on every rung without a restart — and so nothing in a .qml can
    pretend it is on a rung the contract did not grant.
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tier = GlassTier.TOKEN
        self._backdrop = "none"
        self._material = False

    def update(self, *, tier: GlassTier, backdrop_kind: str, material: bool) -> None:
        self._tier = tier
        self._backdrop = backdrop_kind
        self._material = material
        self.changed.emit()

    @Property(str, notify=changed)
    def tier(self) -> str:
        return self._tier.name.lower()

    @Property(int, notify=changed)
    def tierValue(self) -> int:
        return int(self._tier)

    @Property(bool, notify=changed)
    def flat(self) -> bool:
        """The accessibility/operator FLAT rung — no glass identity at all."""
        return self._tier == GlassTier.FLAT

    @Property(bool, notify=changed)
    def glass(self) -> bool:
        """True only while a real OS material is verifiably attached to THIS
        window's current HWND (``gui.backdrop.window_has_material``) — not merely
        "the preference is acrylic". The underlay law's own truth."""
        return self._material

    @Property(str, notify=changed)
    def backdrop(self) -> str:
        return self._backdrop

    @Property(bool, notify=changed)
    def dark(self) -> bool:
        return qml_theme.current_mode() == "dark"


# --------------------------------------------------------------------------- #
# The preview window                                                           #
# --------------------------------------------------------------------------- #
class QmlPreviewWindow(QMainWindow):
    """A QMainWindow + ``#mainShell`` central widget hosting ONE QQuickWidget.

    That shape is not decoration: ``gui/style.py``'s glass-canvas QSS only ever
    matches ``QMainWindow[glassCanvas="true"]`` / ``QDialog[glassCanvas="true"]``
    / ``QWidget#mainShell[glassCanvas="true"]``, and ``gui/backdrop.py``'s
    ``_canvas_widgets`` preps the top-level AND the central widget. A plain
    QWidget host would silently render a DIFFERENT canvas than the cockpit — the
    exact class of lie this tool exists to prevent.
    """

    def __init__(self, qml_path: Path, *, backdrop_kind: str,
                 tier_override: str | None, decoy: bool = False) -> None:
        super().__init__()
        # Topmost BEFORE the HWND exists. setWindowFlags on a realized window is a
        # documented HWND-recreation path (Fenrir K9) and every DWM attribute dies
        # with the old handle; the spine would re-assert, but a preview that has to
        # be healed to look right is a preview that lies for one frame.
        if decoy:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # THE ORDER LAW — first line, before a single child exists. A QQuickWidget
        # realizes the top-level's HWND, and Qt fixes surface alpha exactly once,
        # in QWidgetPrivate::create(). Set the attribute afterwards and the material
        # attaches with S_OK and composites nothing (GL-island spike, finding 2).
        style.prepare_window_surface(self)

        self._path = qml_path
        self._backdrop_kind = backdrop_kind
        self._tier_override = tier_override      # None ⇒ read the persisted setting
        self._tier = glass_env.SAFE_FLOOR
        self._decoy = None
        self._decoy_pattern = "live"

        self.setWindowTitle(f"QML preview — {qml_path.name}")
        self.resize(1180, 760)

        central = QWidget(self)
        central.setObjectName("mainShell")       # the QSS/backdrop canvas contract
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._status = QLabel("", central)
        self._status.setObjectName("previewStatus")
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        self._errors = QPlainTextEdit(central)
        self._errors.setObjectName("previewErrors")
        self._errors.setReadOnly(True)
        self._errors.setMaximumHeight(190)
        self._errors.hide()
        outer.addWidget(self._errors)

        from PySide6.QtQuickWidgets import QQuickWidget

        self._quick = QQuickWidget(central)
        self._quick.setObjectName("previewQuick")
        self._quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._bridge = PreviewBridge(self)
        ctx = self._quick.rootContext()
        ctx.setContextProperty("preview", self._bridge)
        engine = self._quick.engine()
        for p in (str(_QML_DIR), str(qml_path.parent)):
            engine.addImportPath(p)
        outer.addWidget(self._quick, 1)

        # --- hot reload -------------------------------------------------------
        # BOTH the file and its directory: most editors save atomically (write a
        # temp file, then rename over the target), which DELETES the inode
        # QFileSystemWatcher was holding — the file path silently stops being
        # watched after the first save. The directory watch catches the rename,
        # and _reload() re-arms the file path every cycle.
        self._watcher = QFileSystemWatcher(self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(RELOAD_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._reload)
        self._watcher.fileChanged.connect(self._on_fs_event)
        self._watcher.directoryChanged.connect(self._on_fs_event)
        self._rearm_watch()

        self._install_shortcuts()
        self._restyle()
        self._reload()
        self._apply_glass(reason="startup")

        if decoy:
            self._build_decoy()

    # -- QML load / reload -------------------------------------------------- #
    def _rearm_watch(self) -> None:
        watched = set(self._watcher.files()) | set(self._watcher.directories())
        for p in (str(self._path), str(self._path.parent)):
            if p not in watched and Path(p).exists():
                self._watcher.addPath(p)

    def _on_fs_event(self, _path: str) -> None:
        self._debounce.start()

    def _reload(self) -> None:
        """Clear the component cache and re-load. NEVER raises.

        A tool that dies on a typo will not be used, so every failure mode here
        (missing file, syntax error, non-Item root, an exception out of Qt) ends in
        "show the text, keep watching, recover on the next good save".
        """
        try:
            self._rearm_watch()
            if not self._path.exists():
                self._show_errors(f"{self._path} does not exist (waiting for it to "
                                  f"come back — the directory is still watched)")
                return

            # Order matters: drop the old root object graph FIRST, then clear the
            # cache, then load. Clearing while the old component is still
            # referenced by the view leaves the stale one alive and the reload is
            # a no-op that looks like "my edit did nothing".
            self._quick.setSource(QUrl())
            self._quick.engine().clearComponentCache()
            self._quick.setSource(QUrl.fromLocalFile(str(self._path)))

            from PySide6.QtQuickWidgets import QQuickWidget

            if self._quick.status() == QQuickWidget.Status.Error:
                self._show_errors("\n".join(e.toString() for e in self._quick.errors()))
                return
            if self._quick.rootObject() is None:
                self._show_errors(
                    "loaded, but there is no root Item.\n"
                    "A QQuickWidget can only host a root object deriving from "
                    "QQuickItem — a root `Window { }` will not render here. Wrap the "
                    "component in an `Item { }` (which is also how the app embeds "
                    "QML: an island inside a QWidget window).")
                return
            self._clear_errors()
            logger.info("reloaded %s", self._path)
        except Exception:                       # pragma: no cover - belt
            logger.exception("reload failed")
            self._show_errors("the reload itself raised — see the console traceback.\n"
                              "Still watching; fix the file and save again.")

    def _show_errors(self, text: str) -> None:
        self._errors.setPlainText(text)
        self._errors.show()
        logger.warning("QML error in %s:\n%s", self._path.name, text)
        self._refresh_status()

    def _clear_errors(self) -> None:
        self._errors.clear()
        self._errors.hide()
        self._refresh_status()

    # -- glass: the REAL contract, the REAL chain --------------------------- #
    def _environment(self) -> glass_env.GlassEnvironment:
        env = glass_env.probe_environment(
            shell=glass_env.SHELL_CLASSIC,      # a QQuickWidget island in a QWidget
                                                # window IS the classic shell today
            scan_active=False,                  # a dev tool never runs an acquisition
            rtt_children=("QQuickWidget",),     # the honest census (logged, not decisive)
            user_override=self._tier_override,  # None ⇒ read the persisted ceiling
        )
        # The RHI is not guessable from the environment (glass_env._rhi_backend_probe
        # can only report what was REQUESTED via env vars); we PINNED it ourselves in
        # main(), so we state it, exactly as that probe's docstring instructs.
        return glass_env.normalize(replace(env, rhi_backend="opengl"))

    def _apply_glass(self, *, reason: str) -> None:
        decision = glass_env.explain_tier(self._environment())
        plan = glass_env.plan_transition(self._tier, decision.tier, scan_active=False)
        logger.info(glass_env.format_truth_log(decision, window="preview", reason=reason))
        if plan.action != glass_env.TRANSITION_NONE:
            logger.info("glass: %s %s → %s (%s)", plan.action, plan.current.name.lower(),
                        plan.target.name.lower(), plan.reason)
        self._tier = decision.tier

        # The tier GATES the material: below WINDOW there is no OS material to
        # attach, whatever the operator picked. Above it, the requested kind wins.
        kind = self._backdrop_kind if decision.tier >= GlassTier.WINDOW else "none"
        style.set_window_backdrop(kind)
        # apply_theme must re-run: the glass-canvas QSS rules only EXIST while a
        # backdrop preference is active (gui/style.py::_glass_canvas_qss).
        apply_theme(QApplication.instance(), qml_theme.current_mode())
        style.reassert_window_backdrop(self, reason=f"preview-{reason}")

        material = backdrop.window_has_material(self)
        # Let the material through the island only when it is verifiably attached —
        # the underlay law, applied to the QQuickWidget's clear colour: an alpha
        # hole may never exist without a material behind it.
        self._quick.setClearColor(
            QColor(Qt.GlobalColor.transparent) if material
            else QColor(palette(qml_theme.current_mode())["canvas"]))
        self._bridge.update(tier=decision.tier, backdrop_kind=kind, material=material)
        self._decision = decision
        self._restyle()
        self._refresh_status()

    # -- theme -------------------------------------------------------------- #
    def _restyle(self) -> None:
        """Repaint the harness chrome from TOKENS (both themes, zero inline hex)."""
        p = palette(qml_theme.current_mode())
        self.setStyleSheet(
            f"QLabel#previewStatus {{ background: {p['strip']}; color: {p['muted']};"
            f" padding: 6px 10px; border-bottom: 1px solid {p['hairline']}; }}"
            f"QPlainTextEdit#previewErrors {{ background: {p['well']}; color: {p['crit']};"
            f" border: 1px solid {p['crit']}; padding: 6px; }}")

    def toggle_theme(self) -> None:
        mode = "light" if qml_theme.current_mode() == "dark" else "dark"
        qml_theme.set_theme_mode(mode)          # QML bindings re-evaluate (NOTIFY)
        # _apply_glass runs the QSS side (gui.style.apply_theme) itself — it has to,
        # because the glass-canvas rules only exist while a backdrop preference is
        # active, so the backdrop must be decided BEFORE the stylesheet is built.
        # It also re-tints the live DWM material (attr 20) for the new mode.
        self._apply_glass(reason="theme")

    def cycle_backdrop(self) -> None:
        i = BACKDROP_CYCLE.index(self._backdrop_kind) if self._backdrop_kind in BACKDROP_CYCLE else 0
        self._backdrop_kind = BACKDROP_CYCLE[(i + 1) % len(BACKDROP_CYCLE)]
        self._apply_glass(reason="backdrop")

    def cycle_tier(self) -> None:
        current = self._tier_override or glass_env.OVERRIDE_AUTO
        i = TIER_CYCLE.index(current) if current in TIER_CYCLE else 0
        self._tier_override = TIER_CYCLE[(i + 1) % len(TIER_CYCLE)]
        self._apply_glass(reason="tier")

    # -- decoy (the hostile desktop) ---------------------------------------- #
    def _build_decoy(self) -> None:
        """Import the spike's Decoy — never fork it. Both traps come with it."""
        if sys.platform != "win32":
            logger.warning("--decoy: the spike's Decoy is Windows-only; skipping")
            return
        try:
            spec = importlib.util.spec_from_file_location(
                "_tct_qml_glass_spike", _SPIKE)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)         # type: ignore[union-attr]
            self._decoy = mod.Decoy()
        except Exception:
            logger.exception("--decoy: could not load %s — continuing without it", _SPIKE)
            self._decoy = None
            return
        self._place_decoy()
        self._decoy.show()
        self._decoy.set_pattern(self._decoy_pattern)
        self.restack()

    def _place_decoy(self, inflate: int = 24) -> None:
        if self._decoy is None:
            return
        g = self.frameGeometry()
        self._decoy.setGeometry(g.x() - inflate, g.y() - inflate,
                                g.width() + 2 * inflate, g.height() + 2 * inflate)

    def cycle_decoy(self) -> None:
        if self._decoy is None:
            return
        i = DECOY_CYCLE.index(self._decoy_pattern)
        self._decoy_pattern = DECOY_CYCLE[(i + 1) % len(DECOY_CYCLE)]
        self._decoy.set_pattern(self._decoy_pattern)
        self.restack()
        self._refresh_status()

    def restack(self) -> None:
        """Decoy directly behind this window, both above everything else.

        TRAP 2 (spike, ``_restack``): let ANY other window rise between the decoy
        and the target and DWM will faithfully blur *that* window instead — a
        perfect, entirely false "the glass works" reading. The z-order is
        re-asserted here, on show, on move/resize, and on demand (``R``).
        """
        if self._decoy is None:
            return
        self._place_decoy()
        self._decoy.raise_()
        self.raise_()
        self.activateWindow()

    def moveEvent(self, event):     # noqa: N802 (Qt)
        super().moveEvent(event)
        self._place_decoy()

    def resizeEvent(self, event):   # noqa: N802 (Qt)
        super().resizeEvent(event)
        self._place_decoy()

    def showEvent(self, event):     # noqa: N802 (Qt)
        super().showEvent(event)
        if self._decoy is not None:
            QTimer.singleShot(0, self.restack)

    # -- chrome ------------------------------------------------------------- #
    def _refresh_status(self) -> None:
        d = getattr(self, "_decision", None)
        mat = "ATTACHED" if self._bridge.glass else "no material"
        decoy = f"  decoy={self._decoy_pattern}" if self._decoy is not None else ""
        line = (f"{self._path.name}   theme={qml_theme.current_mode()}   "
                f"tier={self._tier.name.lower()} (override="
                f"{self._tier_override or 'auto/persisted'})   "
                f"backdrop={style.get_window_backdrop()} [{mat}]{decoy}\n"
                f"T theme · B backdrop · G tier · D decoy · R re-stack · F5 reload · Esc quit")
        if d is not None and d.tier < GlassTier.WINDOW:
            line += f"\nno OS material here — capped by: {'+'.join(d.binding)}"
        self._status.setText(line)

    def _install_shortcuts(self) -> None:
        for keys, slot in (
            ("T", self.toggle_theme),
            ("B", self.cycle_backdrop),
            ("G", self.cycle_tier),
            ("D", self.cycle_decoy),
            ("R", self.restack),
            ("F5", self._reload),
            ("Ctrl+R", self._reload),
            ("Esc", self.close),
        ):
            QShortcut(QKeySequence(keys), self, activated=slot)

    # -- teardown ----------------------------------------------------------- #
    def shutdown(self) -> None:
        """Release the QML engine's object graph EXPLICITLY before the widget dies.

        A QQuickWidget owns its own QQmlEngine and scene-graph resources, and
        relying on ``deleteLater`` alone left native teardown incomplete often
        enough to surface as an access violation in an unrelated place later (the
        lesson ``tests/test_qml_shell.py::_release_qml_chrome`` paid for).
        Idempotent; safe to call twice.
        """
        try:
            self._debounce.stop()
            for p in list(self._watcher.files()) + list(self._watcher.directories()):
                self._watcher.removePath(p)
            self._quick.setSource(QUrl())
        except Exception:                       # pragma: no cover - teardown belt
            logger.debug("shutdown: partial", exc_info=True)
        if self._decoy is not None:
            self._decoy.close()
            self._decoy = None

    def closeEvent(self, event):    # noqa: N802 (Qt)
        self.shutdown()
        super().closeEvent(event)


# --------------------------------------------------------------------------- #
# Boot                                                                         #
# --------------------------------------------------------------------------- #
def _enable_translucent_window_surface() -> None:
    """8-bit alpha on the DEFAULT surface, before the QApplication exists.

    The same three lines as ``main.py::_enable_translucent_window_surface`` —
    duplicated, deliberately, because importing ``main`` would drag in
    ``tct_gui`` → ``controller/`` → ``devices/``, and this tool must never touch
    any of that. It MERGES alpha into whatever default format is in effect; it
    does not collide with the OpenGL RHI pin (that goes through
    QQuickWindow.setGraphicsApi, not QSurfaceFormat)."""
    fmt = QSurfaceFormat.defaultFormat()
    if fmt.alphaBufferSize() < 8:
        fmt.setAlphaBufferSize(8)
        QSurfaceFormat.setDefaultFormat(fmt)


def build_preview(qml_path: Path, *, mode: str, backdrop_kind: str,
                  tier: str | None, decoy: bool = False) -> QmlPreviewWindow:
    """Construct the preview window against an EXISTING QApplication.

    Split out from :func:`main` so the headless test can build the real thing —
    same theme feed, same glass chain, same watcher — without a screen.
    """
    _ensure_qml_dll_path()                 # Windows: QtQuick plugin DLLs (qml_shell's own fix)
    load_theme_customization()             # the operator's persisted glass/typography/overrides
    qml_theme.set_theme_mode(mode)         # the QML singleton's mode…
    apply_theme(QApplication.instance(), mode)   # …and the QSS/pyqtgraph side, in lockstep
    return QmlPreviewWindow(qml_path, backdrop_kind=backdrop_kind,
                            tier_override=tier, decoy=decoy)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Live QML preview — real theme, real glass, hot reload.")
    ap.add_argument("qml", help="path to the .qml file to preview")
    theme = ap.add_mutually_exclusive_group()
    theme.add_argument("--dark", action="store_true")
    theme.add_argument("--light", action="store_true")
    ap.add_argument("--tier", choices=list(TIER_CYCLE), default=None,
                    help="glass tier CEILING (gui/glass_env.py). An override can only "
                         "force the tier DOWN — never up. Default: the persisted "
                         "operator setting.")
    ap.add_argument("--backdrop", choices=list(BACKDROP_CYCLE), default=None,
                    help="DWM material to request. Default: the persisted preference.")
    ap.add_argument("--decoy", action="store_true",
                    help="paint a loud moving pattern BEHIND the window, so "
                         "translucency is judged against a hostile desktop "
                         "(reuses the glass spike's Decoy).")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S")

    path = Path(args.qml)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 2

    # THE RHI PIN — before any QQuickWidget/QQuickWindow exists in this process.
    # Not cosmetic: measured 2026-07-14 (353072f finding 3), a Quick shell renders
    # FLAT WHITE on Qt's Windows default (D3D11) and real glass on OpenGL.
    pin_opengl_rhi()
    _enable_translucent_window_surface()

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("TCT QML Preview")

    from gui.app_settings import theme_mode

    mode = "dark" if args.dark else ("light" if args.light else theme_mode())
    load_theme_customization()
    kind = args.backdrop if args.backdrop else style.get_window_backdrop()

    win = build_preview(path, mode=mode, backdrop_kind=kind, tier=args.tier,
                        decoy=args.decoy)
    win.show()
    try:
        return app.exec()
    finally:
        win.shutdown()


if __name__ == "__main__":
    sys.exit(main())
