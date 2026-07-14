"""U0 GATE PROBE — does this machine actually render Qt Quick through the
OpenGL RHI backend on REAL GPU hardware, or does it silently land on a
software rasterizer (llvmpipe / WARP / "Microsoft Basic Render Driver" / any
CPU fallback masquerading as a GPU)?

This is the entry gate for the QML migration epoch (``docs/ROADMAP_MASTERPLAN.md``,
track U0). Pass criterion, verbatim from the roadmap: "QSG_RHI_BACKEND=opengl
set; probe logs GL_RENDERER == <expected bench GPU>; zero software-fallback
lines." This script proves exactly that, nothing more — it is a standalone
probe, not app code: it imports nothing from ``gui/``, ``devices/`` or
``controller/``, touches no hardware, and is never imported by the app.

MECHANISM
---------
1. ``QSG_RHI_BACKEND=opengl`` is written into ``os.environ`` (plus
   ``QSG_INFO=1`` and a widened ``QT_LOGGING_RULES``) BEFORE the first
   ``PySide6`` import — the scene graph's RHI backend is selected the moment
   the platform/scenegraph plugins are touched, so pinning it after import (or
   after a ``QGuiApplication`` exists) is too late. Same ordering rule as
   ``scripts/spikes/qml_multieffect_glass_spike.py``'s own RHI pin, which this
   script echoes with an explicit ``QQuickWindow.setGraphicsApi(OpenGL)`` call
   as belt-and-suspenders.
2. A ``qInstallMessageHandler`` is installed before the ``QGuiApplication`` is
   built, capturing EVERY line the Qt logging system emits (any category, any
   thread, any level) into an in-memory list — this is the full "capture" the
   ``--log`` file dumps, and the haystack the software-fallback scan reads.
3. A minimal ``QQuickView`` loads one inline ``Rectangle`` — real, on-screen
   window (never ``QT_QPA_PLATFORM=offscreen``: the whole point is pinning the
   real GPU present path, which an offscreen surface cannot exercise). The
   script refuses early if ``QT_QPA_PLATFORM`` already forces a headless
   platform.
4. Two hooks answer the two must-appear-verbatim facts:
     * ``graphicsApi`` — read from ``QQuickWindow.rendererInterface()
       .graphicsApi()`` inside ``afterRendering`` (render thread, direct
       connection) once the first frame has actually rendered: the scene
       graph's real, negotiated backend, not merely "what was requested".
     * ``GL_RENDERER`` (+ VENDOR/VERSION) — queried with a bare
       ``glGetString`` call against ``opengl32.dll`` via ``ctypes`` (no
       PyOpenGL — the project removed that dependency 2026-07-13, see
       ``requirements.txt``), from inside the SAME render-thread hook, where
       ``QOpenGLContext.currentContext()`` is guaranteed non-null for the
       OpenGL RHI backend. This is Qt's own documented pattern for raw-GL
       access from ``beforeRendering``/``afterRendering`` (the "OpenGL Under
       QML" example uses the identical direct-connection idiom).
   Both hooks only read; they emit a Qt signal (``Probe.frameCaptured``) back
   to a main-thread ``QObject`` receiver rather than touching the app/timers
   directly from the render thread — the one Qt-thread-safety rule that
   matters here.
5. After the first frame: every captured log line (plus the GL strings
   themselves, belt-and-suspenders) is scanned, case-insensitively, for the
   fixed marker list below. Any hit fails the gate outright.
6. A dual watchdog guarantees this can never hang a gate: a 15 s Qt ``QTimer``
   tries a graceful ``app.quit()``; an independent watchdog spawned as its
   OWN process (own interpreter, own GIL) force-terminates this process a
   few seconds later if the graceful path itself got stuck. This is not
   theoretical: an in-process ``threading.Timer`` was tried first and
   measured to be insufficient — see the comment on ``_spawn_hard_watchdog``
   for why only an out-of-process kill can be trusted here. The teardown
   path also restores Qt's default (GIL-free) message handler before
   quitting — see the comment on ``_Runner._finish`` for the deadlock this
   avoids (also measured, not theoretical).

RUN (real desktop session only — this is not the offscreen test suite)
------------------------------------------------------------------------
::

    cd TCT_app
    .venv/Scripts/python.exe scripts/rhi_gl_probe.py
    .venv/Scripts/python.exe scripts/rhi_gl_probe.py --expect "RTX 5080" --log artifacts_claude/rhi_gl_probe_bench.log

Exit codes: ``0`` PASS, ``2`` FAIL (a check failed, including a refused
offscreen environment), ``3`` watchdog timeout (no frame ever rendered).
"""
from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# ENVIRONMENT MUST BE PINNED BEFORE THE FIRST PySide6 IMPORT.                  #
# --------------------------------------------------------------------------- #
# QSG_RHI_BACKEND selects the Qt Quick scene graph's RHI backend at
# QRhi-creation time, deep inside the platform/scenegraph plugin machinery
# that gets touched the moment PySide6.QtGui / PySide6.QtQuick is imported.
# Setting it after import — or after a QGuiApplication exists — is too late.
os.environ["QSG_RHI_BACKEND"] = "opengl"
# QSG_INFO=1: the legacy switch that makes Qt Quick announce backend/driver
# info at startup. QT_LOGGING_RULES widens the RHI/scenegraph/platform debug
# categories so anything Qt logs through qCDebug (the modern, Qt6 path for
# this kind of diagnostic) reaches the message handler installed below.
os.environ["QSG_INFO"] = "1"
os.environ["QT_LOGGING_RULES"] = "qt.rhi.*=true;qt.scenegraph.*=true;qt.qpa.*=true"

