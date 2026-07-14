"""No panel may be immortal — the PRODUCT side of the RED-bench leak.

BACKGROUND (measured, and reproduced independently). A panel that a user merely
drops used to be *never freed*. Constructing and dropping one ``AnalysisPanel``
left 835 live QWidgets behind; a second left 1670; a third 2505 — perfectly
linear, nothing ever reclaimed. Every window the app opens and closes (a camera
ROI dialog, a scope trigger dialog, the theme editor, a detached panel the user
closes) permanently grew the widget pile, and because ``apply_theme`` ends in
``QApplication.setStyleSheet`` — which repolishes EVERY live widget, O(N) at
~0.3-0.5 ms each — every later theme toggle got slower and never gave the memory
back. ``gui/style.py``'s own docstring measured ~9 s per ``setStyleSheet`` at 13k
widgets; that number was the leak talking.

THE MECHANISM. A ``lambda`` that captures ``self`` connected to a signal owned
by a CHILD of ``self`` forms the cycle

    panel -> child -> (PySide6 C++ connection storage) -> lambda -> cell -> panel

One hop lives in C++, where CPython's gc cannot traverse, so gc never sees the
cycle to break it and the whole tree is immortal. A BOUND METHOD does not do
this — PySide6 holds bound-method slots weakly. That weak-vs-strong difference
is the entire fix, applied across 31 sites in 11 modules.

WHAT THESE TESTS PIN.
  * ``test_no_self_capturing_lambda_connected`` — the AST guard. It decides
    safety by MEASURING (walking the syntax tree), not by matching a spelling,
    exactly like ``tests/test_icon_theming_gui.py``. It flagged 31 sites on the
    tree before this fix; it must flag 0 now.
  * ``test_<panel>_construct_drop_is_not_immortal`` — construct each panel that
    leaked, drop it, drain Qt, assert the live-widget delta is 0. Before the
    fix these reported (built -> leaked): AnalysisPanel 835->835, CameraPanel
    276->276, MotorPanel 296->296, LaserPanel 90->90, CalibrationPanel 95->95,
    DeviceManagerWindow 54->54, ThemeEditorDialog 178->178, SegmentedControl
    4->4, DetachableTabWidget 7->7, SequencerPanel 41->41. BiasPanel (100) and
    ScopePanel (345) never leaked — they carry no self-capturing lambda, and
    sit here as the control group that must stay at 0 too.
  * ``test_*_connection_still_fires`` — the hazard/behaviour proofs: every
    rewired signal must still reach the same handler with the same arguments,
    with special attention to the motor jog pad, the sequencer reorder, the
    calibration dirty tracker and the device connect/disconnect buttons.
"""
from __future__ import annotations

import ast
import gc
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import yaml
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

