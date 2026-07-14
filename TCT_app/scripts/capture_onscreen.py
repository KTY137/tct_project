"""ONSCREEN capture harness — real DWM compositor effects (Mica/Acrylic).

WHY
---
``scripts/capture_panels.py`` forces ``QT_QPA_PLATFORM=offscreen`` and is
therefore structurally blind to ``gui/backdrop.py``'s Windows 11 system
backdrop material: Mica/Acrylic only exist in the COMPOSITED framebuffer the
real "windows" Qt platform plugin paints into — offscreen has no compositor,
so every acrylic/mica screenshot from that harness is byte-identical to
"none". This script is the other half: it shows a real ``TCTMainWindow`` on
the REAL desktop session and grabs its pixels with an OS-level screen
capture that DOES see the composited result.

THIS IS A MANUAL-RUN TOOL, NOT PART OF THE TEST SUITE.
--------------------------------------------------------
Run it yourself, on Kaya's/Adam's real Windows desktop, never from CI or an
offscreen/headless shell — it refuses to do anything (see
:func:`check_environment`) the moment it detects ``QT_QPA_PLATFORM`` is
``offscreen``/``minimal``, the resolved Qt platform plugin is one of those,
or there is no primary screen. The matching guard test,
``tests/test_capture_onscreen_guard.py``, exercises exactly that refusal
(the suite's own ``QT_QPA_PLATFORM=offscreen`` IS the refusal case) plus the
pure ``--list`` dry run and the settings snapshot/restore helper — it never
drives a real capture.

HOW TO RUN (Kaya/Adam, on the real desktop, PowerShell, from ``TCT_app/``)
----------------------------------------------------------------------
::

    .venv/Scripts/python.exe scripts/capture_onscreen.py --list   # dry run, safe anywhere
    .venv/Scripts/python.exe scripts/capture_onscreen.py          # the real thing

Do **not** set ``QT_QPA_PLATFORM`` before the second form — that is precisely
what the guard refuses.

WHAT IT DOES
------------
1. Asserts every device in ``configs/devices.yaml`` is simulated (the same
   backend this whole app ships with) before showing anything.
2. Snapshots every ``QSettings("TCT", "TCTSetup")`` key this run could touch
   (:func:`snapshot_settings`), builds ``TCTMainWindow`` at a fixed
   position/size, and resets theme customization to a known baseline
   (``gui.style.reset_theme_customization``) so the matrix is reproducible
   regardless of whatever theme Kaya had open before.
3. Steps through the scenario matrix from :func:`build_full_plan` —
   backdrop {none, mica, acrylic} x preset {Cockpit Dark, Glass} x theme
   {dark} (+ one Lab Light spot check, + one detached-tab shot) — driving
   the SAME slots the Settings/Theme UI uses
   (``tct_gui.TCTMainWindow._open_theme_editor`` /
   ``gui.theme_editor.ThemeEditorDialog._apply`` / the backdrop combo /
   ``gui.detachable_tabs.DetachableTabWidget.detach_by_title``) — no new GUI
   logic lives here.
4. Grabs each scenario's window rect via an OS-level screen capture
   (:func:`_grab` — ``QScreen.grabWindow`` primary, GDI ``BitBlt`` fallback;
   :func:`_probe_capture_method` decides which one actually sees the DWM
   composite on THIS host, empirically, before the matrix runs) and saves
   one PNG per scenario, plus a 3-frame ~150 ms burst for the none->acrylic
   and mica->acrylic transitions (the A1/A4 flicker checklist items).
5. Restores every snapshotted QSettings key in a ``finally`` block — this
   tool must never permanently change Kaya's persisted theme/backdrop/tab
   layout, even on an exception mid-run.

OUTPUT
------
``<repo>/artifacts_claude/ui_onscreen_<UTC timestamp>/``::

    <backdrop>_<preset>_<canvas>_<theme>.png
    acrylic_default_A_dark_detached.png
    transition_none_acrylic_f0/f1/f2.png
    transition_mica_acrylic_f0/f1/f2.png
    manifest.txt   -- scenario -> file, environment, capture-method verdict

Target total runtime < 90 s.
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import traceback
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ``TCT_app/`` is this file's parent's parent; make imports (tct_gui, gui.*,
# controller.*) resolve regardless of the caller's cwd. Deliberately NO
# ``os.chdir`` here (unlike scripts/capture_panels.py) — this module is
# imported by tests/test_capture_onscreen_guard.py as part of the shared
# pytest session, and mutating the process cwd as an import side effect
# would leak into every other test collected afterward. CONFIG_PATH is
# resolved to an ABSOLUTE path below instead.
_TCT_APP = Path(__file__).resolve().parent.parent
if str(_TCT_APP) not in sys.path:
    sys.path.insert(0, str(_TCT_APP))
_REPO_ROOT = _TCT_APP.parent

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QWidget

from gui import app_settings, backdrop, style

logger = logging.getLogger(__name__)

CONFIG_PATH = str(_TCT_APP / "configs" / "devices.yaml")

# --------------------------------------------------------------------------- #
# Constants — window geometry, probe geometry, scenario vocabulary            #
# --------------------------------------------------------------------------- #

WINDOW_POS = (40, 40)
WINDOW_SIZE = (1480, 920)

# The capture-method probe's window. Its POSITION is computed at runtime from
# the live screen (:func:`_probe_pos`) — it used to be a hard-coded (60, 1000),
# which is BELOW a 1536x864-DIP desktop: the probe window was off-screen, both
# grabs returned a flat nothing, the variance was 0.0, and the harness reported
# "INCONCLUSIVE — grabWindow may not see the DWM composite". It sees it fine.
# An off-screen probe is not evidence about a capture method; it is evidence
# about arithmetic. (GL-island spike, item 4.)
_PROBE_SIZE = (240, 160)
_PROBE_DECOY_HEX = "#FF00AA"  # loud, unlikely to occur naturally behind acrylic

# Heuristic-only: population variance (over sampled pixel luminances) above
# this means "not a single flat colour" — see _pixel_variance / the
# _probe_capture_method docstring for what this stands in for.
_VARIANCE_THRESHOLD = 25.0

_DISALLOWED_PLATFORMS = {"offscreen", "minimal"}

_PRESET_DEFAULT = "Cockpit Dark"
_PRESET_GLASS = "Glass"
_PRESET_LIGHT = "Lab Light"
_DETACH_TAB_TITLE = "Motor Stage"
_PRESET_SLUGS = {_PRESET_DEFAULT: "default", _PRESET_GLASS: "glass", _PRESET_LIGHT: "lablight"}

# Probed via hasattr only — gui/backdrop.py is a PARALLEL beat's file lock;
# this script imports and calls it read-only and never pokes its private
# _CANVAS_MODE constant directly. Neither name exists today, so
# _available_canvas_modes() returns ["A"] until a beat adds one.
_CANVAS_SETTER_NAMES = ("set_canvas_mode", "set_canvas_strategy")


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


@dataclass(frozen=True)
class Scenario:
    key: str
    backdrop: str          # "none" | "mica" | "acrylic"
    theme: str              # "dark" | "light"
    preset: str             # display name, e.g. "Cockpit Dark"
    canvas: str              # "A" (only mode live today) or "B"
    detach_title: str | None = None

    @property
    def filename(self) -> str:
        preset_slug = _PRESET_SLUGS.get(self.preset, _slug(self.preset))
        base = f"{self.backdrop}_{preset_slug}_{self.canvas}_{self.theme}"
        if self.detach_title:
            base += "_detached"
        return base + ".png"


@dataclass(frozen=True)
class TransitionProbe:
    key: str
    from_backdrop: str
    to_backdrop: str
    theme: str = "dark"
    preset: str = _PRESET_DEFAULT
    canvas: str = "A"

    def frame_filename(self, index: int) -> str:
        return f"transition_{self.from_backdrop}_{self.to_backdrop}_f{index}.png"


# --------------------------------------------------------------------------- #
# Scenario matrix — pure, no Qt objects required (safe for --list)            #
# --------------------------------------------------------------------------- #

def _available_canvas_modes() -> list[str]:
    """["A"] today. gui/backdrop.py has no runtime setter for its
    module-level ``_CANVAS_MODE`` constant — probed via hasattr, never
    poked directly (this script only calls read-only/public API on that
    module, per the beat's file-lock boundary). Returns ["A", "B"] the day a
    parallel beat adds one of _CANVAS_SETTER_NAMES.
    """
    if any(hasattr(backdrop, name) for name in _CANVAS_SETTER_NAMES):
        return ["A", "B"]
    return ["A"]


def _apply_canvas_mode(canvas: str) -> None:
    """No-op for "A" (the shipped default). Best-effort call for "B" via
    whichever _CANVAS_SETTER_NAMES entry exists — speculative until a beat
    actually adds one; see _available_canvas_modes.
    """
    if canvas != "B":
        return
    for name in _CANVAS_SETTER_NAMES:
        setter = getattr(backdrop, name, None)
        if callable(setter):
            try:
                setter("no_system_background")
            except Exception:
                logger.warning(
                    "capture_onscreen: canvas-mode setter %s('no_system_background') failed",
                    name, exc_info=True)
            return


def build_full_plan() -> tuple[list[Scenario], list[TransitionProbe]]:
    """The single source of truth for both ``--list`` and the real run —
    they must never drift apart, so both consume this."""
    canvas_modes = _available_canvas_modes()
    scenarios: list[Scenario] = []
    for preset in (_PRESET_DEFAULT, _PRESET_GLASS):
        for canvas in canvas_modes:
            for bd in backdrop.BACKDROP_KINDS:
                key = f"{bd}_{_PRESET_SLUGS[preset]}_{canvas}_dark"
                scenarios.append(Scenario(
                    key=key, backdrop=bd, theme="dark", preset=preset, canvas=canvas))
    scenarios.append(Scenario(
        key="light_spot_check", backdrop="acrylic", theme="light",
        preset=_PRESET_LIGHT, canvas=canvas_modes[0]))
    scenarios.append(Scenario(
        key="detached_tab_shot", backdrop="acrylic", theme="dark",
        preset=_PRESET_DEFAULT, canvas=canvas_modes[0], detach_title=_DETACH_TAB_TITLE))
    transitions = [
        TransitionProbe(key="none_to_acrylic", from_backdrop="none", to_backdrop="acrylic"),
        TransitionProbe(key="mica_to_acrylic", from_backdrop="mica", to_backdrop="acrylic"),
    ]
    return scenarios, transitions


def _print_plan() -> None:
    scenarios, transitions = build_full_plan()
    canvas_modes = _available_canvas_modes()
    print(f"capture_onscreen.py -- dry-run plan "
          f"({len(scenarios)} scenario shot(s), {len(transitions)} transition "
          f"probe(s) x 3 frames)")
    if len(canvas_modes) == 1:
        print("canvas-mode: A only -- gui/backdrop.py exposes no runtime setter for "
              "_CANVAS_MODE today (hasattr probe found none). Mode B needs a hand-edit "
              "of that module constant plus a re-run, not this script.")
    else:
        print(f"canvas-mode: {canvas_modes} -- a runtime setter was found on gui.backdrop.")
    print()
    print("scenarios:")
    for sc in scenarios:
        tag = f"  [detach: {sc.detach_title}]" if sc.detach_title else ""
        print(f"  {sc.filename:38s} backdrop={sc.backdrop:8s} theme={sc.theme:5s} "
              f"preset={sc.preset:12s} canvas={sc.canvas}{tag}")
    print()
    print("transition bursts (3 frames, ~150 ms apart):")
    for tp in transitions:
        frames = ", ".join(tp.frame_filename(i) for i in range(3))
        print(f"  {tp.from_backdrop} -> {tp.to_backdrop}: {frames}")
    print()
    print("output directory: artifacts_claude/ui_onscreen_<UTCts>/  (manifest.txt alongside)")


# --------------------------------------------------------------------------- #
# Refuse-to-run guard                                                         #
# --------------------------------------------------------------------------- #

def check_environment(app=None) -> str | None:
    """Return a human-readable refusal reason, or ``None`` if capture may
    proceed. Checked BEFORE constructing any window or touching QSettings.

    Two independent checks, either sufficient to refuse:

    1. ``QT_QPA_PLATFORM`` env var (checked WITHOUT needing ``app`` — the
       common case: the whole pytest suite forces this to "offscreen", so
       this branch alone is what the guard test exercises).
    2. If an ``app`` (anything with ``.platformName()``/``.primaryScreen()``,
       duck-typed so a test stub works without a real QApplication) is
       passed, the resolved Qt platform plugin and primary-screen presence.
    """
    forced = os.environ.get("QT_QPA_PLATFORM", "")
    forced_first = forced.split(":")[0].strip().lower()
    if forced_first in _DISALLOWED_PLATFORMS:
        return (f"QT_QPA_PLATFORM={forced!r} selects a headless Qt platform plugin -- "
                "capture_onscreen.py must run in a real, on-screen desktop session "
                "(unset QT_QPA_PLATFORM, or simply do not export it, and try again).")
    if app is not None:
        platform_name = (app.platformName() or "").strip().lower()
        if platform_name in _DISALLOWED_PLATFORMS:
            return (f"Qt resolved the {platform_name!r} platform plugin -- no real "
                    "compositor/display is available in this session.")
        screen = app.primaryScreen()
        if screen is None:
            return "No primary screen is available (QApplication.primaryScreen() is None)."
    return None


# --------------------------------------------------------------------------- #
# QSettings snapshot / restore — this tool must never permanently change      #
# Kaya's persisted theme/backdrop/tab-layout state.                          #
# --------------------------------------------------------------------------- #

_MISSING = object()


def _declared_settings_keys() -> list[str]:
    """Every ``app_settings.*_KEY`` constant — reflection, not a
    hand-maintained duplicate list, so this can never silently drift out of
    sync with a new persisted key."""
    return sorted({v for k, v in vars(app_settings).items() if k.endswith("_KEY")})


def snapshot_settings(settings) -> dict:
    """Read every declared key from *settings*. A key that is currently
    ABSENT is recorded as ``_MISSING`` (a sentinel), not e.g. ``None`` or
    ``""`` — :func:`restore_settings` needs to tell "was empty" apart from
    "was never set" so it can ``remove()`` rather than write a phantom
    value back."""
    return {key: (settings.value(key) if settings.contains(key) else _MISSING)
            for key in _declared_settings_keys()}


def restore_settings(settings, snapshot: dict) -> None:
    """Undo whatever a capture run wrote: keys present in *snapshot* are
    written back verbatim, keys that were absent before are removed again
    (even if the run created them). Always call from a ``finally`` block."""
    for key, value in snapshot.items():
        if value is _MISSING:
            settings.remove(key)
        else:
            settings.setValue(key, value)
    settings.sync()


# --------------------------------------------------------------------------- #
# All-simulated config guard                                                  #
# --------------------------------------------------------------------------- #

_DEVICE_KEYS_REQUIRING_SIM = (
    "oscilloscope", "motor_stage", "intensity_monitor", "camera",
    "bias_supply", "waveform_generator",
)


def _is_sim_entry(entry: dict) -> bool:
    if entry.get("simulation") is True:
        return True
    return str(entry.get("backend", "")).strip().lower() == "simulated"


def _assert_all_simulated(config_path: str) -> None:
    """Refuse before constructing so much as a ``DeviceManager`` against a
    non-simulated device. This tool shows a real window on a real desktop —
    the usual offscreen-test isolation does not apply here, so the config
    itself is the only thing standing between it and real hardware."""
    import yaml

    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    problems = [key for key in _DEVICE_KEYS_REQUIRING_SIM
                if not _is_sim_entry(cfg.get(key) or {})]
    for channel in (cfg.get("slow_control") or {}).get("channels") or []:
        if str(channel.get("backend", "")).strip().lower() != "simulated":
            problems.append(f"slow_control channel {channel.get('name', '?')}")
    if problems:
        raise RuntimeError(
            "capture_onscreen refuses to run against non-simulated device(s): "
            + ", ".join(problems))


# --------------------------------------------------------------------------- #
# Event-loop settling — QTimer + a local QEventLoop, never time.sleep         #
# --------------------------------------------------------------------------- #

def _settle(ms: int = 150) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# --------------------------------------------------------------------------- #
# OS-level screen grab — the load-bearing part of this whole script           #
# --------------------------------------------------------------------------- #

def _grabwindow_grab(screen, x: int, y: int, w: int, h: int):
    """``QScreen.grabWindow(0, x, y, w, h)`` — window id 0 means "the desktop
    root", so this goes through the real compositor on Windows (Qt does not
    special-case "capture my own window" here; it is a plain screen grab).
    Returns a ``QPixmap``."""
    scr = screen or QGuiApplication.primaryScreen()
    return scr.grabWindow(0, x, y, w, h)


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _bitblt_grab(screen, x: int, y: int, w: int, h: int) -> QImage:
    """GDI ``BitBlt`` fallback (``CopyFromScreen``-equivalent), used only if
    :func:`_probe_capture_method` finds ``grabWindow`` does NOT see the DWM
    composite on this host. ``x, y, w, h`` are Qt device-independent pixels;
    GDI is DPI-blind, so they are scaled to physical pixels via the
    screen's ``devicePixelRatio()`` first. ``CAPTUREBLT`` is set explicitly
    so layered/composited windows are included in the copy (without it,
    older GDI paths can skip DWM-composited content on some hosts)."""
    scr = screen or QGuiApplication.primaryScreen()
    dpr = scr.devicePixelRatio() if scr is not None else 1.0
    px, py = round(x * dpr), round(y * dpr)
    pw, ph = max(1, round(w * dpr)), max(1, round(h * dpr))

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc_screen = user32.GetDC(0)
    if not hdc_screen:
        raise RuntimeError("GetDC(0) failed")
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, pw, ph)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        SRCCOPY = 0x00CC0020
        CAPTUREBLT = 0x40000000
        ok = gdi32.BitBlt(hdc_mem, 0, 0, pw, ph, hdc_screen, px, py, SRCCOPY | CAPTUREBLT)
        if not ok:
            raise RuntimeError("BitBlt failed")

        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = pw
        bmi.biHeight = -ph  # negative = top-down DIB, matches QImage row order
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB

        buf = (ctypes.c_ubyte * (pw * ph * 4))()
        DIB_RGB_COLORS = 0
        lines = gdi32.GetDIBits(hdc_mem, hbmp, 0, ph, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
        if lines == 0:
            raise RuntimeError("GetDIBits failed")
        img = QImage(bytes(buf), pw, ph, QImage.Format.Format_ARGB32)
        return img.copy()  # detach from the local ctypes buffer before it is freed
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)


def _grab(method: str, screen, x: int, y: int, w: int, h: int):
    if method == "bitblt":
        return _bitblt_grab(screen, x, y, w, h)
    return _grabwindow_grab(screen, x, y, w, h)


def _save(image, path: Path) -> None:
    image.save(str(path))


def _pixel_variance(image) -> float:
    """Population variance over a small sampled grid of pixel luminances —
    a cheap "does this image show more than one flat colour" signal, used
    ONLY to decide which OS-level grab call saw the real DWM composite
    during :func:`_probe_capture_method`. Not a rendering-quality metric."""
    if hasattr(image, "toImage"):
        image = image.toImage()
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    w, h = image.width(), image.height()
    if w == 0 or h == 0:
        return 0.0
    step_x, step_y = max(1, w // 12), max(1, h // 12)
    samples = []
    for yy in range(0, h, step_y):
        for xx in range(0, w, step_x):
            px = image.pixel(xx, yy)
            r, g, b = (px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF
            samples.append(0.299 * r + 0.587 * g + 0.114 * b)
    if len(samples) < 2:
        return 0.0
    mean = sum(samples) / len(samples)
    return sum((s - mean) ** 2 for s in samples) / len(samples)


def _probe_pos(app) -> tuple[int, int]:
    """Where to put the capture-method probe: ON SCREEN, and clear of the
    capture window's rect.

    Derived from the live ``availableGeometry`` instead of a hard-coded constant,
    because the constant (60, 1000) was below the bottom edge of Kaya's
    1536x864-DIP desktop — an invisible probe measures nothing and then reports
    that the capture method is broken."""
    screen = app.primaryScreen()
    if screen is None:
        return (60, 60)
    avail = screen.availableGeometry()
    w, h = _PROBE_SIZE
    # Bottom-right corner of the available area, one margin in.
    x = avail.x() + max(0, avail.width() - w - 24)
    y = avail.y() + max(0, avail.height() - h - 24)
    win_x, win_y = WINDOW_POS
    win_w, win_h = WINDOW_SIZE
    overlaps = (x < win_x + win_w and x + w > win_x
                and y < win_y + win_h and y + h > win_y)
    if overlaps:
        # The capture window covers even the corner (a small desktop): tuck the
        # probe into the top-left instead — still on screen, which is the point.
        x, y = avail.x() + 8, avail.y() + 8
    return (int(x), int(y))


def _probe_capture_method(app) -> tuple[str, str]:
    """Empirically decide grabWindow vs. BitBlt for THIS host, before the
    real matrix runs.

    Paints a small, loud solid-colour decoy widget, puts a MICA-backdropped
    probe widget directly over the SAME screen rect, and grabs that rect
    with both methods. A flat single-colour result means that method did
    NOT see the real DWM composite (the common failure mode:
    ``WA_TranslucentBackground`` silently not compositing paints solid
    black or the decoy's own flat colour, never a blend) — pixel variance
    above ``_VARIANCE_THRESHOLD`` is treated as "saw the composite".

    Returns ``(method, evidence)`` where *method* is ``"grabwindow"`` or
    ``"bitblt"`` and *evidence* is a human-readable string for the
    manifest — including an explicit "INCONCLUSIVE, needs a live eyeball"
    when neither method shows variance (e.g. this host does not actually
    support the backdrop at all)."""
    if not backdrop.is_backdrop_supported():
        return ("grabwindow",
                "backdrop.is_backdrop_supported() is False on this host (not Win11 "
                "22H2+ / not the native 'windows' Qt platform) -- cannot probe DWM "
                "compositing here. Defaulting to grabWindow, UNVERIFIED: needs a live "
                "Win11 22H2+ run to confirm either capture method.")

    decoy = QWidget()
    probe_pos = _probe_pos(app)
    decoy.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    decoy.setStyleSheet(f"background-color: {_PROBE_DECOY_HEX};")
    decoy.move(*probe_pos)
    decoy.resize(*_PROBE_SIZE)
    decoy.show()

    probe = QWidget()
    probe.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    # Alpha-capable surface BEFORE show() realizes the native window: Qt fixes a
    # top-level's surface alpha at creation, so a probe that is shown first can
    # never composite the material it is trying to detect (it would measure a
    # flat colour and blame the capture method). GL-island spike, finding 2.
    backdrop.prepare_surface(probe)
    probe.move(*probe_pos)
    probe.resize(*_PROBE_SIZE)
    probe.show()
    _settle(200)

    try:
        applied = backdrop.apply_backdrop(probe, "mica")
        if not applied:
            return ("grabwindow",
                    "backdrop.apply_backdrop(probe, 'mica') returned False -- "
                    "UNVERIFIED, needs a live run to confirm either capture method.")
        _settle(250)
        rect = probe.frameGeometry()
        # Warm-up: the first grab after a material attach can return the STALE
        # composite (the same command otherwise yields different pixels run to
        # run). Nudge the window by 1 px, put it back, settle, and throw the
        # first grab away.
        probe.move(rect.x() + 1, rect.y())
        _settle(60)
        probe.move(rect.x(), rect.y())
        _settle(120)
        try:
            _grabwindow_grab(probe.screen(), rect.x(), rect.y(),
                             rect.width(), rect.height())
        except Exception:
            pass
        _settle(60)
        results: dict[str, object] = {}
        for name, fn in (("grabwindow", _grabwindow_grab), ("bitblt", _bitblt_grab)):
            try:
                img = fn(probe.screen(), rect.x(), rect.y(), rect.width(), rect.height())
                results[name] = _pixel_variance(img)
            except Exception as exc:
                results[name] = f"ERROR: {type(exc).__name__}: {exc}"

        gw, bb = results.get("grabwindow"), results.get("bitblt")
        gw_ok = isinstance(gw, float) and gw > _VARIANCE_THRESHOLD
        bb_ok = isinstance(bb, float) and bb > _VARIANCE_THRESHOLD
        if gw_ok:
            verdict = "grabwindow"
        elif bb_ok:
            verdict = "bitblt"
        else:
            verdict = "grabwindow"  # arbitrary fallback; evidence says INCONCLUSIVE
        confirmed = "CONFIRMED " + verdict if (gw_ok or bb_ok) else "INCONCLUSIVE, needs a live eyeball"
        return verdict, (f"variance grabwindow={gw!r} bitblt={bb!r} "
                         f"threshold={_VARIANCE_THRESHOLD} -> {confirmed}")
    finally:
        try:
            backdrop.apply_backdrop(probe, "none")
        except Exception:
            pass
        probe.close()
        probe.deleteLater()
        decoy.close()
        decoy.deleteLater()
        _settle(100)


def _environment_lines(app) -> list[str]:
    lines = []
    build = None
    if sys.platform == "win32":
        try:
            build = sys.getwindowsversion().build  # type: ignore[attr-defined]
        except Exception:
            build = None
    lines.append(f"platform: {sys.platform}  Qt platform plugin: {app.platformName()}")
    lines.append(f"Windows build: {build}  backdrop.is_backdrop_supported(): "
                 f"{backdrop.is_backdrop_supported()}")
    screen = app.primaryScreen()
    if screen is not None:
        size = screen.size()
        lines.append(f"primary screen: {screen.name()!r}  size={size.width()}x{size.height()}"
                     f"  devicePixelRatio={screen.devicePixelRatio()}"
                     f"  logicalDPI={screen.logicalDotsPerInch()}")
    return lines


# --------------------------------------------------------------------------- #
# Scenario application — drives the SAME slots the Settings/Theme UI uses     #
# --------------------------------------------------------------------------- #

def _apply_scenario_state(win, sc: Scenario) -> None:
    """Same code paths a person clicking through View > Theme... uses —
    ``TCTMainWindow._open_theme_editor`` lazily builds/wires the real
    ``ThemeEditorDialog`` (its ``applyRequested`` signal is already
    connected to ``TCTMainWindow._on_theme_editor_apply``, which is what
    flips the dark-mode action / re-applies theme+backdrop+opacity+panel
    refresh — see tct_gui.py). No new GUI logic is added here."""
    win._open_theme_editor()
    editor = win._theme_editor
    editor.hide()  # never let the dialog occlude the capture region

    matches = editor._preset_list.findItems(sc.preset, Qt.MatchFlag.MatchExactly)
    if matches:
        editor._preset_list.setCurrentItem(matches[0])  # -> _on_preset_selected -> _load_preset

    idx = editor._backdrop_combo.findData(sc.backdrop)
    if idx >= 0:
        editor._backdrop_combo.setCurrentIndex(idx)  # -> _on_backdrop_changed (live preview)

    editor._apply()  # commits preset+backdrop+opacity, emits applyRequested(mode)
    _apply_canvas_mode(sc.canvas)


def _capture_scenario(win, sc: Scenario, method: str, out_root: Path,
                       manifest: list[str]) -> Path | None:
    try:
        _apply_scenario_state(win, sc)
        _settle(250)
        rect = win.frameGeometry()
        img = _grab(method, win.screen(), rect.x(), rect.y(), rect.width(), rect.height())
        path = out_root / sc.filename
        _save(img, path)
        manifest.append(f"{sc.filename}  {rect.width()}x{rect.height()}  "
                        f"backdrop={sc.backdrop} theme={sc.theme} preset={sc.preset} "
                        f"canvas={sc.canvas}")
        return path
    except Exception as exc:
        manifest.append(f"FAILED: {sc.filename}  {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None


def _capture_detached_scenario(win, sc: Scenario, method: str, out_root: Path,
                                manifest: list[str]) -> Path | None:
    try:
        _apply_scenario_state(win, sc)
        _settle(150)
        if not win._tabs.detach_by_title(sc.detach_title):
            manifest.append(f"FAILED: {sc.filename}  detach_by_title({sc.detach_title!r}) "
                            "returned False (tab title not found)")
            return None
        _settle(250)
        entry = win._tabs._detached.get(sc.detach_title)
        if entry is None:
            manifest.append(f"FAILED: {sc.filename}  detach reported ok but no window recorded")
            return None
        detached_win = entry[0]
        rect = detached_win.frameGeometry()
        img = _grab(method, detached_win.screen(), rect.x(), rect.y(), rect.width(), rect.height())
        path = out_root / sc.filename
        _save(img, path)
        manifest.append(f"{sc.filename}  {rect.width()}x{rect.height()}  "
                        f"detached window, backdrop={sc.backdrop}")
        return path
    except Exception as exc:
        manifest.append(f"FAILED: {sc.filename}  {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None
    finally:
        try:
            win._tabs.redock_all()
        except Exception:
            pass
        _settle(150)


def _capture_transition(win, tp: TransitionProbe, method: str, out_root: Path,
                        manifest: list[str]) -> None:
    try:
        _apply_scenario_state(win, Scenario(
            key=f"{tp.key}_from", backdrop=tp.from_backdrop, theme=tp.theme,
            preset=tp.preset, canvas=tp.canvas))
        _settle(300)

        editor = win._theme_editor
        idx = editor._backdrop_combo.findData(tp.to_backdrop)
        if idx >= 0:
            editor._backdrop_combo.setCurrentIndex(idx)
        editor._apply()

        rect = win.frameGeometry()
        for i in range(3):
            img = _grab(method, win.screen(), rect.x(), rect.y(), rect.width(), rect.height())
            path = out_root / tp.frame_filename(i)
            _save(img, path)
            manifest.append(f"{tp.frame_filename(i)}  {rect.width()}x{rect.height()}")
            if i < 2:
                _settle(150)
    except Exception as exc:
        manifest.append(f"FAILED: transition {tp.key}  {type(exc).__name__}: {exc}")
        traceback.print_exc()


# --------------------------------------------------------------------------- #
# The real run — never invoked by the guard test, never invoked headless      #
# --------------------------------------------------------------------------- #

def _run_capture(app) -> int:
    _assert_all_simulated(CONFIG_PATH)

    settings = app_settings.settings()
    snapshot = snapshot_settings(settings)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root = _REPO_ROOT / "artifacts_claude" / f"ui_onscreen_{ts}"
    out_root.mkdir(parents=True, exist_ok=True)

    manifest: list[str] = [f"TCT cockpit ONSCREEN capture -- {ts}", f"config: {CONFIG_PATH}", ""]
    win = None
    try:
        method, evidence = _probe_capture_method(app)
        manifest.append(f"capture method: {method}")
        manifest.append(f"probe evidence: {evidence}")
        manifest.extend(_environment_lines(app))
        manifest.append("")

        from tct_gui import TCTMainWindow

        style.reset_theme_customization()
        win = TCTMainWindow(config_path=CONFIG_PATH)
        win.move(*WINDOW_POS)
        win.resize(*WINDOW_SIZE)
        win.show()
        _settle(300)

        scenarios, transitions = build_full_plan()
        if len(_available_canvas_modes()) == 1:
            manifest.append(
                "NOTE: canvas-mode B skipped -- gui/backdrop._CANVAS_MODE has no runtime "
                "setter (hasattr probe found none); only mode A ('translucent_attr', the "
                "shipped default) was captured. Flip the module constant by hand and "
                "re-run to audit mode B.")
        manifest.append("")

        for sc in scenarios:
            if sc.detach_title:
                _capture_detached_scenario(win, sc, method, out_root, manifest)
            else:
                _capture_scenario(win, sc, method, out_root, manifest)

        # Dedicated baseline before the transition bursts (Cockpit Dark / canvas A / dark).
        _apply_scenario_state(win, Scenario(
            key="transition_baseline", backdrop="none", theme="dark",
            preset=_PRESET_DEFAULT, canvas="A"))
        _settle(200)
        for tp in transitions:
            _capture_transition(win, tp, method, out_root, manifest)
            # Reset to the FROM state of the next transition happens inside
            # _capture_transition itself (_apply_scenario_state at its top).

        manifest.append("")
        manifest.append("DONE")
        return 0
    except Exception as exc:
        manifest.append(f"FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1
    finally:
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
        restore_settings(settings, snapshot)
        (out_root / "manifest.txt").write_text("\n".join(manifest), encoding="utf-8")
        print(f"onscreen capture output: {out_root}")


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="capture_onscreen.py",
        description="ONSCREEN capture of TCTMainWindow's real DWM backdrop material. "
                    "Manual-run only -- see this file's module docstring.")
    parser.add_argument("--list", action="store_true",
                        help="Print the scenario/transition plan and exit. Pure, no "
                             "QApplication, no window -- safe to run anywhere, including headless.")
    args = parser.parse_args(argv)

    if args.list:
        _print_plan()
        return 0

    reason = check_environment()
    if reason is not None:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    app = QApplication.instance() or QApplication(sys.argv[:1])
    reason = check_environment(app)
    if reason is not None:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    return _run_capture(app)


if __name__ == "__main__":
    sys.exit(main())