_LOG_LINES: list[str] = []


def _qt_message_handler(msg_type, context, message) -> None:
    """Captures EVERY line the Qt logging system emits, any thread, any
    category, any level. Runs AFTER category filtering — it only sees what
    QT_LOGGING_RULES above already let through, which is why that rule exists.
    Append is used deliberately (not a lock): CPython's GIL makes a single
    ``list.append`` atomic, which is all the thread-safety a flat log needs
    here — this handler can fire from the render thread as well as the GUI
    thread."""
    from PySide6.QtCore import QtMsgType
    names = {
        QtMsgType.QtDebugMsg: "DEBUG", QtMsgType.QtInfoMsg: "INFO",
        QtMsgType.QtWarningMsg: "WARNING", QtMsgType.QtCriticalMsg: "CRITICAL",
        QtMsgType.QtFatalMsg: "FATAL",
    }
    cat = context.category if context and context.category else "default"
    _LOG_LINES.append(f"[{names.get(msg_type, msg_type)}] {cat}: {message}")


# PySide6 imported only now — after the environment above is pinned.
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QGuiApplication, QOpenGLContext  # noqa: E402
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface  # noqa: E402

_DISALLOWED_PLATFORMS = {"offscreen", "minimal"}

# Fixed, case-insensitive software-fallback marker list — the U0 gate contract.
_SOFTWARE_MARKERS = (
    "llvmpipe",
    "microsoft basic render",
    "warp",
    "software adapter",
    "software renderer",
    "falling back",
)

_GL_RENDERER = 0x1F01
_GL_VENDOR = 0x1F00
_GL_VERSION = 0x1F02

_GA_OPENGL_VALUE = QSGRendererInterface.GraphicsApi.OpenGL.value

_QML = """
import QtQuick

Rectangle {
    width: 320
    height: 200
    color: "#202030"
    Text {
        anchors.centerIn: parent
        color: "#E6E9EF"
        text: "rhi_gl_probe"
    }
}
"""


def _query_gl_strings() -> tuple[str | None, str | None, str | None, str | None]:
    """Bare ``glGetString`` via ctypes — no PyOpenGL (removed from this repo
    2026-07-13; see ``requirements.txt``). Returns
    ``(renderer, vendor, version, error)``; only one of the first three or
    the last is meaningfully populated."""
    try:
        if sys.platform == "win32":
            gl = ctypes.WinDLL("opengl32.dll")
        else:
            gl = ctypes.CDLL("libGL.so.1")
        gl.glGetString.restype = ctypes.c_char_p
        gl.glGetString.argtypes = [ctypes.c_uint]
        renderer = gl.glGetString(_GL_RENDERER)
        vendor = gl.glGetString(_GL_VENDOR)
        version = gl.glGetString(_GL_VERSION)
        dec = lambda b: b.decode("utf-8", "replace") if b else None  # noqa: E731
        return dec(renderer), dec(vendor), dec(version), None
    except Exception as exc:
        return None, None, None, f"{type(exc).__name__}: {exc}"


