"""Seeded UI MONKEY harness — safe-action random walks over the live cockpit.

This is the GUI-level sibling of ``tests/test_state_fuzz.py`` (which fuzzes the
run lifecycle at the controller tier).  Where the state fuzzer drives
``StateMachine``/``ScanController`` directly, this drives the REAL, fully-built
``TCTMainWindow`` against fully-*simulated* devices, headless/offscreen, with a
seeded stream of random *user-like* interactions, and asserts a small set of
invariants after EVERY action.

What it is for
--------------
Random interaction finds the bugs a scripted test never reaches: a slot that
crashes when a panel is not the current tab, a widget touched after teardown, a
handler that assumes a device is connected, a stray thread per click.  The
monkey does not know what any button "means" — that is the point.

SAFETY MODEL (three independent layers — a scan/HV/motion path must be
unreachable *by construction*, not merely unlikely)
-------------------------------------------------------------------------------
1. **Safe-action allowlist** — :func:`is_monkey_safe`, the ONE centralized
   predicate (see its docstring for the exact rules).  Nothing dangerous is ever
   clicked: no HV, no motion, no homing, no scan start, no arm latch, no
   connect/disconnect, no settings save/reload.

2. **Blocking-modal neutralization** — :func:`_neutralize_modals`.  Several
   *safe-state* buttons legitimately open a **blocking** ``QFileDialog`` /
   ``QDialog.exec()`` / ``QMenu.exec()`` (Browse, Export CSV, Load routine, ...).
   Left alone, the first such click would wedge the harness forever (the modal
   never returns without a human).  They are patched to a non-blocking
   "user pressed Cancel/No" result, so the click still exercises the handler up
   to the dialog boundary and then unwinds cleanly.  ``QtDangerGate._show_dialog``
   is patched too — it can only *deny*, and any invocation is recorded as a
   BREACH (see 3).

3. **Run-control tripwires** — the four ``ScanController`` entry points that can
   start motion/HV/acquisition (``start_plan``, ``start_z_focus_scan``,
   ``start_voltage_scan``, ``arm_hv``) are replaced, at class level, with
   recorders that refuse.  They must never fire.  If one does, the allowlist has
   a hole: the run is *prevented* and the seed FAILS loudly with the repro, so a
   gap in layer 1 surfaces as a red test instead of a real scan.

   Layer 3 is what makes "the monkey cannot start a scan" a *proof* rather than a
   promise.  It is deliberately at the controller boundary (the real danger
   seam), not at the widget, because widget-level markings are exactly the thing
   under test: e.g. the Z-focus "Find focus" button used to carry
   ``state="primary"`` (NOT ``"motion"``/``"danger"``) while starting a real
   motion+acquisition run, caught only by its *text* — the W1 taxonomy sweep
   has since given it the motion class too (rule 4 now ALSO denies it), but
   rule 5's text-level denial stays the one true backstop for the next button
   that slips through role-marking, and layer 3 is the final backstop if that
   ever slips.

Invariants checked after EVERY action
-------------------------------------
  (a) no Python exception escapes (direct call, ``sys.excepthook``,
      ``threading.excepthook``);
  (b) no Qt *fatal* message;
  (c) no danger breach (tripwire / danger dialog) — see the safety model above;
  (d) no modal dialog left blocking the app (``activeModalWidget() is None``);
  (e) ``AppState`` is UNCHANGED — the monkey has no legitimate path to move the
      state machine (it never connects and never starts a run), so any movement
      is a bug;
  (f) the window is still alive and responsive (events drain, the tab tree is
      intact).

Thread-leak invariant: checked on a cadence (every :data:`_THREAD_CHECK_EVERY`
actions) plus a hard, post-drain check at the end of the walk, rather than after
every single action — Qt's ``QThread`` objects are invisible to Python's
``threading`` module (measured: ``threading.active_count() == 1`` while 10
QThreads run), so the only reliable enumeration is a ``gc`` sweep at ~30 ms a
call; per-action it would dominate the runtime budget for no extra signal (a
per-click thread leak still accumulates well within the cadence).

Reproducibility
---------------
Seeds come from ``TCT_MONKEY_SEED`` (comma/space separated) or default to
:data:`_DEFAULT_SEEDS`; each seed is its own parametrized test (so one bad seed
does not mask the others, and each gets its own 60 s budget).  ANY failure
prints ``MONKEY REPRO: seed=... action=<n>`` plus the last
:data:`_LOG_TAIL` actions.  Re-run a single seed with::

    TCT_MONKEY_SEED=20260712 .venv/Scripts/python.exe -m pytest \
        tests/test_ui_monkey.py -q

Offscreen, fully simulated, never connected: safe to run with real hardware
attached (hardware-safety rules 1/2/3/6).  ``QSettings`` is repointed at a
throwaway per-process temp .ini by ``tests/conftest.py`` (before collection,
so before any window is built), and a monkey click can never write the
developer's real persisted settings.
"""
from __future__ import annotations

import gc
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

import yaml

# Must precede any Qt import (conftest also sets it; belt and braces).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import (
    QEvent, QObject, QtMsgType, QThread, QUrl,
    qInstallMessageHandler,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QCheckBox, QComboBox,
    QDialog, QDoubleSpinBox, QFileDialog, QMenu, QMessageBox, QPushButton,
    QRadioButton, QSlider, QSpinBox, QSplitter, QToolButton, QWidget,
)

