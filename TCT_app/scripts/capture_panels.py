"""Headless panel screenshot harness for the TCT cockpit design audit.

WHY
---
Design review (docs/design/apple_style_ui_audit.md) needs current, real
screenshots of every panel in BOTH themes. This harness is the repeatable
replacement for a one-off inline capture: run it any time to regenerate a
fresh, timestamped screenshot set.

HOW TO RUN
----------
From ``TCT_app/`` (this file assumes that cwd so ``configs/devices.yaml``
resolves; it also self-relocates via ``__file__`` and ``os.chdir`` so running
it from the repo root or anywhere else still works)::

    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe scripts/capture_panels.py

``QT_QPA_PLATFORM=offscreen`` is also forced in-process (first line of code,
before any Qt import) so setting it in the environment is a belt-and-braces
extra, not a requirement.

WHAT IT DOES
------------
Builds one shared, never-shown-for-real ``QApplication`` and, for BOTH
``light`` and ``dark`` themes:

1. The full classic ``TCTMainWindow`` shell (1440x900) — ``shell_full.png``.
2. The QML chrome strip (``TCT_QML_SHELL=1`` for that one window build,
   rail+pills+scan-status only, not the whole window) — ``qml_chrome.png``.
3. Every top-level panel, built STANDALONE against a fresh, fully-simulated
   ``DeviceManager`` (``configs/devices.yaml`` has ``simulation: true`` for
   every backend) — ``panel_<name>.png``.

Zero hardware, zero real connection, zero scan/HV/motion: ``DeviceManager()``
never talks to hardware at construction (rule 1), and this script never calls
``connect_all()`` or any panel's "Connect"/"Start"/"Arm" action.

Every panel construction + capture is wrapped in its own try/except so ONE
panel failing to build standalone still lets every other panel render — a
failure is itself an audit finding and is recorded in ``manifest.txt`` as
``FAILED: <panel>  <error>`` rather than aborting the run.

QSettings ISOLATION
--------------------
``gui/style.py``/``tct_gui.py``/most panels read/write
``QSettings("TCT", "TCTSetup")`` (theme, window geometry, ...) — the SAME
store the real app uses (the Windows registry by default). This script must
never touch the developer's real persisted settings, so before touching any
Qt window it repoints ALL ``QSettings("TCT", "TCTSetup")`` access process-wide
at a throwaway temp .ini file (``QSettings.setDefaultFormat`` +
``QSettings.setPath``). The temp file is left on disk (harmless, OS temp
dir); nothing under ``TCT_app/`` or the registry is written.

OUTPUT
------
``<repo>/artifacts_claude/ui_audit_<UTC timestamp>/``::

    light/panel_<name>.png, light/shell_full.png, light/qml_chrome.png
    dark/panel_<name>.png,  dark/shell_full.png,  dark/qml_chrome.png
    contact_sheet_light.png, contact_sheet_dark.png
    manifest.txt   -- every file + pixel size, FAILED entries prominent

Re-runnable: every run gets its own timestamped folder, nothing is mutated
in place.
"""
from __future__ import annotations

import os

# Must happen before any Qt import — offscreen, no real display, no hardware.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import gc
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ``TCT_app/`` is this file's parent directory; make imports (tct_gui, gui.*,
# controller.*) resolve regardless of the caller's cwd, then chdir into it so
# the repo's own relative config path ("configs/devices.yaml") is valid too —
# the same assumption tests/test_qml_shell.py makes.
_TCT_APP = Path(__file__).resolve().parent.parent
if str(_TCT_APP) not in sys.path:
    sys.path.insert(0, str(_TCT_APP))
os.chdir(_TCT_APP)

_WORKTREE_ROOT = _TCT_APP.parent

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

# Isolate from the developer's REAL persisted QSettings("TCT","TCTSetup")
# store (Windows registry by default) before any window/panel reads or writes
# it. Every subsequent QSettings("TCT","TCTSetup") call in this process
# (tct_gui.py, every panel's theme read, SettingsWindow, ...) now lands in a
# throwaway temp .ini instead.
_SETTINGS_DIR = tempfile.mkdtemp(prefix="tct_ui_audit_settings_")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _SETTINGS_DIR)

