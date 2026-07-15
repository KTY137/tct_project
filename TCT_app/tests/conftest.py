"""Shared test infrastructure for the headless GUI suite.

1. Makes the TCT_app package root importable (the app itself relies on being
   run from the TCT_app directory, so tests do the same via sys.path).

2. Drains Qt deferred deletions after every test (T6, added 2026-07-10):
   the suite runs ~690 tests inside ONE offscreen ``QApplication``. Widgets
   scheduled with ``deleteLater()`` are never actually destroyed — no test
   returns control to the Qt event loop, so posted ``DeferredDelete`` events
   pile up and every dead panel (and its pyqtgraph scene) stays alive. Past a
   threshold this wedged pyqtgraph paints inside ``QWidget.grab()`` mid-suite
   (pytest-timeout abort at a GUI test that passes in isolation — the abort
   location depends only on how many GUI tests ran before it). The autouse
   fixture below flushes destructions after EVERY test so no test depends on
   the accumulated Qt state of the tests before it. It deliberately does NOT
   close or delete widgets a test created — only completes destructions the
   test itself already requested.

3. Isolates PROCESS-GLOBAL state that leaks between tests (D3, 2026-07-13) —
   the defect that made the parallel suite (``-n auto``) untrustworthy: tests
   that pass alone and pass serially failed under xdist, because the workers
   slice the suite differently and a leaked global then lands on a *different*
   victim test each run. Two leak classes are closed here:

   * ``QSettings("TCT", "TCTSetup")`` — repointed at a per-process throwaway
     .ini, so no test can read (or WRITE) the developer's real persisted
     settings, and no two xdist workers can stomp each other through one
     shared registry key. This used to happen only as a side effect of
     importing ``tests/test_ui_monkey.py``, i.e. it silently did not apply to
     any subset run that did not collect that file.
   * ``gui.style`` theme-customization module globals (glass amount, palette
     overrides, typography, radius scale — and the LIGHT/DARK dicts they
     recompute in place). A test that customizes the theme and does not reset
     it changes what every LATER test on that worker sees.
"""
from __future__ import annotations

import gc
import os
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore
from PySide6.QtCore import QSettings

# --------------------------------------------------------------------------- #
# QSettings redirection — runs at conftest IMPORT, i.e. before collection, so  #
# before any test module's import-time code, before any gui module is imported #
# and long before any window is built.                                         #
#                                                                              #
# Why the shim and not just setDefaultFormat(): Qt applies the default format  #
# ONLY to the ``QSettings(parent)`` constructor, and on Windows ``setPath`` is #
# ignored for NativeFormat. Every consumer in this app names the store          #
# explicitly — ``QSettings("TCT", "TCTSetup")`` (gui/bias_panel.py:222,        #
# tct_gui.py, gui/style.py::_default_settings, ...) — so those calls kept      #
# resolving to the REAL registry key HKCU\Software\TCT\TCTSetup no matter what #
# the format defaults said. (This is why the redirect that used to live at the #
# top of tests/test_ui_monkey.py never actually took: the monkey has been      #
# clicking the developer's real theme/geometry settings.)                      #
#                                                                              #
# Under xdist that registry key is ALSO shared by every worker process, so a   #
# test writing "theme" in worker A changed what a panel built in worker B read #
# mid-construction — a cross-process leak that cannot happen serially and that #
# picks a different victim test every run. Below, the (org, app) form is       #
# rewritten to an INI store under a per-process temp dir; every other overload #
# (e.g. QSettings(path, IniFormat) in tests) passes through untouched.         #
# --------------------------------------------------------------------------- #
_SETTINGS_DIR = tempfile.mkdtemp(prefix="tct_tests_settings_")
_RealQSettings = QSettings


class _IsolatedQSettings(_RealQSettings):
    """QSettings that can never reach the user's real per-app store."""

    def __init__(self, *args, **kwargs):
        if (len(args) == 2 and not kwargs
                and all(isinstance(a, str) for a in args)):
            super().__init__(_RealQSettings.Format.IniFormat,
                             _RealQSettings.Scope.UserScope, args[0], args[1])
        else:
            super().__init__(*args, **kwargs)


QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  _SETTINGS_DIR)
QSettings.setDefaultFormat(QSettings.Format.IniFormat)   # QSettings(parent) form
QtCore.QSettings = _IsolatedQSettings                    # (org, app) form