# Isolation from the developer's REAL QSettings("TCT", "TCTSetup") store (the
# Windows registry by default) now lives in tests/conftest.py, which repoints
# QSettings at a per-process throwaway .ini before collection — so it holds for
# EVERY test and every subset run, not just the ones that happen to import this
# module. A monkey click still cannot mutate the real theme / geometry /
# detached-tab state; nothing else did.

REPO_CONFIG = "configs/devices.yaml"      # cwd is TCT_app/ (see tests/conftest.py)

_DEFAULT_SEEDS = (20_260_712, 8_675_309, 424_242)
_ACTIONS_PER_SEED = 200
_LOG_TAIL = 20                 # actions printed on failure
_THREAD_CHECK_EVERY = 25       # gc sweep cadence (see module docstring)
_THREAD_SLACK = 2              # tolerate a transient worker mid-walk
_SPIN_ABS_CAP = 1000.0         # bound random spin values (see _act_spin)


def _seeds() -> tuple[int, ...]:
    raw = os.environ.get("TCT_MONKEY_SEED", "").strip()
    if not raw:
        return _DEFAULT_SEEDS
    return tuple(int(tok) for tok in re.split(r"[,\s]+", raw) if tok)


# --------------------------------------------------------------------------- #
# THE safe-action predicate (single source of truth)                           #
# --------------------------------------------------------------------------- #
# Marked-danger roles, as the panels actually set them (grep-verified against
# gui/*.py): objectName "dangerBtn" (motor/calibration/planner/panel_kit/
# arm_latch/bias polarity switch), "killSwitchBtn" (bias Output OFF /
# multi_bias ALL OUTPUTS OFF -- the kill-switch escalation ruling gave these
# their own identity, distinct from the ALWAYS-red dangerBtn language, but
# still caught by the same "danger"/"arm"/"kill" object-substring net below),
# "armedBtn" (laser), "connectBtn"/"disconnectBtn" (toolbar), and the dynamic
# QSS property state in {danger, motion, armed}.
_DENY_OBJECT_SUBSTRINGS = (
    "danger", "arm", "exec", "connect", "motion", "jog", "kill", "home", "menu",
)
_DENY_STATES = frozenset({"danger", "motion", "armed"})

# Text-level denial. REQUIRED, not belt-and-braces: role markings alone are NOT
# sufficient, and this is the layer that proves it. Counter-examples found in
# the live tree while writing this harness:
#   * scan_viewer "Find focus"      state="primary" when found (now "motion",
#                                    W1 taxonomy sweep) -> starts a REAL
#                                    z-focus run (motion+acquisition)
#   * settings/scope "Apply & Save" no state         -> WRITES devices.yaml
#   * scope "List VISA..."          no state         -> enumerates VISA resources
#   * scope "Drive scope (->SCPI)"  QCheckBox        -> drives the instrument
# Matched on whole words (never substrings: "on"/"off"/"go" would otherwise hit
# "config"/"gone"), plus a leading-word check.
_DENY_WORDS = frozenset({
    # motion / homing / HV / laser / acquisition / run-control
    "connect", "disconnect", "reconnect", "home", "homing", "move", "jog",
    "zero", "arm", "armed", "disarm", "execute", "start", "stop", "run",
    "abort", "pause", "resume", "ramp", "enable", "disable", "kill", "scan",
    "focus", "trigger", "output", "live", "stream", "acquire", "park",
    "on", "off", "go",
    # persistence / config / system-reaching / device-command surfaces
    "save", "apply", "reload", "restart", "quit", "exit", "reset",
    "visa", "scpi", "drive", "metadata", "calibrate", "repeatability",
    "measure", "menu",
})

_WORD_RE = re.compile(r"[a-z]+")


def is_monkey_safe(w: QWidget) -> bool:
    """Return True only for widgets the monkey is allowed to actuate.

    The ONE predicate every action type funnels through (buttons, checkboxes,
    radio buttons — everything that can fire a handler).  Deliberately
    *conservative*: it is far better to skip a harmless control than to actuate
    a dangerous one, so anything ambiguous is denied.  A widget is safe only if
    ALL of the following hold:

    1. it is visible and enabled (the monkey acts only on what a user could
       actually click right now);
    2. it is not inside an :class:`~gui.arm_latch.ArmLatch` (nor an
       ``ArmButton``) — the two-step HV/motion arm latch is NEVER touched, by
       structural ancestry, independent of any labelling;
    3. its ``objectName`` contains no danger marker
       (:data:`_DENY_OBJECT_SUBSTRINGS` — ``dangerBtn``, ``armedBtn``,
       ``connectBtn``, ...);
    4. its dynamic QSS ``state`` property is not a danger role
       (:data:`_DENY_STATES` — ``danger`` / ``motion`` / ``armed``);
    5. no word of its label is a danger/persistence verb (:data:`_DENY_WORDS`).
       Rules 3-4 are NOT sufficient on their own — see the counter-examples
       above ``_DENY_WORDS``; this rule is what stops the monkey from pressing
       "Find focus" (a ``state="primary"`` button that starts a real scan).

    Note this predicate does not, and must not, stand alone: the run-control
    tripwires (module docstring, layer 3) turn any gap here into a loud test
    failure rather than a real scan.
    """
    try:
        if not (w.isVisible() and w.isEnabled()):
            return False
    except RuntimeError:      # underlying C++ object already deleted
        return False

    if _inside_arm_latch(w):
        return False

    name = (w.objectName() or "").lower()
    if any(tok in name for tok in _DENY_OBJECT_SUBSTRINGS):
        return False

    state = w.property("state")
    if isinstance(state, str) and state.lower() in _DENY_STATES:
        return False

    text = ""
    if isinstance(w, QAbstractButton):
        text = w.text() or ""
    text = text.replace("&", "").lower()
    words = set(_WORD_RE.findall(text))
    if words & _DENY_WORDS:
        return False
    return True