CONFIG_PATH = "configs/devices.yaml"
SHELL_SIZE = (1440, 900)
PANEL_SIZE = (1400, 860)  # realistic cockpit tab-content size


# --------------------------------------------------------------------------- #
# Small Qt helpers (same idiom as tests/test_qml_shell.py's headless harness)  #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(seconds: float = 0.12) -> None:
    app = _app()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.005)


def _teardown_widget(widget: QWidget) -> None:
    """Best-effort, generic teardown: call the panel's own shutdown hook(s)
    (every stateful panel in this codebase implements a no-arg ``shutdown()``
    or, for MonitorPanel, ``stop_polling()`` — the exact set
    ``tct_gui._teardown_panels`` drives), then hide + deleteLater + pump so
    threads/timers are stopped before the next widget is built."""
    for meth_name in ("shutdown", "stop_polling"):
        fn = getattr(widget, meth_name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
    # SettingsWindow owns a _VisaScanManager with its own shutdown(), normally
    # released on app-quit (aboutToQuit) — this script never reaches that, so
    # release it explicitly.
    scan_mgr = getattr(widget, "_visa_scan_mgr", None)
    if scan_mgr is not None and hasattr(scan_mgr, "shutdown"):
        try:
            scan_mgr.shutdown()
        except Exception:
            pass
    try:
        widget.hide()
    except Exception:
        pass
    widget.deleteLater()
    _pump(0.05)


def _destroy_main_window(win) -> None:
    """Tear a TCTMainWindow (classic- or QML-mode) down deterministically —
    adapted from tests/test_qml_shell.py's ``_destroy`` helper."""
    try:
        win._teardown_panels()
    except Exception:
        pass
    chrome = getattr(win, "_qml_chrome", None)
    if chrome is not None:
        try:
            chrome.setSource(QUrl())
        except Exception:
            pass
        win._qml_chrome = None
        win._shell_bridge = None
        win._scope_vm = None
    win.hide()
    win.deleteLater()
    _pump(0.2 if chrome is not None else 0.1)
    gc.collect()
    _pump(0.05)


# --------------------------------------------------------------------------- #
# 1. Full classic shell                                                        #
# --------------------------------------------------------------------------- #
def _capture_full_shell(mode: str, theme_dir: Path, manifest: list[str],
                         thumbs: list[tuple[str, QPixmap]]) -> None:
    from tct_gui import TCTMainWindow
    name = "shell_full"
    os.environ.pop("TCT_QML_SHELL", None)
    orig_restore = TCTMainWindow._restore_window_state
    TCTMainWindow._restore_window_state = lambda self: None
    win = None
    try:
        win = TCTMainWindow(config_path=CONFIG_PATH)
        _pump(0.15)
        win.resize(*SHELL_SIZE)
        win.show()
        _pump(0.2)
        pix = win.grab()
        path = theme_dir / f"{name}.png"
        pix.save(str(path))
        manifest.append(f"{name}.png  {pix.width()}x{pix.height()}")
        thumbs.append((name, pix))
    except Exception as e:
        manifest.append(f"FAILED: {name}  {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        if win is not None:
            _destroy_main_window(win)
        TCTMainWindow._restore_window_state = orig_restore


# --------------------------------------------------------------------------- #
# 2. QML chrome strip (opt-in shell)                                           #
# --------------------------------------------------------------------------- #
def _capture_qml_chrome(mode: str, theme_dir: Path, manifest: list[str],
                         thumbs: list[tuple[str, QPixmap]]) -> None:
    from tct_gui import TCTMainWindow
    from gui.qml_shell import pin_opengl_rhi
    name = "qml_chrome"
    os.environ["TCT_QML_SHELL"] = "1"
    orig_restore = TCTMainWindow._restore_window_state
    TCTMainWindow._restore_window_state = lambda self: None
    win = None
    try:
        pin_opengl_rhi()
        win = TCTMainWindow(config_path=CONFIG_PATH)
        _pump(0.2)
        chrome = getattr(win, "_qml_chrome", None)
        if chrome is None:
            manifest.append(
                f"FAILED: {name}  build_qml_chrome() returned None "
                "(Shell.qml failed to load in this environment)")
            return
        win.resize(*SHELL_SIZE)
        win.show()
        _pump(0.3)
        pix = chrome.grab()
        path = theme_dir / f"{name}.png"
        pix.save(str(path))
        manifest.append(f"{name}.png  {pix.width()}x{pix.height()}")
        thumbs.append((name, pix))
    except Exception as e:
        manifest.append(f"FAILED: {name}  {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        if win is not None:
            _destroy_main_window(win)
        TCTMainWindow._restore_window_state = orig_restore
        os.environ.pop("TCT_QML_SHELL", None)


# --------------------------------------------------------------------------- #
# 3. Individual panels — standalone construction against one shared, never-    #
#    connected DeviceManager (mirrors tct_gui._build_central's own calls).     #
# --------------------------------------------------------------------------- #
def _panel_specs(devices, gate):
    from gui.analysis_panel import AnalysisPanel
    from gui.bias_panel import BiasPanel
    from gui.calibration_panel import CalibrationPanel
    from gui.camera_panel import CameraPanel
    from gui.device_panel import DeviceManagerWindow
    from gui.intensity_panel import IntensityPanel
    from gui.laser_panel import LaserPanel
    from gui.monitor_panel import MonitorPanel
    from gui.motor_panel import MotorPanel
    from gui.multi_bias_panel import MultiBiasPanel
    from gui.planner_panel import PlannerPanel
    from gui.scan_viewer_panel import ScanViewerPanel
    from gui.scope_panel import ScopePanel
    from gui.settings_window import SettingsWindow

    W = PANEL_SIZE
    return [
        ("motor",             W,            lambda: MotorPanel(devices.motor)),
        ("reference_monitor", W,            lambda: IntensityPanel(devices.intensity_monitor)),
        ("camera",            W,            lambda: CameraPanel(devices.camera)),
        ("scope",             W,            lambda: ScopePanel(
            devices.scope, config_path=CONFIG_PATH,
            analysis_kwargs=devices.analysis_kwargs)),
        ("laser",             W,            lambda: LaserPanel(devices.laser, devices.waveform_generator)),
        ("scan_viewer",       W,            lambda: ScanViewerPanel()),
        ("planner",           (1500, 950),  lambda: PlannerPanel()),
        ("bias_multi",        W,            lambda: MultiBiasPanel(devices.bias_channels)),
        ("bias_single",       (900, 720),   lambda: BiasPanel(devices.bias_supply)),
        ("calibration",       W,            lambda: CalibrationPanel(devices, gate=gate)),
        ("monitor",           W,            lambda: MonitorPanel(
            devices.slow_control, poll_interval_s=devices._poll_interval_s,
            influx_writer=devices.influx)),
        ("analysis",          W,            lambda: AnalysisPanel()),
        ("device_manager",    None,         lambda: DeviceManagerWindow(devices)),
        ("settings",          None,         lambda: SettingsWindow()),
    ]


def _try_capture_panel(name: str, size, factory, mode: str, theme_dir: Path,
                        manifest: list[str], thumbs: list[tuple[str, QPixmap]]) -> None:
    try:
        widget = factory()
    except Exception as e:
        manifest.append(f"FAILED: {name}  construct: {type(e).__name__}: {e}")
        traceback.print_exc()
        return
    try:
        # Parity with tct_gui._toggle_theme: re-resolve any theme-baked
        # accent (axis colours, plot pens) a panel cached at construction.
        refresh = getattr(widget, "refresh_theme", None)
        if callable(refresh):
            try:
                refresh(mode)
            except Exception:
                pass
        if size is not None:
            widget.resize(*size)
        widget.show()
        _pump(0.12)
        pix = widget.grab()
        path = theme_dir / f"panel_{name}.png"
        pix.save(str(path))
        manifest.append(f"panel_{name}.png  {pix.width()}x{pix.height()}")
        thumbs.append((name, pix))
    except Exception as e:
        manifest.append(f"FAILED: {name}  capture: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        _teardown_widget(widget)


def _capture_all_panels(mode: str, theme_dir: Path, manifest: list[str],
                         thumbs: list[tuple[str, QPixmap]]) -> None:
    from controller.device_manager import DeviceManager
    from gui.qt_danger_gate import QtDangerGate

    try:
        devices = DeviceManager(CONFIG_PATH)
    except Exception as e:
        manifest.append(
            f"FAILED: <all panels>  DeviceManager({CONFIG_PATH}) construction: "
            f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return

    gate = QtDangerGate()
    try:
        for name, size, factory in _panel_specs(devices, gate):
            _try_capture_panel(name, size, factory, mode, theme_dir, manifest, thumbs)
    finally:
        try:
            gate.shutdown()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Contact sheet — simple tiled grid + caption, QPainter only (no extra deps)   #
# --------------------------------------------------------------------------- #
def _build_contact_sheet(thumbs: list[tuple[str, QPixmap]], out_path: Path,
                          columns: int = 4, thumb_w: int = 300) -> None:
    from PySide6.QtCore import Qt as _Qt

    entries = [(n, p) for n, p in thumbs if p is not None and p.width() > 0]
    if not entries:
        return
    scaled = [(n, p.scaledToWidth(thumb_w, _Qt.TransformationMode.SmoothTransformation))
              for n, p in entries]
    max_h = max(p.height() for _, p in scaled)

    pad = 10
    caption_h = 18
    cell_w = thumb_w + pad * 2
    cell_h = max_h + caption_h + pad * 2
    rows = (len(scaled) + columns - 1) // columns

    sheet = QPixmap(cell_w * columns, cell_h * rows)
    sheet.fill(QColor(_Qt.GlobalColor.white))
    painter = QPainter(sheet)
    font = QFont()
    font.setPointSize(9)
    painter.setFont(font)
    for i, (name, pix) in enumerate(scaled):
        col, row = i % columns, i // columns
        x, y = col * cell_w + pad, row * cell_h + pad
        painter.drawPixmap(x, y, pix)
        painter.setPen(QColor(_Qt.GlobalColor.black))
        painter.drawText(x, y + max_h + 14, name)
        painter.setPen(QColor(_Qt.GlobalColor.gray))
        painter.drawRect(col * cell_w + 2, row * cell_h + 2, cell_w - 4, cell_h - 4)
    painter.end()
    sheet.save(str(out_path))


# --------------------------------------------------------------------------- #
# Main                                                                          #
# --------------------------------------------------------------------------- #
def main() -> Path:
    app = _app()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root = _WORKTREE_ROOT / "artifacts_claude" / f"ui_audit_{ts}"
    out_root.mkdir(parents=True, exist_ok=True)

    manifest: list[str] = [
        f"TCT cockpit UI audit capture — {ts}",
        f"config: {CONFIG_PATH}",
        f"settings isolation dir: {_SETTINGS_DIR}",
        "",
    ]

    for mode in ("light", "dark"):
        theme_dir = out_root / mode
        theme_dir.mkdir(parents=True, exist_ok=True)
        manifest.append(f"=== {mode.upper()} ===")
        thumbs: list[tuple[str, QPixmap]] = []

        settings = QSettings("TCT", "TCTSetup")
        settings.setValue("theme", mode)
        settings.sync()

        from gui.style import apply_theme
        apply_theme(app, mode)
        from gui.qml_theme import set_theme_mode
        set_theme_mode(mode)

        _capture_full_shell(mode, theme_dir, manifest, thumbs)
        _capture_qml_chrome(mode, theme_dir, manifest, thumbs)
        _capture_all_panels(mode, theme_dir, manifest, thumbs)

        sheet_path = out_root / f"contact_sheet_{mode}.png"
        _build_contact_sheet(thumbs, sheet_path)
        manifest.append(f"contact_sheet_{mode}.png")
        manifest.append("")

    (out_root / "manifest.txt").write_text("\n".join(manifest), encoding="utf-8")
    print(f"UI audit output: {out_root}")
    print("\n".join(manifest))
    return out_root


if __name__ == "__main__":
    main()