class Probe(QObject):
    """Holds every fact the two render-thread hooks capture. Lives on the
    main thread (constructed there, before any rendering starts) so that
    ``frameCaptured`` resolves to a real Queued connection when emitted from
    the render thread — the one piece of cross-thread Qt plumbing this script
    depends on being correct."""

    frameCaptured = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.frame_count = 0
        self.sg_init_count = 0
        self.sg_errors: list[str] = []
        self.captured = False
        self.graphics_api_value: int | None = None
        self.graphics_api_name: str | None = None
        self.gl_renderer: str | None = None
        self.gl_vendor: str | None = None
        self.gl_version: str | None = None
        self.gl_error: str | None = None

    def on_scene_graph_initialized(self) -> None:
        self.sg_init_count += 1

    def on_scene_graph_error(self, error, message) -> None:
        self.sg_errors.append(f"{error}: {message}")

    def on_after_rendering(self, window: QQuickWindow) -> None:
        """RENDER THREAD (must be connected with DirectConnection). Read-only:
        no GUI object mutation, only the two introspection APIs Qt documents
        as safe to call from this exact hook — ``rendererInterface()`` (the
        "OpenGL Under QML" example's own pattern) and
        ``QOpenGLContext.currentContext()`` (thread-local by construction, so
        this call is safe from any thread on its own)."""
        self.frame_count += 1
        if self.captured:
            return
        self.captured = True

        try:
            api = window.rendererInterface().graphicsApi()
            self.graphics_api_value = int(api.value)
            self.graphics_api_name = getattr(api, "name", str(api))
        except Exception as exc:
            self.graphics_api_name = f"ERROR: {type(exc).__name__}: {exc}"

        ctx = QOpenGLContext.currentContext()
        if ctx is None:
            self.gl_error = "QOpenGLContext.currentContext() is None on the render thread"
        else:
            renderer, vendor, version, err = _query_gl_strings()
            self.gl_renderer, self.gl_vendor, self.gl_version, self.gl_error = (
                renderer, vendor, version, err)

        self.frameCaptured.emit()


class _Runner(QObject):
    """Main-thread receiver for both end conditions (frame captured / watchdog
    timeout). Connecting to a bound method of a QObject that lives on the main
    thread is what lets Qt resolve the cross-thread ``frameCaptured`` signal
    to a genuine QueuedConnection — a lambda has no thread affinity for Qt to
    resolve against, so this script never connects one across threads."""

    def __init__(self, app: QGuiApplication, watchdog: QTimer) -> None:
        super().__init__()
        self.app = app
        self.watchdog = watchdog
        self.timed_out = False
        self._done = False

    def finish_captured(self) -> None:
        self._finish(timed_out=False)

    def finish_timeout(self) -> None:
        self._finish(timed_out=True)

    def _finish(self, timed_out: bool) -> None:
        if self._done:
            return
        self._done = True
        self.timed_out = timed_out
        self.watchdog.stop()
        # Restore Qt's own (GIL-free) default message handler BEFORE quitting.
        # Measured on this host: a Python qInstallMessageHandler still installed
        # during QQuickWindow/RHI teardown deadlocks -- the GUI thread blocks
        # waiting for the render thread to finish tearing down while the render
        # thread's own teardown-time qt.scenegraph/qt.rhi log line (enabled by
        # the widened QT_LOGGING_RULES pin) needs the GIL to reach our handler,
        # and the GUI thread holds it for the whole blocking wait. Every log
        # line worth scanning already happened by the time a frame was
        # captured (or the watchdog fired), so nothing is lost by switching
        # back to the default handler here.
        qInstallMessageHandler(None)
        QTimer.singleShot(30, self.app.quit)


def _scan_for_software_fallback(haystack: list[str]) -> list[str]:
    hits: list[str] = []
    for line in haystack:
        low = line.lower()
        for marker in _SOFTWARE_MARKERS:
            if marker in low:
                hits.append(f"{marker!r} in: {line}")
    return hits