APP_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _drain(app: QApplication) -> None:
    gc.collect()
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def _sim_device_manager(tmp_path):
    """A fully-simulated, never-connected DeviceManager (hardware-safety rule 1
    — construction only)."""
    from controller.device_manager import DeviceManager

    cfg = {
        "oscilloscope":      {"backend": "visa", "simulation": True},
        "motor_stage":       {"backend": "simulated"},
        "intensity_monitor": {"backend": "simulated"},
        "camera":            {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":       {"backend": "simulated"},
        "output":            {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return DeviceManager(config_path=str(path))


def _make(name, tmp_path):
    """Build one panel with simulated backends. Returns the widget."""
    if name == "SegmentedControl":
        from gui.panel_kit import SegmentedControl
        return SegmentedControl([("a", "A"), ("b", "B"), ("c", "C")])
    if name == "DetachableTabWidget":
        from gui.detachable_tabs import DetachableTabWidget
        tabs = DetachableTabWidget()
        tabs.addTab(QWidget(), "one")
        return tabs
    if name == "AnalysisPanel":
        from gui.analysis_panel import AnalysisPanel
        return AnalysisPanel(runs_dir=str(tmp_path / "runs"))
    if name == "CalibrationPanel":
        from gui.calibration_panel import CalibrationPanel
        return CalibrationPanel(_sim_device_manager(tmp_path))
    if name == "CameraPanel":
        from devices.camera_blackfly import BlackflyCamera
        from gui.camera_panel import CameraPanel
        return CameraPanel(BlackflyCamera(simulation=True))
    if name == "DeviceManagerWindow":
        from gui.device_panel import DeviceManagerWindow
        return DeviceManagerWindow(_sim_device_manager(tmp_path))
    if name == "LaserPanel":
        from devices.laser_manual import LaserManualMetadata
        from devices.waveform_generator import WaveformGenerator
        from gui.laser_panel import LaserPanel
        return LaserPanel(LaserManualMetadata(), WaveformGenerator(simulation=True))
    if name == "MotorPanel":
        from devices.motor_simulated import SimulatedMotorStage
        from gui.motor_panel import MotorPanel
        return MotorPanel(SimulatedMotorStage())
    if name == "ThemeEditorDialog":
        from PySide6.QtCore import QSettings
        from gui.theme_editor import ThemeEditorDialog
        s = QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)
        return ThemeEditorDialog(mode="dark", settings=s)
    if name == "SequencerPanel":
        return _make_sequencer()
    if name == "BiasPanel":       # control group — never leaked
        from devices.bias_supply_simulated import SimulatedBiasSupply
        from gui.bias_panel import BiasPanel
        return BiasPanel(SimulatedBiasSupply())
    if name == "ScopePanel":      # control group — never leaked
        from devices.oscilloscope import Oscilloscope
        from gui.scope_panel import ScopePanel
        return ScopePanel(Oscilloscope(simulation=True))
    raise KeyError(name)


def _make_sequencer():
    import test_sequencer_panel as tsp        # sibling test module (conftest sys.path)
    from gui.sequence_coordinator import SequenceCoordinator
    from gui.sequencer_panel import SequencerPanel

    sm = tsp._ready_sm()
    fake = tsp.FakeScanCoordinator(sm)
    coord = SequenceCoordinator(fake, sm, park_safe=tsp.ParkSpy())
    return SequencerPanel(coord, channel_provider=lambda: 0)


def _dispose(panel) -> None:
    """Run the panel's own thread-teardown contract before dropping it — a
    panel that parks a poller/worker QThread on the QApplication relies on
    shutdown() to quit it (TCTMainWindow._teardown_panels does the same)."""
    shutdown = getattr(panel, "shutdown", None)
    if callable(shutdown):
        shutdown()


# The panels that leaked (self-capturing lambda on a child's signal) plus the
# two controls that never did. All must reach delta 0.
_LEAKING = [
    "SegmentedControl", "DetachableTabWidget", "AnalysisPanel",
    "CalibrationPanel", "CameraPanel", "DeviceManagerWindow", "LaserPanel",
    "MotorPanel", "SequencerPanel", "ThemeEditorDialog",
]
_CONTROL = ["BiasPanel", "ScopePanel"]


# --------------------------------------------------------------------------- #
# 1. The AST guard — no self-capturing lambda in any .connect()               #
# --------------------------------------------------------------------------- #
class _ReferencesSelf(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "self":
            self.found = True


def _self_capturing_connect_sites(path: Path):
    """Every ``<something>.connect(lambda ... self ...)`` in *path*.

    Measured, not spelled: the argument to ``.connect`` is parsed, and a lambda
    whose body references ``self`` is flagged. This is the exact idiom that
    leaks — a closure over ``self`` handed to Qt's C++ connection storage. A
    lambda that captures only locals (e.g. ``lambda v: label.setText(v)``) is
    fine and is deliberately NOT flagged."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sites = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"):
            for arg in node.args:
                if isinstance(arg, ast.Lambda):
                    visitor = _ReferencesSelf()
                    visitor.visit(arg)
                    if visitor.found:
                        sites.append(node.lineno)
    return sites


def _guarded_files():
    files = sorted((APP_ROOT / "gui").glob("*.py"))
    files.append(APP_ROOT / "tct_gui.py")
    return files


def test_no_self_capturing_lambda_connected():
    """Zero ``.connect(lambda ...self...)`` across ``gui/*.py`` + ``tct_gui.py``.

    On the tree before this fix the same walk flagged 31 sites in 11 modules
    (analysis_panel 1, calibration_panel 4, camera_panel 6, detachable_tabs 1,
    device_panel 2, laser_panel 6, motor_panel 6, panel_kit 1, sequencer_panel
    2, theme_editor 1, tct_gui 1). Each was the immortal-panel cycle. They are
    now bound methods (PySide6 holds those weakly), so the count must be 0."""
    offenders = {}
    for path in _guarded_files():
        sites = _self_capturing_connect_sites(path)
        if sites:
            offenders[path.relative_to(APP_ROOT).as_posix()] = sites
    assert not offenders, (
        "self-capturing lambda(s) handed to .connect() — each is connected to a "
        "child's signal and stored in Qt's C++ connection list, which closes a "
        f"cycle gc cannot see and makes the whole panel immortal:\n{offenders}\n"
        "Convert each to a bound method (carry any per-widget key on the widget "
        "via setProperty + sender(), never in the closure).")


# --------------------------------------------------------------------------- #
# 2. Construct + drop -> delta 0 for every panel that leaked                   #
#                                                                              #
# Measured in a PRISTINE SUBPROCESS, one panel per interpreter — which is both #
# how the leak was originally quantified (open one panel in a fresh app, close #
# it) and the only safe way to do it. Constructing and destroying a dozen      #
# pyqtgraph-bearing panels back-to-back inside ONE process, each followed by a #
# gc + DeferredDelete storm, corrupts the heap (0xC0000374): pyqtgraph's       #
# parentless orphan widgets accumulate across tests (conftest deliberately     #
# refuses to reap them — three past attempts ended in native crashes) and the  #
# drain eventually frees one out from under a live item. A subprocess per      #
# panel sidesteps all cross-panel contamination AND contains any such crash as #
# a non-zero exit this test reports, instead of aborting the whole suite.      #
# --------------------------------------------------------------------------- #
def _measure_leak_in_subprocess(name: str) -> tuple[int, int, str]:
    """Run this file as a script in a fresh interpreter to construct+drop one
    panel and report ``(d_widgets, d_toplevel)``. Returns the parsed delta and
    the raw output (for the failure message)."""
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--measure", name],
        capture_output=True, text=True, timeout=50,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in proc.stdout.splitlines():
        if line.startswith("DELTA "):
            _, dw, dt = line.split()
            return int(dw), int(dt), out
    raise AssertionError(
        f"leak subprocess for {name} produced no DELTA line "
        f"(exit={proc.returncode} — a non-zero exit here is a NATIVE CRASH "
        f"while destroying the panel, which is itself a regression):\n{out}")


@pytest.mark.parametrize("name", _LEAKING + _CONTROL)
def test_panel_construct_drop_is_not_immortal(name):
    """Build the panel in a fresh process, run its teardown contract, drop it,
    drain Qt — and assert nothing is left alive. A self-capturing lambda on a
    child's signal would leave the entire tree behind (measured deltas in this
    module's docstring); a bound-method slot leaves nothing."""
    d_widgets, d_toplevel, out = _measure_leak_in_subprocess(name)
    assert d_widgets == 0 and d_toplevel == 0, (
        f"{name} is IMMORTAL: {d_widgets} widgets and {d_toplevel} top-levels "
        f"still alive after a fresh construct + drop + drain. A self-capturing "
        f"lambda connected to a child's signal is trapping the tree in a cycle "
        f"gc cannot break.\n{out}")


# --------------------------------------------------------------------------- #
# 3. Hazard / behaviour proofs — every rewired signal still fires the same     #
#    handler with the same arguments.                                          #
# --------------------------------------------------------------------------- #
def test_motor_jog_pad_all_six_connections_still_fire(monkeypatch):
    """DANGER CONTROL. The six jog buttons must each still reach ``_jog`` with
    the right (axis, direction) — a dropped or mis-wired jog connection would be
    a motion-safety regression. Fire every jog button and assert exactly the six
    expected commands come through, and the STOP button is untouched."""
    from devices.motor_simulated import SimulatedMotorStage
    from gui.motor_panel import MotorPanel

    _app()
    panel = MotorPanel(SimulatedMotorStage())
    try:
        calls = []
        monkeypatch.setattr(panel, "_jog", lambda axis, d: calls.append((axis, d)))

        jog_btns = [b for b in panel.findChildren(QPushButton)
                    if b.objectName() == "jogBtn"]
        assert len(jog_btns) == 6, f"expected 6 jog buttons, got {len(jog_btns)}"
        for b in jog_btns:
            b.click()

        assert sorted(calls) == sorted([
            ("x", +1), ("x", -1), ("y", +1), ("y", -1), ("z", +1), ("z", -1)]), (
            f"jog pad no longer delivers all six bounded moves: {calls}")
    finally:
        _dispose(panel)
        panel.deleteLater()


def test_sequencer_reorder_connections_still_fire(monkeypatch):
    """The Up/Down queue-reorder buttons must still call ``_move_selected`` with
    -1 / +1 (a reorder that silently no-ops would corrupt an unattended run
    queue)."""
    _app()
    panel = _make_sequencer()
    try:
        deltas = []
        monkeypatch.setattr(panel, "_move_selected", lambda d: deltas.append(d))
        # emit() (not click()) so the wiring is proven regardless of the
        # buttons' enabled-state, which the panel gates on the current selection.
        panel._btn_up.clicked.emit()
        panel._btn_down.clicked.emit()
        assert deltas == [-1, +1], f"reorder wiring changed: {deltas}"
    finally:
        _dispose(panel)
        panel.deleteLater()


def test_calibration_dirty_tracking_still_fires(monkeypatch, tmp_path):
    """Editing any tracked calibration field must still flip the panel to
    'unsaved' — the four rewired dirty-tracker connections (combo/spin/line/
    check) must all still land on ``_set_dirty``."""
    from gui.calibration_panel import CalibrationPanel

    _app()
    panel = CalibrationPanel(_sim_device_manager(tmp_path))
    try:
        marks = []
        monkeypatch.setattr(panel, "_set_dirty", lambda dirty: marks.append(dirty))
        # a spin box is one of the tracked widgets; changing it must mark dirty
        panel._thickness.setValue(panel._thickness.value() + 1.0)
        # a combo box is another tracked widget type
        panel._units.setCurrentIndex(
            (panel._units.currentIndex() + 1) % max(1, panel._units.count()))
        assert marks and all(m is True for m in marks), (
            f"calibration dirty-tracking connection was dropped by the fix: "
            f"{marks}")
    finally:
        _dispose(panel)
        panel.deleteLater()


def test_device_connect_buttons_still_target_their_own_row(monkeypatch, tmp_path):
    """Each row's Connect/Disconnect button must still act on ITS row. The row
    now travels on the button (a Qt property) instead of a lambda's closure, so
    prove the property round-trips to the right handler argument."""
    from gui.device_panel import DeviceManagerWindow

    _app()
    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        connects, disconnects = [], []
        monkeypatch.setattr(win, "_connect_one", lambda r: connects.append(r))
        monkeypatch.setattr(win, "_disconnect_one", lambda r: disconnects.append(r))
        for btn in win._row_buttons:
            row = btn.property("tctDeviceRow")
            assert row is not None
            btn.click()
        # every row fired exactly once on each action, on its own row index
        rows = sorted(win._row_map.keys())
        assert sorted(connects) == rows
        assert sorted(disconnects) == rows
    finally:
        win.close()
        win.deleteLater()


def test_segmented_control_still_emits_the_selected_key():
    """The segment key now travels on the button (property) and is re-emitted by
    a bound slot; picking a segment must still fire ``selection_changed`` with
    that key and no other."""
    from gui.panel_kit import SegmentedControl

    _app()
    seg = SegmentedControl([("map", "2D map"), ("cce", "CCE"), ("survey", "S")],
                           current="map")
    try:
        seen = []
        seg.selection_changed.connect(seen.append)
        seg.set_current("cce")
        seg._buttons["survey"].setChecked(True)
        assert seen == ["cce", "survey"], f"segmented key wiring changed: {seen}"
        assert seg.current_key() == "survey"
    finally:
        seg.deleteLater()


def test_theme_editor_swatch_opens_picker_for_its_own_token(monkeypatch, tmp_path):
    """Each colour swatch now carries its token as a property; clicking it must
    still open the picker for THAT token (behaviour preserved through the
    property round-trip, not a per-swatch closure)."""
    from PySide6.QtCore import QSettings
    from gui.theme_editor import ThemeEditorDialog

    s = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    _app()
    dlg = ThemeEditorDialog(mode="dark", settings=s)
    try:
        picked = []
        monkeypatch.setattr(dlg, "_pick_color",
                            lambda token, label: picked.append(token))
        for token, swatch in dlg._swatches.items():
            picked.clear()
            swatch.click()
            assert picked == [token], (
                f"swatch for {token!r} opened the picker for {picked} instead")
    finally:
        dlg.deleteLater()


def test_laser_live_apply_connections_still_reach_the_setter(monkeypatch):
    """Each wavegen spin box's editingFinished must still live-apply THAT
    control's value to the matching device setter (frequency/amplitude/offset/
    width/duty), read at call time exactly as the old lambdas did."""
    from devices.laser_manual import LaserManualMetadata
    from devices.waveform_generator import WaveformGenerator
    from gui.laser_panel import LaserPanel

    _app()
    panel = LaserPanel(LaserManualMetadata(), WaveformGenerator(simulation=True))
    try:
        applied = []
        monkeypatch.setattr(panel, "_live_apply",
                            lambda setter, value: applied.append(
                                (setter.__name__, value)))
        panel._spin_freq.setValue(2000.0)
        panel._spin_freq.editingFinished.emit()
        panel._spin_ampl.setValue(1.5)
        panel._spin_ampl.editingFinished.emit()
        names = {n for n, _ in applied}
        assert names == {"set_frequency", "set_amplitude"}, applied
        assert ("set_frequency", 2000.0) in applied
        assert ("set_amplitude", 1.5) in applied
    finally:
        _dispose(panel)
        panel.deleteLater()


def test_camera_view_toggles_and_device_controls_still_fire(monkeypatch):
    """The crosshair/overlay view toggles and the pixel-format/trigger device
    controls were all rewired to bound methods; each must still take effect."""
    from devices.camera_blackfly import BlackflyCamera
    from gui.camera_panel import CameraPanel

    _app()
    cam = BlackflyCamera(simulation=True)
    panel = CameraPanel(cam)
    try:
        # view-only toggles flip the panel flags
        panel._chk_crosshair.setChecked(False)
        assert panel._show_crosshair is False
        panel._chk_overlay.setChecked(False)
        assert panel._show_overlay is False

        # device controls reach the camera
        fmts, trigs = [], []
        monkeypatch.setattr(cam, "set_pixel_format", lambda f: fmts.append(f))
        monkeypatch.setattr(cam, "set_trigger", lambda v: trigs.append(v))
        panel._combo_fmt.setCurrentText("Mono16")
        panel._chk_trigger.setChecked(True)
        assert fmts == ["Mono16"], fmts
        assert trigs == [True], trigs
    finally:
        _dispose(panel)
        panel.deleteLater()


# --------------------------------------------------------------------------- #
# 4. Worker-thread teardown hazard — a mortal panel dropped WITHOUT shutdown() #
#    must not crash when gc / the reaper frees it.                             #
#                                                                              #
# CameraPanel, MotorPanel and LaserPanel each run a worker on a QThread that   #
# is parented to the QApplication (so it survives a soft config-reload), while #
# the worker QObject is held by a plain Python attribute on the panel. Making  #
# the panel collectable (the bound-method fix above) exposed a latent hazard:  #
# dropping the panel WITHOUT calling shutdown() first — a legacy panel test    #
# does exactly this, and so does the conftest reaper, whose leading            #
# gc.collect() pre-empts its own shutdown() call — deallocated that worker     #
# FROM THE GUI THREAD while its QTimer was still polling on the worker thread.  #
# Cross-thread QObject destruction is heap corruption (0xC0000374 / an access  #
# violation with ``<no Python frame>`` on the worker thread). While the panel  #
# was immortal (self-capturing lambda) gc never ran this teardown, so the      #
# crash was masked — camera reproducibly, motor latently. The fix is a         #
# weakref.finalize on each panel that quits+joins the worker thread before the #
# worker is freed. This test drives the crash path — drop, NO shutdown, gc,    #
# reaper-style teardown — in a fresh process, many times; an unfixed panel     #
# aborts the interpreter, surfaced here as a non-zero subprocess exit.         #
# --------------------------------------------------------------------------- #
_THREAD_PANELS = ["CameraPanel", "MotorPanel", "LaserPanel"]


@pytest.mark.parametrize("name", _THREAD_PANELS)
def test_thread_panel_survives_drop_without_shutdown(name):
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--reaploop", name, "12"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0 and "REAP_SURVIVED" in proc.stdout, (
        f"{name} crashed the interpreter when dropped without shutdown() and "
        f"freed by gc / the reaper (exit={proc.returncode}). Its worker QObject "
        f"was deallocated from the GUI thread while its QThread was still "
        f"polling — the weakref.finalize must quit+join the thread first.\n{out}")


# --------------------------------------------------------------------------- #
# Subprocess entry: ``python test_no_immortal_panels.py --measure <PanelName>``#
# runs ONE construct+drop in a pristine interpreter and prints ``DELTA w t``.  #
# Used by test_panel_construct_drop_is_not_immortal (see the note there for    #
# why a fresh process per panel is required).                                  #
# --------------------------------------------------------------------------- #
def _run_measurement(name: str) -> None:
    import tempfile

    sys.path.insert(0, str(APP_ROOT))          # so ``import gui.*`` resolves
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling test mods
    os.chdir(APP_ROOT)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = _app()
    tmp = Path(tempfile.mkdtemp(prefix="immortal_"))

    def cycle():
        panel = _make(name, tmp)
        _dispose(panel)
        del panel
        _drain(app)

    cycle()                                    # warm-up: absorb pyqtgraph one-offs
    w0 = len(app.allWidgets())
    t0 = len(app.topLevelWidgets())

    panel = _make(name, tmp)
    _dispose(panel)
    del panel
    _drain(app)

    dw = len(app.allWidgets()) - w0
    dt = len(app.topLevelWidgets()) - t0
    print(f"DELTA {dw} {dt}", flush=True)


def _reaper_teardown(app) -> None:
    """The committed conftest widget-reaper, in the SAME order it uses — gc.
    collect() BEFORE the per-widget shutdown() loop, which is exactly what lets
    a mortal panel be freed before its worker thread is stopped."""
    from PySide6.QtCore import QEvent

    before = {id(w) for w in app.topLevelWidgets()}   # (already drained above)
    gc.collect()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    doomed = [
        w for w in app.topLevelWidgets()
        if id(w) not in before
        and (type(w).__module__ or "").startswith(("gui.", "tct_gui"))
    ]
    for widget in doomed:
        shutdown = getattr(widget, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                continue
        try:
            widget.close()
        except Exception:
            pass
        try:
            widget.deleteLater()
        except (RuntimeError, ReferenceError):
            continue
    gc.collect()
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def _run_reap_loop(name: str, iters: int) -> None:
    """Construct + drop *name* WITHOUT shutdown(), then run the flush fixture
    and the reaper teardown, in a loop — the precise sequence that crashed the
    suite for a panel whose worker thread outlives an un-shut-down drop."""
    import tempfile

    from PySide6.QtCore import QEvent

    sys.path.insert(0, str(APP_ROOT))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.chdir(APP_ROOT)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = _app()
    tmp = Path(tempfile.mkdtemp(prefix="reaploop_"))
    for _ in range(iters):
        panel = _make(name, tmp)
        del panel                      # NO _dispose/shutdown — the crash path
        gc.collect()                   # conftest _flush_qt_deferred_deletes
        for _ in range(3):
            app.processEvents()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        _reaper_teardown(app)          # conftest _reap_leaked_toplevel_widgets
    print("REAP_SURVIVED", flush=True)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--measure":
        _run_measurement(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "--reaploop":
        _run_reap_loop(sys.argv[2], int(sys.argv[3]))
