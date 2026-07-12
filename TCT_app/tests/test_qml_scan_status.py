"""Headless tests for the Scan Viewer slice's new QML tiles:
``gui/qml/MetricTile.qml`` and ``gui/qml/ScanStatusStrip.qml``.

Lighter pattern than ``tests/test_qml_shell.py``'s full ``TCTMainWindow`` /
``QQuickWidget`` build: these two files are leaf VIEW components (no window
chrome needed to exercise them), so they are loaded directly via a bare
``QQmlEngine`` + ``QQmlComponent`` — the same "import gui.qml_theme before
loading QML" setup ``gui/qml_shell.py::build_qml_chrome`` uses to make
``import Tct`` resolvable, minus the ``QQuickWidget``/window plumbing.

Covers, per the task brief:
  (a) MetricTile.qml loads via QQmlComponent with zero errors;
  (b) ScanStatusStrip.qml loads against a stub ``runState`` (the real
      ``RunStateViewModel``, per the brief's "or reuse RunStateViewModel
      directly" option) and instantiates without QML errors;
  (c) changing a stub runState value updates the bound tile's text, pulled
      via ``findChild`` on ``objectName``.
Plus a MetricTile compact-mode structural check (caption hides + tile
shrinks) and the strip's `stale` flag flipping with `runState.active`.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication

_QML_DIR = Path(__file__).resolve().parent.parent / "gui" / "qml"


# --------------------------------------------------------------------------- #
# Harness — mirrors tests/test_qml_shell.py's _app()/_pump() helpers            #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(seconds: float = 0.05) -> None:
    app = _app()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.005)


def _engine() -> QQmlEngine:
    """A fresh ``QQmlEngine`` with ``import Tct`` (the Theme singleton)
    resolvable — importing ``gui.qml_theme`` registers the ``@QmlElement``/
    ``@QmlSingleton`` type process-wide, the same setup
    ``build_qml_chrome`` does before ``chrome.setSource(...)``. Also runs
    ``qml_shell._ensure_qml_dll_path()`` (Windows QtQuick/Layouts plugin DLL
    resolution) — a bare ``QQmlEngine`` needs it too, not just a
    ``QQuickWidget``."""
    _app()
    from gui import qml_shell, qml_theme
    qml_shell._ensure_qml_dll_path()
    qml_theme.set_theme_mode("light")
    return QQmlEngine()


def _load(engine: QQmlEngine, path: Path):
    """Load *path* via ``QQmlComponent`` and return ``(component, obj)``.
    ``obj`` is ``None`` if creation failed — callers check
    ``component.errors()`` first."""
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    _pump(0.02)  # let a (normally synchronous, local-file) load settle
    obj = component.create()
    return component, obj


def _errs(component: QQmlComponent) -> list[str]:
    return [e.toString() for e in component.errors()]


# --------------------------------------------------------------------------- #
# (a) MetricTile.qml — loads via QQmlComponent with zero errors                 #
# --------------------------------------------------------------------------- #
def test_metric_tile_loads_with_zero_errors():
    engine = _engine()
    component, obj = _load(engine, _QML_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        assert obj is not None
        assert obj.property("objectName") == "metricTile"
    finally:
        if obj is not None:
            obj.deleteLater()
        _pump()


def test_metric_tile_binds_title_value_unit_caption_accent():
    engine = _engine()
    component, obj = _load(engine, _QML_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        obj.setProperty("title", "ETA")
        obj.setProperty("value", "12.3")
        obj.setProperty("unit", "min")
        obj.setProperty("caption", "estimate")
        _pump(0.02)

        title_label = obj.findChild(QObject, "tileTitle")
        value_label = obj.findChild(QObject, "tileValue")
        unit_label = obj.findChild(QObject, "tileUnit")
        caption_label = obj.findChild(QObject, "tileCaption")
        assert title_label.property("text") == "ETA"
        assert value_label.property("text") == "12.3"
        assert unit_label.property("text") == "min"
        assert caption_label.property("text") == "estimate"
    finally:
        obj.deleteLater()
        _pump()


def test_metric_tile_compact_hides_caption_and_shrinks():
    engine = _engine()
    component, obj = _load(engine, _QML_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        obj.setProperty("caption", "x=1.000 y=2.000 z=3.000")
        obj.setProperty("compact", False)
        _pump(0.02)
        full_height = obj.property("implicitHeight")
        caption_label = obj.findChild(QObject, "tileCaption")
        assert caption_label is not None
        assert caption_label.property("visible") is True

        obj.setProperty("compact", True)
        _pump(0.02)
        compact_height = obj.property("implicitHeight")
        assert compact_height < full_height
        assert caption_label.property("visible") is False
    finally:
        obj.deleteLater()
        _pump()


def test_metric_tile_stale_dims_opacity():
    engine = _engine()
    component, obj = _load(engine, _QML_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        obj.setProperty("stale", False)
        _pump(0.02)
        assert obj.property("opacity") == 1.0
        obj.setProperty("stale", True)
        _pump(0.2)  # the 150ms opacity Behavior needs a moment to settle
        assert obj.property("opacity") < 1.0
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# (b) ScanStatusStrip.qml — loads against a stub runState (RunStateViewModel)   #
# --------------------------------------------------------------------------- #
def test_scan_status_strip_loads_against_stub_runstate():
    from gui.run_state_viewmodel import RunStateViewModel

    engine = _engine()
    vm = RunStateViewModel()
    engine.rootContext().setContextProperty("runState", vm)
    component, obj = _load(engine, _QML_DIR / "ScanStatusStrip.qml")
    try:
        assert _errs(component) == []
        assert obj is not None
        assert obj.property("objectName") == "scanStatusStrip"

        # All five tiles are present, per the task brief's binding list.
        for name in ("tileState", "tileProgress", "tileEta", "tileElapsed", "tileScan"):
            tile = obj.findChild(QObject, name)
            assert tile is not None, f"missing tile {name!r}"
    finally:
        obj.deleteLater()
        vm.deleteLater()
        _pump()


def test_scan_status_strip_loads_with_null_runstate():
    """``runState`` explicitly bound to ``None`` (Python) -> QML ``null`` — the
    documented "may be None in a future caller" case from
    ``gui/qml_shell.py::build_qml_chrome``'s own docstring. The strip's
    `runState ? ... : "--"` guards must keep every tile error-free and
    showing the "--" fallback rather than crashing on a null dereference.
    (Omitting the context property entirely is a different, unrealistic case:
    an undefined QML identifier throws a ReferenceError at binding-evaluation
    time, which production never hits because the context property is always
    set — see ``build_qml_chrome``.)"""
    engine = _engine()
    engine.rootContext().setContextProperty("runState", None)
    component, obj = _load(engine, _QML_DIR / "ScanStatusStrip.qml")
    try:
        assert _errs(component) == []
        assert obj is not None
        state_tile = obj.findChild(QObject, "tileState")
        value_label = state_tile.findChild(QObject, "tileValue")
        assert value_label.property("text") == "--"
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# (c) Changing a stub runState value updates the bound tile's text/state        #
# --------------------------------------------------------------------------- #
def test_scan_status_strip_updates_on_runstate_change():
    from controller.state_machine import AppState
    from gui.run_state_viewmodel import RunStateViewModel

    engine = _engine()
    vm = RunStateViewModel()
    engine.rootContext().setContextProperty("runState", vm)
    component, obj = _load(engine, _QML_DIR / "ScanStatusStrip.qml")
    try:
        assert _errs(component) == []

        state_tile = obj.findChild(QObject, "tileState")
        state_value = state_tile.findChild(QObject, "tileValue")
        scan_tile = obj.findChild(QObject, "tileScan")
        scan_value = scan_tile.findChild(QObject, "tileValue")

        # Idle boot state, per RunStateViewModel's own defaults.
        assert state_value.property("text") == "DISCONNECTED"
        assert state_tile.property("stale") is True  # not active yet

        vm.update(state=AppState.RUNNING, scan_type="Grid")
        _pump(0.05)

        assert state_value.property("text") == "RUNNING"
        assert scan_value.property("text") == "Grid"
        assert state_tile.property("stale") is False  # runState.active now True

        # Progress + point text via the coordinator-signal feed methods.
        vm.on_progress(3, 12)
        _pump(0.02)
        progress_tile = obj.findChild(QObject, "tileProgress")
        progress_value = progress_tile.findChild(QObject, "tileValue")
        progress_caption = progress_tile.findChild(QObject, "tileCaption")
        assert progress_value.property("text") == "3/12"
        assert progress_caption.property("text") == vm.pointText

        # Finishing the run flips `active` back off -> tiles go stale again.
        vm.on_scan_finished()
        _pump(0.02)
        assert state_tile.property("stale") is True
    finally:
        obj.deleteLater()
        vm.deleteLater()
        _pump()