def _build_report(probe: Probe, timed_out: bool, expect: str | None,
                  qml_errors: list[str], log_lines: list[str]) -> tuple[str, int]:
    checks: list[tuple[str, bool | None, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))

    add("qsg_rhi_backend_env", os.environ.get("QSG_RHI_BACKEND") == "opengl",
        f"QSG_RHI_BACKEND={os.environ.get('QSG_RHI_BACKEND')!r}")

    if timed_out:
        add("frame_rendered", False, "WATCHDOG TIMEOUT -- no frame was captured in time")
    else:
        add("frame_rendered", probe.captured and probe.frame_count > 0,
            f"frames_rendered={probe.frame_count}")

    api_ok = probe.graphics_api_value == _GA_OPENGL_VALUE
    add("graphics_api", api_ok,
        f"graphicsApi={probe.graphics_api_name!r} (value={probe.graphics_api_value}, "
        f"expected value={_GA_OPENGL_VALUE} = OpenGL/OpenGLRhi)")

    gl_ok = bool(probe.gl_renderer)
    detail = f"GL_RENDERER={probe.gl_renderer!r}"
    if probe.gl_error:
        detail += f"  error={probe.gl_error}"
    add("gl_renderer_captured", gl_ok, detail)

    haystack = list(log_lines)
    for extra in (probe.gl_renderer, probe.gl_vendor, probe.gl_version):
        if extra:
            haystack.append(extra)
    hits = _scan_for_software_fallback(haystack)
    hit_detail = f"{len(hits)} marker hit(s) across {len(haystack)} line(s)"
    if hits:
        hit_detail += "".join(f"\n      - {h}" for h in hits)
    add("software_fallback_scan", len(hits) == 0, hit_detail)

    if expect:
        if gl_ok:
            match = expect.lower() in (probe.gl_renderer or "").lower()
            add("gl_expect_match", match,
                f"--expect {expect!r} {'FOUND' if match else 'NOT FOUND'} in GL_RENDERER")
        else:
            add("gl_expect_match", False,
                f"--expect {expect!r} -- cannot check, GL_RENDERER not captured")
    else:
        checks.append(("gl_expect_match", None, "--expect not given (report-only)"))

    if probe.sg_errors:
        add("scene_graph_errors", False, "; ".join(probe.sg_errors))
    if qml_errors:
        add("qml_load_errors", False, "; ".join(qml_errors))

    scored = [ok for _, ok, _ in checks if ok is not None]
    overall_pass = bool(scored) and all(scored) and not timed_out

    if timed_out:
        exit_code = 3
    elif overall_pass:
        exit_code = 0
    else:
        exit_code = 2

    lines: list[str] = []
    lines.append("=" * 88)
    verdict_word = "TIMEOUT" if timed_out else ("PASS" if overall_pass else "FAIL")
    lines.append(f"RHI/GL PIN PROBE VERDICT: {verdict_word}   (exit code {exit_code})")
    lines.append("=" * 88)
    for name, ok, detail in checks:
        tag = "PASS" if ok else ("INFO" if ok is None else "FAIL")
        lines.append(f"  [{tag}] {name:<24s} {detail}")
    lines.append("-" * 88)
    lines.append(f"graphics_api      : {probe.graphics_api_name}")
    lines.append(f"gl_renderer       : {probe.gl_renderer}")
    lines.append(f"gl_vendor         : {probe.gl_vendor}")
    lines.append(f"gl_version        : {probe.gl_version}")
    lines.append(f"frames_rendered   : {probe.frame_count}")
    lines.append(f"sg_init_count     : {probe.sg_init_count}")
    lines.append(f"qml_errors        : {qml_errors}")
    lines.append(f"captured_log_lines: {len(log_lines)}")
    lines.append("=" * 88)
    return "\n".join(lines), exit_code