def _inside_arm_latch(w: QWidget) -> bool:
    """True if *w* is, or descends from, the ArmLatch danger composite."""
    from gui.arm_latch import ArmButton, ArmLatch

    node: QObject | None = w
    while node is not None:
        if isinstance(node, (ArmLatch, ArmButton)):
            return True
        node = node.parent()
    return False


# --------------------------------------------------------------------------- #
# Qt helpers                                                                    #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(seconds: float = 0.05) -> None:
    app = _app()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.002)


def _drain(app: QApplication, rounds: int = 3) -> None:
    """Cheap per-action event drain (no wall-clock sleep)."""
    for _ in range(rounds):
        app.processEvents()


def _ascii(text: str) -> str:
    """ASCII-safe for the Windows cp1252 console: several real button labels
    carry non-cp1252 glyphs (``Browse…``, a ``↓`` arrow), and a repro print that
    itself dies with UnicodeEncodeError would hide the finding."""
    return str(text).encode("ascii", "replace").decode("ascii")


def _running_qthreads() -> list[QThread]:
    """Every live, running ``QThread`` in the process.

    A ``gc`` sweep is the only reliable enumeration: Qt threads never enter
    Python's ``threading`` registry (``threading.active_count()`` reads 1 while
    ten QThreads run), and the app parents its threads inconsistently (some to
    the window, some to panels, some to ``QApplication.instance()``), so no
    single ``findChildren`` root sees them all.
    """
    out: list[QThread] = []
    for obj in gc.get_objects():
        if not isinstance(obj, QThread):
            continue
        try:
            if obj.isRunning():
                out.append(obj)
        except RuntimeError:   # C++ side already deleted
            continue
    return out