@pytest.fixture(autouse=True, scope="session")
def _real_qapplication():
    """Create ONE real, offscreen ``QApplication`` before any test runs.

    THE BUG THIS CLOSES. Several VM-only test files use a file-local house
    pattern (``QCoreApplication.instance() or QCoreApplication([])``) so a
    bare ``QObject``-only suite never needs a full ``QApplication``. Widget
    test files use the sibling pattern (``QApplication.instance() or
    QApplication([])``). Both read ``.instance()`` first — and Qt's
    ``.instance()`` returns the ONE process-wide singleton regardless of
    which subclass asks, so if a VM-only file happened to run FIRST in the
    process it would create a bare ``QCoreApplication`` that every later
    widget file's ``.instance()`` call finds truthy and reuses. The first
    widget any test then constructs hits Qt's native fail-fast ("QWidget:
    Must construct a QApplication before a QWidget") — an unrecoverable
    process crash, not a Python exception (measured: mixed-order run of a
    VM file then a widget file, exit code from a native abort, no pytest
    summary at all).

    THE FIX. Session scope is a fixed pytest contract, not a convention:
    pytest sets up higher-scoped fixtures BEFORE any lower-scoped fixture
    or test body and tears them down LAST — so this autouse fixture is
    guaranteed to run before every file's own ``_app()`` helper gets a
    chance to run (those only execute inside a test body, never at
    collection/import time). Creating the real ``QApplication`` HERE means
    every later ``.instance()`` call in the suite, Core-flavoured or not,
    finds this one and can never fall through to construct a bare
    ``QCoreApplication``. This does not weaken the no-widget boundary the
    VM suites are asserting: that boundary is the standing-law pair
    (``test_read_only_no_command_surface`` / ``test_owns_no_timer_no_thread``,
    S2 Ruling Q3) checking the VIEWMODEL's own attributes/children, not the
    application class it happens to run under.

    The isinstance guard in ``_reap_leaked_toplevel_widgets`` below stays
    regardless (belt and braces) — this fixture removes the ORDINARY path
    to a bare-QCoreApplication singleton; it does not forbid one, since a
    test could still call ``QCoreApplication()`` directly rather than
    through ``.instance()``.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _isolate_style_globals():
    """Restore ``gui.style``'s theme-customization globals after every test.

    ``gui/style.py`` keeps the user's theme knobs in module globals and
    recomputes the LIGHT/DARK palettes *in place* (dict identity is part of
    the contract — ``apply_theme`` checks ``palette is DARK``). Anything a
    test applies therefore persists into the rest of that process. Restoring
    only when the state actually moved keeps the common case free.
    """
    from gui import style

    before = (style.get_glass_amount(), style.theme_overrides("light"),
              style.theme_overrides("dark"), style.typography(),
              style.radius_scale())
    yield
    after = (style.get_glass_amount(), style.theme_overrides("light"),
             style.theme_overrides("dark"), style.typography(),
             style.radius_scale())
    if after != before:
        style.reset_theme_customization()


@pytest.fixture(autouse=True)
def _flush_qt_deferred_deletes():
    yield
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    # Collect Python-side garbage first: dropping the last Python reference
    # to a QWidget schedules its C++ deletion, which the drain below flushes.
    gc.collect()
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


# --------------------------------------------------------------------------- #
# Widget-pile reaper (2026-07-14) — the fix for the RED bench gate.            #
#                                                                              #
# THE BUG. A panel that a test merely drops is NEVER freed, even though the    #
# fixture above already runs gc.collect(). Measured: one `AnalysisPanel()`     #
# constructed and dropped leaves **835 live QWidgets and 102 top-levels**      #
# behind, every single time. Across the ~75 analysis-panel tests the pile      #
# reached 62,625 widgets / 7,650 top-levels by test 97 of 2600.                #
#                                                                              #
# WHY gc CANNOT SEE IT. gui/analysis_panel.py:334 connects a *lambda* that     #
# captures ``self`` to a signal owned by ``self._segmented`` — a CHILD:        #
#                                                                              #
#     self._segmented.selection_changed.connect(                               #
#         lambda key: fade_swap(self._modes, ...))          # captures self    #
#                                                                              #
# panel -> child -> (C++ connection storage) -> lambda -> cell -> panel. The   #
# cycle is real, but one hop of it lives inside PySide6's C++ connection list, #
# which Python's garbage collector cannot traverse. So gc never sees a cycle   #
# to break, and the whole 835-widget tree is immortal. A bound-method slot     #
# does NOT do this (PySide6 holds those weakly) — only a lambda/closure. The   #
# pattern appears in 14 gui/ modules, so this is a CLASS of leak, not one bug. #
#                                                                              #
# WHY IT KILLED THE BENCH. ``apply_theme`` ends in ``QApplication.setStyleSheet``,#
# which repolishes EVERY live widget: measured O(N) at ~0.3-0.5 ms per widget. #
# At 3.3k widgets (the real app) that is 1.7 s; at 62k it is ~17 s; and a      #
# theme-switch test that toggles a few times then blows through the 60 s       #
# pytest-timeout. ``timeout_method = thread`` aborts with ``os._exit`` — while #
# Qt is mid-repolish and a camera poll thread is live — and THAT race is the   #
# 0xC0000005 access violation. The AV is the symptom; the pile is the disease. #
# (Proven: the same tests pass under ``--timeout=300``.)                       #
#                                                                              #
# THE FIX. ``deleteLater()`` destroys the C++ object, which tears down the     #
# connection, which releases the lambda, which breaks the cycle — so the tree  #
# is reclaimed in full (measured: delta 0 widgets over repeated construct/     #
# destroy cycles). Rather than retrofit ~75 call sites (and re-break on the    #
# next panel test someone writes), destroy, after every test, the top-level    #
# widgets that test created and nobody still holds.                            #
#                                                                              #
# WHAT IS PROTECTED. Widgets a still-live fixture legitimately holds ACROSS    #
# tests (13 module/session-scoped fixtures do this on purpose — e.g.           #
# tests/test_ribbon_never_clips.py's one-window-per-module ``win``) and        #
# widgets parked in a test module's globals. Those are read out of pytest's    #
# own fixture cache, so a fixture that is still active can never be reaped.    #
# Popups (QMenu/QDialog, e.g. pyqtgraph's parentless ViewBoxMenu/QColorDialog) #
# are deliberately NOT touched: they are owned by Python refs inside the panel #
# and die with it. Deleting them out from under a half-destroyed pyqtgraph     #
# item is exactly the dangling-wrapper hazard gui/style.py already warns about.#
# --------------------------------------------------------------------------- #
def _is_app_owned(widget) -> bool:
    """True for a widget class THIS APP defines (``gui.*`` / ``tct_gui``).

    Only these are reaped. A panel keeps strong Python references to parentless
    helper widgets that pyqtgraph creates for it — a ``ViewBoxMenu``, a
    ``ColorMapMenu`` and its ``QWidgetAction``'s bare ``QWidget``/``QFrame``,
    a ``QColorDialog`` — and *those* are top-level too. Deleting one of them
    directly rips it out from under the pyqtgraph item that still holds it and
    aborts Qt in the DeferredDelete drain (measured, not theorised: the first
    cut of this reaper did exactly that). Destroying the PANEL instead tears
    down its connections, drops those references, and gc reclaims every one of
    them — the full 835-widget tree, delta 0. Own the root; the leaves follow."""
    module = type(widget).__module__ or ""
    return module == "tct_gui" or module.startswith("gui.")


def _protected_widget_ids(session):
    """Every QWidget a still-live pytest fixture — or a test module global —
    legitimately holds. Read from pytest's own fixture cache, so a
    module/session-scoped fixture's widget can never be reaped while it is
    still in use; its own finalizer stays responsible for it."""
    from PySide6.QtWidgets import QWidget

    protected: set[int] = set()

    def add(value, depth=0):
        if value is None or depth > 2:
            return
        if isinstance(value, QWidget):
            protected.add(id(value))
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                add(item, depth + 1)
        elif isinstance(value, dict):
            for item in value.values():
                add(item, depth + 1)
        elif depth < 2 and hasattr(value, "__dict__"):
            try:                       # a fixture may yield a holder object
                members = list(vars(value).values())
            except (RuntimeError, ReferenceError, TypeError):
                return
            for item in members:
                add(item, depth + 1)

    manager = getattr(session, "_fixturemanager", None)
    for fixturedefs in getattr(manager, "_arg2fixturedefs", {}).values():
        for fixturedef in fixturedefs:
            cached = getattr(fixturedef, "cached_result", None)
            if cached:                 # (value, cache_key, exc) — None when torn down
                add(cached[0])

    for name, module in list(sys.modules.items()):
        if not (name.startswith("test_") or ".test_" in name):
            continue
        try:
            members = list(vars(module).values())
        except (RuntimeError, ReferenceError):
            continue
        for item in members:
            if isinstance(item, QWidget):
                protected.add(id(item))
    return protected


@pytest.fixture(autouse=True)
def _reap_leaked_toplevel_widgets(request):
    """Destroy the top-level widgets a test created and then abandoned.

    Defined AFTER ``_flush_qt_deferred_deletes`` so that (same scope, same
    file) its teardown runs FIRST: it reaps, then the flush above drains what
    the reaping scheduled.

    Escape hatch: ``TCT_DISABLE_WIDGET_REAPER=1`` turns it off, so a suspected
    reaper-induced failure can be bisected against the un-reaped suite without
    editing this file."""
    from PySide6.QtWidgets import QApplication

    if os.environ.get("TCT_DISABLE_WIDGET_REAPER") == "1":
        yield
        return

    app = QApplication.instance()
    # A viewmodel-only suite runs under a bare QCoreApplication (house
    # pattern for ISOLATION runs) — it has no topLevelWidgets() to reap by
    # construction, so skip this teardown step entirely rather than AttributeError.
    before = {id(w) for w in app.topLevelWidgets()} if isinstance(app, QApplication) else set()
    yield

    from PySide6.QtCore import QEvent

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return

    # Let Python free whatever it CAN first; only the C++-cycle leaks survive.
    gc.collect()
    app.sendPostedEvents(None, QEvent.DeferredDelete)

    protected = _protected_widget_ids(request.session)
    doomed = [
        w for w in app.topLevelWidgets()
        if id(w) not in before and id(w) not in protected
        and _is_app_owned(w)
    ]
    if not doomed:
        return

    for widget in doomed:
        # ---- 1. shutdown(): the app's own thread-teardown contract ---------- #
        # A panel parks its poller/worker QThread on the long-lived QApplication
        # (see the thread-guard note below) and relies on shutdown() to quit it;
        # TCTMainWindow._teardown_panels calls it for exactly this reason.
        #
        # THE RULE, and it is a safety rule, not a convenience: if we could not
        # complete a panel's shutdown, we do NOT destroy it. Tearing a panel's
        # C++ object out from under a worker thread that is still running is an
        # access violation — measured twice: reaping MotorPanel with no shutdown
        # at all segfaulted tests/test_motor_icon_theming.py, and destroying one
        # whose shutdown() had raised crashed tests/test_motor_panel_reload.py
        # (its fakes deliberately leave a stuck worker that ignores stop()).
        # Leaking such a panel is the strictly safer failure: it costs widgets,
        # not a dead process, and the session-end thread guard still catches it.
        shutdown = getattr(widget, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except (RuntimeError, ReferenceError):
                continue        # C++ gone, or teardown half-done — leave it be
            except Exception:
                continue        # unknown thread state -> do NOT destroy

        # ---- 2. close(): a WINDOW's closeEvent runs the real teardown -------- #
        # Unlike shutdown(), a raising close() does NOT mean "threads may still
        # be running". These tests tear their own window down first
        # (tests/test_qml_shell.py::_destroy calls _teardown_panels(), then
        # deleteLater()), so our close() drives a SECOND _teardown_panels() and
        # trips over an already-deleted QTimer. The threads are, by then,
        # provably stopped — by the test's own successful teardown. Skipping the
        # destroy on that exception is what stranded a whole TCTMainWindow
        # (~3,259 widgets) per test and left 14,760 widgets sitting in
        # test_qml_shell.py alone — inflating the very pile whose repolish cost
        # blows that file's own theme test through the 60 s timeout. So: try to
        # close, and destroy either way.
        try:
            widget.close()
        except Exception:
            pass
        try:
            widget.deleteLater()
        except (RuntimeError, ReferenceError):
            continue                # C++ side already gone — nothing to reap

    gc.collect()
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()

    # NOT REAPED, DELIBERATELY: pyqtgraph's parentless orphans. A panel's plots
    # each build helper widgets with no parent — ViewBoxMenu, ColorMapMenu and
    # its QWidgetAction's bare QWidget/QFrame, a QColorDialog. They are
    # top-level, they are not ours, and they are owned by Python references held
    # by pyqtgraph items inside the panel. They are also the whole residual pile:
    # one TCTMainWindow leaves ~984 of them behind per test, which is where
    # test_qml_shell.py's ~14,760 widgets come from.
    #
    # Three separate attempts to reclaim them ALL ended in a native crash or in
    # corrupting a live panel, and they are on the record so nobody pays for this
    # lesson twice:
    #   1. deleting them alongside the panel      -> Qt "Fatal Python error: Aborted"
    #      (a live pyqtgraph item still held them mid-DeferredDelete)
    #   2. deleting them after the panel died, gated on "the panels I made this
    #      test are gone"                          -> RuntimeError in
    #      tests/test_panel_glass_rollout.py, whose module fixtures keep panels
    #      alive ACROSS tests and still owned some
    #   3. gated on total quiescence (no app-owned widget alive anywhere)
    #                                              -> access violation anyway
    # Their ownership is not something the test tier can reason about safely.
    # They stay. Slow is always better than corrupt, and the durable fix is on
    # the product side (see the lambda note above): a panel that gc can actually
    # collect frees its own orphans, and none of this is needed.


# --------------------------------------------------------------------------- #
# Thread-leak reaper + guard (D4, 2026-07-13).                                 #
#                                                                              #
# Some panels deliberately parent a worker thread to the long-lived            #
# QApplication rather than to the panel — a planner cost-estimate worker       #
# (started in __init__), a settings-window VISA scan — precisely so a soft     #
# config-reload can delete the panel tree without destroying a still-running   #
# QThread as a child (itself a hard Qt6 abort). In the real app the main       #
# window's teardown quits those via each panel's shutdown(); a test that       #
# builds a panel and drops it never runs that path, so the app-parented thread #
# survives to interpreter exit, where ``~QApplication`` destroys it while it   #
# is still running → Qt6 fail-fast ("QThread: Destroyed while thread '' is     #
# still running", 0xC0000409) AFTER a green pytest summary. This was masked    #
# under xdist (a worker subprocess crashing at exit after reporting results is #
# invisible to the controller) and surfaced only in the SERIAL gate run.       #
#                                                                              #
# The crash is strictly a teardown-order fact: it needs a RUNNING QThread at   #
# the moment ``~QApplication`` runs. So we play the main window's teardown     #
# role ONCE, at session end (before the app is torn down), instead of          #
# retrofitting every panel-constructing test: a COOPERATIVE quit()+join        #
# (never terminate()) of every running non-main QThread — the same primitive   #
# shutdown() uses. Doing it here (not per test) also keeps the O(heap) thread  #
# scan off the ~1900-test hot path.                                            #
# --------------------------------------------------------------------------- #
def _running_nonmain_qthreads():
    """Every live QThread except the main (GUI) thread that reports isRunning().

    Enumerated via the Python heap (Qt exposes no thread registry). Wrappers
    whose C++ object is already gone raise and are skipped."""
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    main = app.thread() if app is not None else None
    out = []
    for obj in gc.get_objects():
        if not isinstance(obj, QThread) or obj is main:
            continue
        try:
            if obj.isRunning():
                out.append(obj)
        except (RuntimeError, ReferenceError):
            continue  # C++ side already deleted — a harmless dangling wrapper
    return out


def _reap_running_qthreads(app):
    """Cooperatively quit()+join every running non-main QThread, then drain the
    deferred deletions their ``finished`` handlers schedule. Bounded wait — a
    thread whose ``run()`` is a non-event-loop compute cannot be interrupted by
    quit(), so never block the suite unbounded; a thread that ignores the join is
    surfaced by :func:`pytest_sessionfinish`. NEVER ``terminate()``."""
    from PySide6.QtCore import QEvent

    reaped = False
    for thread in _running_nonmain_qthreads():
        try:
            thread.quit()
            thread.wait(3000)
            reaped = True
        except (RuntimeError, ReferenceError):
            continue
    if reaped:
        gc.collect()
        for _ in range(3):
            app.processEvents()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def _describe_qthread(obj):
    try:
        name = obj.objectName()
    except Exception:
        name = "?"
    chain = []
    try:
        p = obj.parent()
        depth = 0
        while p is not None and depth < 6:
            chain.append(type(p).__name__)
            p = p.parent()
            depth += 1
    except Exception:
        pass
    return f"class={type(obj).__name__} objectName={name!r} parent={'->'.join(chain) or '<none>'}"


def pytest_sessionfinish(session, exitstatus):
    """Bucket-A invariant guard: no non-main QThread may survive a graceful reap
    at session end. A survivor is a thread a test started and neither joined nor
    left reapable — it is destroyed only when ``~QApplication`` runs at interpreter
    exit, a hard Qt6 abort (0xC0000409) that a green pytest summary hides. Fail the
    session loudly instead. Opt out with TCT_ALLOW_LEAKED_THREADS=1 if it flakes."""
    if os.environ.get("TCT_ALLOW_LEAKED_THREADS") == "1":
        return
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    _reap_running_qthreads(app)          # last graceful attempt
    survivors = _running_nonmain_qthreads()
    if not survivors:
        return
    lines = "\n".join(f"    - {_describe_qthread(t)}" for t in survivors)
    print(
        "\n[THREAD-GUARD] FAIL: non-main QThread(s) survived a graceful reap at "
        "session end. Left running, these hard-abort Qt6 when ~QApplication runs "
        "at interpreter exit ('QThread: Destroyed while thread is still running')."
        f" Owner must join/shutdown its thread on teardown.\n{lines}",
        flush=True,
    )
    try:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    except Exception:
        session.exitstatus = 1