def _spawn_hard_watchdog(pid: int, seconds: float) -> subprocess.Popen:
    """A watchdog running in its OWN process (own interpreter, own GIL).

    MEASURED, not theoretical: an in-process ``threading.Timer`` hard-kill was
    tried first and never fired -- this script's main thread can be blocked
    inside Qt/render-thread teardown for the ENTIRE duration of ``app.exec()``
    without the GIL ever coming free for another Python thread in the same
    process (see ``_Runner._finish`` for the specific deadlock that produced
    this). ``TerminateProcess`` (what ``os.kill`` maps to on Windows) does not
    care what this process's GIL is doing, so a watchdog in its own process is
    the only mechanism that can truly guarantee the gate exits.
    ``os.kill(pid, 3)`` on Windows terminates the target process WITH exit
    code 3 -- a hard-killed run still reports the documented watchdog-timeout
    code, even though it never gets to print a report of its own."""
    code = ("import os, time\n"
            f"time.sleep({seconds})\n"
            f"try:\n    os.kill({pid}, 3)\nexcept Exception:\n    pass\n")
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen([sys.executable, "-c", code], creationflags=creationflags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rhi_gl_probe.py",
        description="U0 gate probe: proves Qt Quick renders through the OpenGL "
                     "RHI backend on real GPU hardware (no software fallback).")
    ap.add_argument("--expect", default=None,
                    help="case-insensitive substring GL_RENDERER must contain "
                         "(e.g. the bench GPU name); mismatch = FAIL, omitted = "
                         "report-only")
    ap.add_argument("--log", default=None, type=Path,
                    help="also write the full capture + verdict to this file")
    args = ap.parse_args(argv)

    forced = os.environ.get("QT_QPA_PLATFORM", "").lower()
    if forced in _DISALLOWED_PLATFORMS:
        msg = (f"REFUSED: QT_QPA_PLATFORM={forced!r} selects a headless Qt platform "
               "plugin -- this probe needs a REAL on-screen GPU present path "
               "(unset QT_QPA_PLATFORM and try again).")
        print(msg, file=sys.stderr)
        return 2

    qInstallMessageHandler(_qt_message_handler)

    # Belt-and-suspenders with the env var pin above, and in the same order as
    # scripts/spikes/qml_multieffect_glass_spike.py: before the QGuiApplication.
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

    probe = Probe()
    view = QQuickView()
    view.setTitle("rhi_gl_probe (U0 gate)")
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)

    tmp_qml = Path(tempfile.gettempdir()) / "tct_rhi_gl_probe.qml"
    tmp_qml.write_text(_QML, encoding="utf-8")
    view.setSource(QUrl.fromLocalFile(str(tmp_qml)))
    qml_errors = [str(e) for e in view.errors()]

    view.sceneGraphInitialized.connect(probe.on_scene_graph_initialized)
    view.sceneGraphError.connect(probe.on_scene_graph_error)
    # DirectConnection: this hook MUST run on the render thread, synchronously,
    # while the OpenGL context is still current (see Probe.on_after_rendering).
    view.afterRendering.connect(lambda: probe.on_after_rendering(view),
                                Qt.ConnectionType.DirectConnection)

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    runner = _Runner(app, watchdog)
    watchdog.timeout.connect(runner.finish_timeout)
    watchdog.start(15000)
    # QueuedConnection, explicit: probe.frameCaptured is emitted from the
    # render thread; runner lives on the main thread. Forcing the type here
    # removes any dependence on Qt's auto-resolution for this connection.
    probe.frameCaptured.connect(runner.finish_captured, Qt.ConnectionType.QueuedConnection)

    # Independent, out-of-process hard kill: an in-process threading.Timer is
    # NOT enough here -- if the main thread is stuck inside a single blocking
    # C/driver call, CPython never releases the GIL for that call and no
    # Python thread in THIS process, Qt timer or otherwise, can ever run. A
    # watchdog spawned as its OWN process has its own interpreter and GIL and
    # calls TerminateProcess on our PID regardless of what this process is
    # stuck in.
    watchdog_proc = _spawn_hard_watchdog(os.getpid(), 25.0)

    view.show()
    app.exec()
    try:
        watchdog_proc.terminate()
    except Exception:
        pass

    report_text, exit_code = _build_report(probe, runner.timed_out, args.expect,
                                           qml_errors, list(_LOG_LINES))
    print(report_text)

    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        full = [f"rhi_gl_probe run: {ts}", "", report_text, "", "-" * 88,
                "FULL CAPTURED LOG", "-" * 88]
        full.extend(_LOG_LINES if _LOG_LINES else ["(no Qt log lines captured)"])
        args.log.write_text("\n".join(full), encoding="utf-8")
        print(f"\nfull capture + verdict written to: {args.log}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