# --------------------------------------------------------------------------- #
# Harness context: exception/Qt-message capture, modal neutralization,          #
# run-control tripwires                                                         #
# --------------------------------------------------------------------------- #
class MonkeyContext:
    """Collects everything the invariants are asserted against."""

    def __init__(self) -> None:
        self.excs: list[str] = []        # (a) escaped Python exceptions
        self.qt_fatal: list[str] = []    # (b) Qt fatal messages
        self.qt_critical: list[str] = []  # reported, not failed (see check())
        self.breaches: list[str] = []    # (c) danger paths reached — MUST be []
        self.modals: list[str] = []      # neutralized dialogs (informational)
        self.actions: list[str] = []
        self.quarantine: list = []       # KNOWN-BROKEN widgets (see _quarantine_for)
        self.baseline_state = None
        self.baseline_threads = 0
        self.max_threads = 0

    def record_exc(self, where: str, exc: BaseException) -> None:
        self.excs.append(
            f"[{where}] " + "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)))


def _neutralize_modals(monkeypatch, ctx: MonkeyContext) -> None:
    """Make every blocking modal return a safe "user cancelled" answer.

    Without this the harness deadlocks on the first ``Browse…`` / ``Export CSV``
    / ``Load routine…`` click: those are legitimately *safe* buttons (no motion,
    no HV) but they call ``QFileDialog.getOpenFileName`` & friends, which block
    until a human answers.  Patched to "cancelled", the click still runs the
    whole handler up to the dialog boundary and then unwinds — which is exactly
    the code path worth fuzzing — and can never touch the filesystem.

    ``QMessageBox`` answers are forced to the *safe* branch (No/Cancel), so a
    confirmation the monkey somehow reaches is always declined.
    """
    # -- file dialogs: always "cancelled" -----------------------------------
    def _no_file(*a, **k):
        ctx.modals.append("QFileDialog")
        return ("", "")

    def _no_files(*a, **k):
        ctx.modals.append("QFileDialog(multi)")
        return ([], "")

    def _no_dir(*a, **k):
        ctx.modals.append("QFileDialog(dir)")
        return ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(_no_file))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_no_file))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(_no_files))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(_no_dir))

    # -- message boxes: always the SAFE (declining) answer -------------------
    def _mb(answer):
        def _inner(*a, **k):
            ctx.modals.append("QMessageBox")
            return answer
        return staticmethod(_inner)

    monkeypatch.setattr(QMessageBox, "question", _mb(QMessageBox.StandardButton.No))
    monkeypatch.setattr(QMessageBox, "warning", _mb(QMessageBox.StandardButton.No))
    monkeypatch.setattr(QMessageBox, "critical", _mb(QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "information", _mb(QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "about", _mb(None))

    # -- any other modal (custom QDialog, popup QMenu): reject, never block ---
    def _no_exec(self, *a, **k):
        ctx.modals.append(type(self).__name__)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", _no_exec)
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: None)

    # -- the danger gate can only DENY, and any use is a breach --------------
    from gui.qt_danger_gate import QtDangerGate

    def _gate_denied(self, action):
        ctx.breaches.append(f"QtDangerGate._show_dialog({getattr(action, 'kind', '?')})")
        return False

    monkeypatch.setattr(QtDangerGate, "_show_dialog", _gate_denied)


def _install_tripwires(monkeypatch, ctx: MonkeyContext) -> None:
    """Replace every ScanController entry point that can move the stage, drive
    HV, or start acquisition with a recorder that REFUSES.

    Patched at class level (not on the instance): the coordinator resolves
    ``self._scanner.start_*`` at call time, so a class patch is what actually
    intercepts a signal-driven start — an instance attribute would be bypassed
    by the already-bound Qt connection.

    A tripwire firing means the safe-action allowlist has a hole.  The run is
    prevented either way; the recorded breach turns that hole into a red test
    with a reproducible action log.
    """
    from controller.scan_controller import ScanController

    def _trip(name):
        def _inner(self, *a, **k):
            ctx.breaches.append(f"ScanController.{name}")
            raise AssertionError(
                f"MONKEY TRIPWIRE: {name} reached from a supposedly-safe action")
        return _inner

    for meth in ("start_plan", "start_z_focus_scan", "start_voltage_scan", "arm_hv"):
        monkeypatch.setattr(ScanController, meth, _trip(meth))


# --------------------------------------------------------------------------- #
# Window build / teardown (the suite's established headless pattern —           #
# tests/test_qml_shell.py::_make_window/_destroy)                               #
# --------------------------------------------------------------------------- #
def _sandbox_config(tmp_path) -> str:
    """A throwaway copy of the real ``configs/devices.yaml`` for this walk.

    NOT a nicety — a hard safety requirement of this harness.  Several
    *innocuous-looking* scope controls persist straight to the config file they
    were built with (``gui/scope_panel.py::_on_avg_changed`` ->
    ``_save_scope_keys_to_yaml(self._config_path, ...)``; the trigger/timebase
    editors do the same).  Pointed at the repo file, a random combo change would
    rewrite the developer's tracked ``devices.yaml`` — a mutation the brief
    forbids outright ("Explicitly NEVER: Settings save/reload").  Handing the
    window a temp copy makes every such write land in ``tmp_path`` instead, so
    the repo config is untouchable *by construction* rather than by luck.

    ``output.data_dir`` is redirected into ``tmp_path`` too, so nothing can
    scribble into ``TCT_app/runs/`` either.
    """
    cfg = yaml.safe_load(Path(REPO_CONFIG).read_text(encoding="utf-8"))
    cfg.setdefault("output", {})["data_dir"] = str(tmp_path / "runs")
    dst = tmp_path / "devices.yaml"
    dst.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(dst)


def _build_window(monkeypatch, config_path: str):
    # Classic shell explicitly: deterministic today, and the monkey is
    # shell-agnostic anyway (it walks whatever widget tree exists).
    monkeypatch.delenv("TCT_QML_SHELL", raising=False)

    from tct_gui import TCTMainWindow

    # No persisted geometry / detached tabs in a headless build.
    monkeypatch.setattr(TCTMainWindow, "_restore_window_state", lambda self: None)
    win = TCTMainWindow(config_path=config_path)
    win.resize(1400, 900)
    win.show()          # offscreen; makes isVisible() meaningful for the filter
    _pump(0.25)
    return win


def _destroy_window(win) -> None:
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
# The action alphabet                                                           #
# --------------------------------------------------------------------------- #
def _quarantine_for(win) -> list:
    """Widgets held out of the random pool because they are KNOWN-BROKEN today.

    This is a *bug ledger*, not a safety mechanism (safety is the allowlist +
    tripwires) — every entry is a real defect this harness found on its first
    run, owned by another seat, each pinned below by a ``xfail(strict=True)``
    regression probe.  When the owner lands the fix, the probe XPASSes; strict
    xfail turns that into a red test, which forces whoever fixed it to delete
    the matching entry here.  So the quarantine cannot silently outlive the bug.

    FINDING 1 — ``gui/scope_panel.py::_on_avg_changed`` (owner: Noah/Paul):
        ``self._scope.n_averages = n`` assigns a READ-ONLY property ->
        ``AttributeError`` on every change of the scope "Averages" combo.  A
        user-reachable, unhandled GUI crash.  Pinned by
        ``test_xfail_scope_averages_combo_raises_attributeerror``.
    """
    out = []
    combo = getattr(getattr(win, "_scope_panel", None), "_avg_combo", None)
    if combo is not None:
        out.append(combo)
    return out


def _usable(w: QWidget, ctx: MonkeyContext) -> bool:
    """Safe (:func:`is_monkey_safe`) AND not a quarantined known-broken widget."""
    if any(w is q for q in ctx.quarantine):
        return False
    return is_monkey_safe(w)


def _page(win) -> QWidget:
    """The widget subtree the monkey is currently looking at."""
    return win._tabs.currentWidget() or win


def _pick(rng, items):
    return rng.choice(items) if items else None


def _safe_children(root: QWidget, cls, ctx: MonkeyContext) -> list:
    return [w for w in root.findChildren(cls) if _usable(w, ctx)]


def _act_tab(win, rng, ctx) -> str:
    tabs = win._tabs
    n = tabs.count()
    if n <= 1:
        return "tab:noop"
    idx = rng.randrange(n)
    tabs.setCurrentIndex(idx)
    return f"tab:{_ascii(tabs.tabText(idx))}"


def _act_click(win, rng, ctx) -> str:
    pool = [w for w in _page(win).findChildren(QAbstractButton)
            if isinstance(w, (QPushButton, QToolButton)) and _usable(w, ctx)]
    btn = _pick(rng, pool)
    if btn is None:
        return "click:none"
    label = _ascii(btn.text() or btn.objectName() or type(btn).__name__)
    btn.click()
    return f"click:{label}"


def _act_check(win, rng, ctx) -> str:
    pool = [w for w in _page(win).findChildren(QAbstractButton)
            if isinstance(w, (QCheckBox, QRadioButton)) and _usable(w, ctx)]
    box = _pick(rng, pool)
    if box is None:
        return "check:none"
    label = _ascii(box.text() or box.objectName() or type(box).__name__)
    box.click()          # through the real toggled/clicked signal path
    return f"check:{label}={box.isChecked()}"


def _act_spin(win, rng, ctx) -> str:
    """Step or set a spin box strictly within its own range.

    Random values are additionally clamped to +/-:data:`_SPIN_ABS_CAP`, and
    stepping is favoured over jumping: this harness fuzzes *interaction*, not
    extreme-value stress, and an unbounded jump on a "number of points"-style
    spin would build an enormous plan and blow the per-test time budget for no
    new signal (extreme-value validation is the planner validator's own tests).
    """
    pool = _safe_children(_page(win), QAbstractSpinBox, ctx)
    spin = _pick(rng, pool)
    if spin is None:
        return "spin:none"
    name = _ascii(spin.objectName() or type(spin).__name__)
    if rng.random() < 0.6 or not isinstance(spin, (QSpinBox, QDoubleSpinBox)):
        if rng.random() < 0.5:
            spin.stepUp()
            return f"spin:{name}.stepUp"
        spin.stepDown()
        return f"spin:{name}.stepDown"

    lo, hi = spin.minimum(), spin.maximum()
    lo = max(lo, -_SPIN_ABS_CAP)
    hi = min(hi, _SPIN_ABS_CAP)
    if lo > hi:
        spin.stepUp()
        return f"spin:{name}.stepUp"
    val = rng.randint(int(lo), int(hi)) if isinstance(spin, QSpinBox) \
        else rng.uniform(lo, hi)
    spin.setValue(val)
    return f"spin:{name}={val:.4g}"


def _act_combo(win, rng, ctx) -> str:
    pool = [w for w in _safe_children(_page(win), QComboBox, ctx) if w.count() > 0]
    combo = _pick(rng, pool)
    if combo is None:
        return "combo:none"
    idx = rng.randrange(combo.count())
    combo.setCurrentIndex(idx)
    return f"combo:{_ascii(combo.objectName() or 'combo')}[{idx}]"


def _act_slider(win, rng, ctx) -> str:
    pool = _safe_children(_page(win), QSlider, ctx)
    sld = _pick(rng, pool)
    if sld is None:
        return "slider:none"
    val = rng.randint(sld.minimum(), sld.maximum())
    sld.setValue(val)
    return f"slider:{_ascii(sld.objectName() or 'slider')}={val}"


def _act_splitter(win, rng, ctx) -> str:
    pool = [s for s in _page(win).findChildren(QSplitter) if s.count() > 1]
    sp = _pick(rng, pool)
    if sp is None:
        return "splitter:none"
    sizes = sp.sizes()
    total = sum(sizes) or 100
    cuts = sorted(rng.randint(0, total) for _ in range(len(sizes) - 1))
    new, prev = [], 0
    for c in cuts:
        new.append(c - prev)
        prev = c
    new.append(total - prev)
    sp.setSizes(new)
    return f"splitter:{len(new)}"


def _act_hover(win, rng, ctx) -> str:
    """Synthetic hover — exercises the QSS hover hot path (the one guarded by
    tests/test_style_hover_hotpath_guard.py) on live, themed widgets.

    ``QTest.mouseMove`` only, deliberately: Qt6 dispatches ``QEvent::Enter`` by
    ``static_cast``-ing to ``QEnterEvent*``, so hand-posting a bare
    ``QEvent(Enter)`` is undefined behaviour (a crash the *harness* would own,
    not the app).  A real mouse move is the honest input, and Qt synthesizes the
    hover events from it for every ``WA_Hover`` widget.
    """
    pool = [w for w in _page(win).findChildren(QWidget)
            if w.isVisible() and w.width() > 2 and w.height() > 2]
    w = _pick(rng, pool)
    if w is None:
        return "hover:none"
    QTest.mouseMove(w, w.rect().center())
    return f"hover:{_ascii(type(w).__name__)}"


# Weighted alphabet: tab switches and clicks dominate (they change what is on
# screen and fire the most handler code); the value-editing actions carry the
# rest of the state-space coverage.
_ACTIONS = (
    (_act_tab,      4),
    (_act_click,    5),
    (_act_check,    3),
    (_act_spin,     4),
    (_act_combo,    3),
    (_act_slider,   1),
    (_act_splitter, 1),
    (_act_hover,    3),
)
_ACTION_FNS = [fn for fn, w in _ACTIONS for _ in range(w)]


# --------------------------------------------------------------------------- #
# Invariants                                                                    #
# --------------------------------------------------------------------------- #
def _check_invariants(win, ctx: MonkeyContext, i: int) -> None:
    # (c) danger reached — the loudest failure there is.
    assert not ctx.breaches, "DANGER PATH REACHED: " + "; ".join(ctx.breaches)
    # (a) no escaped exception.
    assert not ctx.excs, "unhandled exception:\n" + "\n".join(ctx.excs)
    # (b) no Qt fatal.
    assert not ctx.qt_fatal, "Qt fatal:\n" + "\n".join(ctx.qt_fatal)
    # (d) nothing modal is blocking the app.
    modal = QApplication.activeModalWidget()
    assert modal is None, f"a modal dialog is blocking: {type(modal).__name__}"
    # (e) AppState frozen — the monkey has no legitimate path to move it.
    assert win._sm.state is ctx.baseline_state, (
        f"AppState moved without a scan/connect: "
        f"{ctx.baseline_state} -> {win._sm.state}")
    # (f) the window survived and its tree is intact.
    assert win._tabs.count() > 0, "tab tree collapsed"

    # Thread-leak check on a cadence (see the module docstring for why not
    # every action).
    if i % _THREAD_CHECK_EVERY == 0:
        n = len(_running_qthreads())
        ctx.max_threads = max(ctx.max_threads, n)
        assert n <= ctx.baseline_threads + _THREAD_SLACK, (
            f"QThread leak: {n} running vs {ctx.baseline_threads} at baseline")


def _report(seed: int, ctx: MonkeyContext, i: int) -> str:
    tail = ctx.actions[-_LOG_TAIL:]
    lines = [
        "",
        f"MONKEY REPRO: seed={seed} failed_at_action={i} "
        f"(TCT_MONKEY_SEED={seed} to replay)",
        f"MONKEY REPRO: last {len(tail)} actions:",
    ]
    lines += [f"  {i - len(tail) + n + 1:>4}. {a}" for n, a in enumerate(tail)]
    if ctx.qt_critical:
        lines.append(f"MONKEY: Qt critical messages: {ctx.qt_critical[:5]}")
    if ctx.modals:
        lines.append(f"MONKEY: neutralized modals: {ctx.modals[-5:]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The walk                                                                      #
# --------------------------------------------------------------------------- #
def _run_monkey(monkeypatch, tmp_path, seed: int,
                n_actions: int = _ACTIONS_PER_SEED) -> MonkeyContext:
    import random

    app = _app()
    ctx = MonkeyContext()
    rng = random.Random(seed)

    _neutralize_modals(monkeypatch, ctx)
    _install_tripwires(monkeypatch, ctx)

    # (a) catch what Qt's queued dispatch would otherwise swallow / print.
    orig_hook, orig_thook = sys.excepthook, threading.excepthook
    sys.excepthook = lambda et, ev, tb: ctx.record_exc("main", ev)
    threading.excepthook = lambda args: ctx.record_exc("thread", args.exc_value)

    # (b) Qt-level messages.
    def _qt_msg(mode, _ctx, msg):
        if mode == QtMsgType.QtFatalMsg:
            ctx.qt_fatal.append(str(msg))
        elif mode == QtMsgType.QtCriticalMsg:
            ctx.qt_critical.append(str(msg))

    orig_msg = qInstallMessageHandler(_qt_msg)

    win = None
    i = 0
    try:
        win = _build_window(monkeypatch, _sandbox_config(tmp_path))
        ctx.quarantine = _quarantine_for(win)
        ctx.baseline_state = win._sm.state
        ctx.baseline_threads = len(_running_qthreads())
        ctx.max_threads = ctx.baseline_threads
        # A fresh, never-connected window must be DISCONNECTED (rule 1: no
        # hardware is touched at construction) — the premise of invariant (e).
        from controller.state_machine import AppState
        assert ctx.baseline_state is AppState.DISCONNECTED, ctx.baseline_state

        for i in range(1, n_actions + 1):
            action = rng.choice(_ACTION_FNS)
            try:
                name = action(win, rng, ctx)
            except BaseException as exc:          # noqa: BLE001 — record & fail
                ctx.actions.append(f"{action.__name__}:RAISED")
                ctx.record_exc(action.__name__, exc)
                name = "RAISED"
            else:
                ctx.actions.append(name)
            _drain(app)
            _check_invariants(win, ctx, i)

        # Hard, post-drain thread check: every transient worker a click may have
        # spawned must be gone — a real leak accumulates here.
        _pump(0.2)
        gc.collect()
        _pump(0.05)
        final = len(_running_qthreads())
        ctx.max_threads = max(ctx.max_threads, final)
        assert final <= ctx.baseline_threads, (
            f"QThread leak after {n_actions} actions: "
            f"{final} running vs {ctx.baseline_threads} at baseline")
    except BaseException:
        print(_report(seed, ctx, i))
        raise
    finally:
        sys.excepthook, threading.excepthook = orig_hook, orig_thook
        qInstallMessageHandler(orig_msg)
        if win is not None:
            _destroy_window(win)
        app.processEvents()
    return ctx


# --------------------------------------------------------------------------- #
# Tests — one per seed (independent 60 s budgets; a bad seed can't mask others) #
# --------------------------------------------------------------------------- #
@pytest.mark.monkey
@pytest.mark.timeout(120)
@pytest.mark.parametrize("seed", _seeds())
def test_ui_monkey_safe_random_walk(monkeypatch, tmp_path, seed):
    """~200 safe, seeded, user-like interactions against the simulated cockpit.

    Asserts, after EVERY action: no exception, no Qt fatal, no danger path
    reached, no blocking modal, AppState unchanged, window alive — plus no
    QThread leak (cadenced + a hard post-drain check).  See the module docstring.

    The explicit 120 s timeout is headroom, not need: the slowest seed measures
    ~24 s (window build ~6 s + 200 actions).  It matters because ``pytest.ini``
    sets ``timeout_method = thread``, whose watchdog aborts the WHOLE run
    (``os._exit``) rather than just failing one test — so a walk that merely got
    unlucky with CPU contention must never be the thing that kills the suite.
    """
    ctx = _run_monkey(monkeypatch, tmp_path, seed)

    # The walk must actually have DONE something — a filter bug that silently
    # denied every widget would otherwise "pass" while testing nothing.
    assert len(ctx.actions) == _ACTIONS_PER_SEED
    real = [a for a in ctx.actions if not a.endswith(":none") and a != "tab:noop"]
    assert len(real) >= _ACTIONS_PER_SEED // 2, (
        f"monkey mostly idled ({len(real)}/{_ACTIONS_PER_SEED} effective) — "
        "the safe-widget filter is probably over-denying")
    assert not ctx.breaches


@pytest.mark.monkey
def test_monkey_safe_filter_denies_every_danger_control(monkeypatch, tmp_path):
    """The allowlist predicate itself, pinned against the REAL widget tree.

    Guards the safety layer that the random walk depends on: every control that
    can move the stage, drive HV, start a run, connect a device, or write the
    config must be denied by :func:`is_monkey_safe` — including ones whose
    *role markings* alone would look benign (the Z-focus "Find focus" button
    used to ship as ``state="primary"`` and is caught below by its text
    regardless of what state it carries).  A future panel that adds a danger
    button without a danger role will fail here rather than in a 1-in-200
    random click.
    """
    _neutralize_modals(monkeypatch, MonkeyContext())
    _install_tripwires(monkeypatch, MonkeyContext())
    win = _build_window(monkeypatch, _sandbox_config(tmp_path))
    try:
        # Walk every tab so each panel's controls are realized and visible.
        offenders: list[str] = []
        for idx in range(win._tabs.count()):
            win._tabs.setCurrentIndex(idx)
            _pump(0.05)
            for w in _page(win).findChildren(QAbstractButton):
                text = (w.text() or "").replace("&", "").lower()
                words = set(_WORD_RE.findall(text))
                name = (w.objectName() or "").lower()
                state = w.property("state")
                dangerous = (
                    bool(words & _DENY_WORDS)
                    or any(t in name for t in _DENY_OBJECT_SUBSTRINGS)
                    or (isinstance(state, str) and state.lower() in _DENY_STATES)
                    or _inside_arm_latch(w)
                )
                if dangerous and is_monkey_safe(w):
                    offenders.append(
                        f"{_ascii(w.text())!r} obj={name!r} state={state!r}")
        assert not offenders, "safe-filter let a danger control through: " + \
            "; ".join(offenders)

        # The specific, load-bearing case that motivated the text rule. W1
        # taxonomy sweep (state_color_census.md) gave "Find focus" the motion
        # command class (rule 4 now ALSO denies it), but the word-level rule
        # 5 stays the one true backstop per this test's own docstring -- it
        # must deny even a button whose role marking looks benign, so this
        # still asserts via the *text* path, not the state it happens to
        # carry today.
        zf = win._scan_viewer._btn_zf_start
        assert zf.property("state") == "motion"        # now ALSO caught by rule 4
        assert not is_monkey_safe(zf), (
            "the Z-focus 'Find focus' button starts a real motion+acquisition "
            "run and must never be monkey-clickable")
    finally:
        _destroy_window(win)
        _app().processEvents()


# --------------------------------------------------------------------------- #
# WHAT THE MONKEY FOUND (2026-07-12, first run) — strict-xfail regression pins  #
#                                                                              #
# Both are REAL, user-reachable defects in another seat's files, so they are    #
# reported, not fixed, here (this beat is new-files-only; gui/ is Noah's).      #
# They are pinned as ``xfail(strict=True)`` probes asserting the DESIRED        #
# behaviour: today they XFAIL; the moment the owner lands a fix they XPASS,     #
# and strict xfail turns an XPASS into a FAILURE — which forces whoever fixed   #
# it to delete both the marker and the matching ``_quarantine_for`` entry.      #
# The bug can therefore never be silently "fixed" while the guard rots.         #
# --------------------------------------------------------------------------- #
class _slot_exceptions:
    """Capture exceptions raised inside Qt slots.

    PySide6 does NOT propagate an exception raised in a Python slot back to the
    C++ emitter (``setCurrentIndex`` / a fired ``QTimer`` return normally); it
    routes the traceback to ``sys.excepthook``.  A plain ``pytest.raises`` would
    therefore see nothing at all — which is precisely why these two crashes were
    invisible to the existing suite and only a live random walk surfaced them.
    """

    def __enter__(self) -> list[BaseException]:
        self.caught: list[BaseException] = []
        self._orig = sys.excepthook
        sys.excepthook = lambda et, ev, tb: self.caught.append(ev)
        return self.caught

    def __exit__(self, *exc) -> None:
        sys.excepthook = self._orig


@pytest.mark.monkey
@pytest.mark.xfail(
    strict=True,
    reason="FINDING 1 (UI monkey, 2026-07-12): gui/scope_panel.py::_on_avg_changed "
           "assigns the READ-ONLY property `n_averages` -> AttributeError on every "
           "change of the scope Averages combo. Owner: Noah (panel) / Paul (driver "
           "contract). When fixed: delete this marker AND the _quarantine_for entry.")
def test_xfail_scope_averages_combo_raises_attributeerror(monkeypatch, tmp_path):
    """Changing the scope "Averages" combo must not crash.

    ``_on_avg_changed`` does ``self._scope.n_averages = n``, but ``n_averages``
    is a read-only property on the oscilloscope -> ``AttributeError``.  Note the
    handler would *also* rewrite ``devices.yaml`` two lines later
    (``_save_scope_keys_to_yaml``); today the crash pre-empts that write, so the
    fix must not accidentally start persisting a value it failed to apply.
    """
    _neutralize_modals(monkeypatch, MonkeyContext())
    _install_tripwires(monkeypatch, MonkeyContext())
    win = _build_window(monkeypatch, _sandbox_config(tmp_path))
    try:
        combo = win._scope_panel._avg_combo
        assert combo.count() > 1, "need >1 averaging option to change to"
        with _slot_exceptions() as caught:
            combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
            _pump(0.05)
        assert not caught, (
            "changing the scope Averages combo raised: "
            + "; ".join(f"{type(e).__name__}: {e}" for e in caught))
    finally:
        _destroy_window(win)
        _app().processEvents()


@pytest.mark.monkey
def test_flash_button_survives_widget_destruction():
    """A flashed button destroyed before its restore-timer fires must not crash.

    Real-world path: click any command button that flashes success, then close
    the window / soft-reload the config / rebuild the panel within 900 ms — the
    pending ``_restore`` closure outlives the widget.  This is the same
    timer/worker-outlives-its-widget class as the D1 teardown batch.

    Was FINDING 2 (UI monkey, 2026-07-12), fixed 2026-07-13: ``flash_button``
    now arms the restore timer with the button as the singleShot *context
    object*, so Qt drops the pending invocation when the widget dies.  The
    same leak was what made the parallel (``-n auto``) suite untrustworthy —
    a restore timer armed near the end of one test fired inside the NEXT
    test's event pumping (see ``test_flash_timer_does_not_leak_into_next_test``).
    """
    from gui.status_widgets import flash_button
    from PySide6.QtCore import QCoreApplication

    _app()
    btn = QPushButton("flash me")
    btn.show()
    flash_button(btn, "good", text="OK", timeout_ms=10)

    with _slot_exceptions() as caught:
        btn.deleteLater()
        # Force the deferred delete through so the C++ object is really gone
        # before the restore timer fires. Safe here: an isolated, lightweight
        # standalone widget (the narrow case tests/test_qml_shell.py sanctions),
        # not a live TCTMainWindow.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _pump(0.12)          # > timeout_ms: let the singleShot fire
    assert not caught, (
        "flash_button's restore timer fired on a destroyed widget: "
        + "; ".join(f"{type(e).__name__}: {e}" for e in caught))


@pytest.mark.monkey
def test_flash_timer_does_not_leak_into_next_test():
    """Cross-test isolation: a flash armed on a widget that dies must leave NO
    pending invocation behind for a later test to trip over.

    This is the parallel-suite (xdist) failure mode in miniature: under
    ``-n auto`` the workers slice the suite differently, so a restore timer
    armed in the last moments of one test lands in the middle of another —
    which is why tests that pass in isolation failed in parallel.  A long
    ``timeout_ms`` here stands in for "the test ended before the flash did".
    """
    from gui.status_widgets import flash_button
    from PySide6.QtCore import QCoreApplication

    app = _app()
    btn = QPushButton("flash me")
    btn.show()
    flash_button(btn, "good", text="OK", timeout_ms=900)   # outlives this scope
    btn.deleteLater()
    del btn

    # Emulate the next test starting: conftest's drain finishes the destruction,
    # then the "later test" pumps the event loop past the flash deadline.
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    with _slot_exceptions() as caught:
        _pump(1.1)           # > 900 ms: an unowned timer would fire here
    assert not caught, (
        "a flash timer leaked past its widget into the next test: "
        + "; ".join(f"{type(e).__name__}: {e}" for e in caught))
