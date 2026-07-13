"""Headless tests for the Scan Viewer slice's QML tiles:
``gui/qml/MetricTile.qml`` and ``gui/qml/ScanStatusStrip.qml``.

Lighter pattern than ``tests/test_qml_shell.py``'s full ``TCTMainWindow`` /
``QQuickWidget`` build: these two files are leaf VIEW components (no window
chrome needed to exercise them), so they are loaded directly via a bare
``QQmlEngine`` + ``QQmlComponent`` — the same "import gui.qml_theme before
loading QML" setup ``gui/qml_shell.py::build_qml_chrome`` uses to make
``import Tct`` resolvable, minus the ``QQuickWidget``/window plumbing.

Cockpit v5 D2 pass (docs/design/cockpit_design_system.md §5's strip
hierarchy — State / HV·measured / Progress·ETA merged (with meter) /
Position compact; last-charge and the old separate ETA/Elapsed/Scan tiles are
gone, per the ratified design): ScanStatusStrip.qml now binds a SECOND
context property, ``shell`` (gui/qml_shell.py::_ShellBridge — the same one
Shell.qml's rail already binds), for the HV tile's cached bias readout. These
tests build a real ``_ShellBridge`` (not a hand-rolled stub QObject) against a
controllable ``state_provider`` callable, matching the "reuse the real
view-model" pattern the ``runState`` tests already use for
``RunStateViewModel``.

Covers:
  (a) MetricTile.qml loads via QQmlComponent with zero errors, including the
      new optional progress meter;
  (b) ScanStatusStrip.qml loads against stub ``runState``/``shell`` and
      instantiates without QML errors, with the new 4-tile set;
  (c) changing stub runState/shell values updates the bound tiles' text/
      caption/stale, pulled via ``findChild`` on ``objectName``;
  (d) the sim ribbon (Shell.qml) and readiness caption (tct_gui/_ShellBridge)
      additions are covered by tests/test_qml_shell.py instead (they need the
      full rail, not just the leaf strip).
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


def _shell_bridge(initial_state: dict | None = None):
    """A real ``_ShellBridge`` against a controllable state dict — the same
    "reuse the real view-model, not a hand-rolled stub" pattern the
    ``runState`` tests below already use for ``RunStateViewModel``. Returns
    ``(bridge, state)``; mutate ``state`` in place and call ``bridge.pull()``
    to push a new snapshot."""
    from gui.qml_shell import _ShellBridge

    state = dict(initial_state or {})
    bridge = _ShellBridge(
        state_provider=lambda: state,
        on_connect=lambda: None,
        on_disconnect=lambda: None,
        on_toggle_theme=lambda: None,
    )
    bridge.pull()
    return bridge, state


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


def test_metric_tile_value_label_actually_gets_laid_out_width():
    """Regression pin: ``tileValue``'s ``width`` binding references the unit
    Text sibling by id (``unitLabel.visible``/``unitLabel.implicitWidth``) —
    that sibling previously carried only an ``objectName`` and no ``id``, so
    the reference threw a QML ReferenceError at binding-evaluation time
    (silent — ``QQmlComponent.errors()`` does not catch runtime binding
    errors) and ``tileValue.width`` silently stayed 0 forever. The value text
    still reported the right *string* via ``.property("text")`` (every prior
    test here passed), so this went undetected until D2's capture-harness
    eyeball caught the strip's value line rendering as invisible/zero-width
    in a real screenshot. Pin the actual laid-out width so this class of bug
    (a broken id reference that only breaks PAINT, not the property value)
    cannot silently return."""
    engine = _engine()
    component, obj = _load(engine, _QML_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        obj.setProperty("width", 220)
        obj.setProperty("value", "DISCONNECTED")
        _pump(0.05)
        value_label = obj.findChild(QObject, "tileValue")
        assert value_label.property("width") > 0, (
            "tileValue got width<=0 — the unitLabel id reference regressed"
        )
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
# (a2) MetricTile.qml — optional progress meter (D2 — the merged Progress·ETA #
#      strip tile "with meter")                                                #
# --------------------------------------------------------------------------- #
def test_metric_tile_meter_hidden_by_default():
    engine = _engine()
    component, obj = _load(engine, _QML_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        meter = obj.findChild(QObject, "tileMeter")
        assert meter is not None
        assert meter.property("visible") is False  # meterFraction defaults to -1
    finally:
        obj.deleteLater()
        _pump()


def test_metric_tile_meter_fill_tracks_fraction():
    engine = _engine()
    component, obj = _load(engine, _QML_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        obj.setProperty("meterFraction", 0.25)
        _pump(0.02)
        meter = obj.findChild(QObject, "tileMeter")
        fill = obj.findChild(QObject, "tileMeterFill")
        assert meter.property("visible") is True
        meter_w = meter.property("width")
        _pump(0.3)  # the width Behavior needs a moment to settle
        assert abs(fill.property("width") - 0.25 * meter_w) < 1.0

        # Out-of-range fractions are clamped, never overflow the tile.
        obj.setProperty("meterFraction", 1.7)
        _pump(0.3)
        assert fill.property("width") <= meter_w + 0.5
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# (b) ScanStatusStrip.qml — loads against stub runState/shell                   #
# --------------------------------------------------------------------------- #
def test_scan_status_strip_loads_against_stub_runstate():
    from gui.run_state_viewmodel import RunStateViewModel

    engine = _engine()
    vm = RunStateViewModel()
    bridge, _state = _shell_bridge()
    engine.rootContext().setContextProperty("runState", vm)
    engine.rootContext().setContextProperty("shell", bridge)
    component, obj = _load(engine, _QML_DIR / "ScanStatusStrip.qml")
    try:
        assert _errs(component) == []
        assert obj is not None
        assert obj.property("objectName") == "scanStatusStrip"

        # The strip-hierarchy tile set (design system §5): State / HV /
        # merged Progress·ETA / compact Position. The old separate ETA/
        # Elapsed/Scan tiles are gone.
        for name in ("tileState", "tileHv", "tileProgress", "tilePosition"):
            tile = obj.findChild(QObject, name)
            assert tile is not None, f"missing tile {name!r}"
        for name in ("tileEta", "tileElapsed", "tileScan"):
            assert obj.findChild(QObject, name) is None, (
                f"tile {name!r} should have been dropped from the D2 strip"
            )
    finally:
        obj.deleteLater()
        vm.deleteLater()
        bridge.deleteLater()
        _pump()


def test_scan_status_strip_loads_with_null_runstate_and_shell():
    """Both ``runState`` and ``shell`` explicitly bound to ``None`` (Python)
    -> QML ``null`` — the documented "may be None in a future caller" case
    from ``gui/qml_shell.py::build_qml_chrome``'s own docstring. Every guard
    (`runState ? ... : ...` / `shell ? ... : ...`) must keep the strip
    error-free and showing its fallback rather than crashing on a null
    dereference. (Omitting the context property entirely is a different,
    unrealistic case: an undefined QML identifier throws a ReferenceError at
    binding-evaluation time, which production never hits because both context
    properties are always set — see ``build_qml_chrome``.)"""
    engine = _engine()
    engine.rootContext().setContextProperty("runState", None)
    engine.rootContext().setContextProperty("shell", None)
    component, obj = _load(engine, _QML_DIR / "ScanStatusStrip.qml")
    try:
        assert _errs(component) == []
        assert obj is not None

        state_tile = obj.findChild(QObject, "tileState")
        state_value = state_tile.findChild(QObject, "tileValue")
        assert state_value.property("text") == "--"

        hv_tile = obj.findChild(QObject, "tileHv")
        hv_value = hv_tile.findChild(QObject, "tileValue")
        assert hv_value.property("text") == "--"
        hv_caption = hv_tile.findChild(QObject, "tileCaption")
        assert hv_caption.property("text") == "not connected"
        assert hv_tile.property("stale") is True

        pos_tile = obj.findChild(QObject, "tilePosition")
        pos_value = pos_tile.findChild(QObject, "tileValue")
        assert pos_value.property("text") == "--"
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# (c) Changing stub runState/shell values updates the bound tiles              #
# --------------------------------------------------------------------------- #
def test_scan_status_strip_updates_on_runstate_change():
    from controller.state_machine import AppState
    from gui.run_state_viewmodel import RunStateViewModel

    engine = _engine()
    vm = RunStateViewModel()
    bridge, _state = _shell_bridge()
    engine.rootContext().setContextProperty("runState", vm)
    engine.rootContext().setContextProperty("shell", bridge)
    component, obj = _load(engine, _QML_DIR / "ScanStatusStrip.qml")
    try:
        assert _errs(component) == []

        state_tile = obj.findChild(QObject, "tileState")
        state_value = state_tile.findChild(QObject, "tileValue")

        # Idle boot state, per RunStateViewModel's own defaults.
        assert state_value.property("text") == "DISCONNECTED"
        assert state_tile.property("stale") is True  # not active yet

        vm.update(state=AppState.RUNNING, scan_type="Grid")
        _pump(0.05)

        assert state_value.property("text") == "RUNNING"
        assert state_tile.property("stale") is False  # runState.active now True

        # Progress·ETA (merged) + point text via the coordinator-signal feed.
        vm.on_progress(3, 12)
        _pump(0.02)
        progress_tile = obj.findChild(QObject, "tileProgress")
        progress_value = progress_tile.findChild(QObject, "tileValue")
        progress_caption = progress_tile.findChild(QObject, "tileCaption")
        assert progress_value.property("text") == "3/12 · " + vm.etaText
        assert progress_caption.property("text") == vm.pointText
        assert abs(progress_tile.property("meterFraction") - 0.25) < 1e-9

        # Position tile mirrors the same point text (compact tile).
        pos_tile = obj.findChild(QObject, "tilePosition")
        pos_value = pos_tile.findChild(QObject, "tileValue")
        assert pos_value.property("text") == vm.pointText
        assert pos_tile.property("compact") is True

        # Finishing the run flips `active` back off -> tiles go stale again.
        vm.on_scan_finished()
        _pump(0.02)
        assert state_tile.property("stale") is True
    finally:
        obj.deleteLater()
        vm.deleteLater()
        bridge.deleteLater()
        _pump()


def test_scan_status_strip_hv_tile_tracks_shell_bridge():
    """The HV tile is fed from the `shell` rail bridge's cached bias readout
    (`_ShellBridge.hvText`/`hvState`, mirroring
    `tct_gui._collect_shell_state()["hv"]` — the SAME cached value the
    classic ribbon's HV chip shows), not `runState` — no device I/O happens
    on this timer, only a `state_provider()` dict read."""
    from gui.run_state_viewmodel import RunStateViewModel

    engine = _engine()
    vm = RunStateViewModel()
    bridge, state = _shell_bridge()
    engine.rootContext().setContextProperty("runState", vm)
    engine.rootContext().setContextProperty("shell", bridge)
    component, obj = _load(engine, _QML_DIR / "ScanStatusStrip.qml")
    try:
        assert _errs(component) == []
        hv_tile = obj.findChild(QObject, "tileHv")
        hv_value = hv_tile.findChild(QObject, "tileValue")
        hv_caption = hv_tile.findChild(QObject, "tileCaption")

        # No reading yet: stale, "not connected".
        assert hv_value.property("text") == "--"
        assert hv_caption.property("text") == "not connected"
        assert hv_tile.property("stale") is True

        # A live, nonzero reading ("armed" per the classic ribbon's HV chip
        # convention — see tct_gui._refresh_bias_strip): "HV " prefix
        # trimmed, caption says "output on", tile is no longer stale.
        state["hv"] = ["HV +250.0 V", "armed"]
        bridge.pull()
        _pump(0.02)
        assert hv_value.property("text") == "+250.0 V"
        assert hv_caption.property("text") == "output on"
        assert hv_tile.property("stale") is False

        # A near-zero reading ("good" per the same convention): output off.
        state["hv"] = ["HV +0.0 V", "good"]
        bridge.pull()
        _pump(0.02)
        assert hv_value.property("text") == "+0.0 V"
        assert hv_caption.property("text") == "output off"
        assert hv_tile.property("stale") is False
    finally:
        obj.deleteLater()
        vm.deleteLater()
        bridge.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# (d) Strip-hierarchy tile widths follow the §5 flex ratio                     #
#     (State 1.5fr / HV 1.1fr / Progress·ETA 1fr / Position 0.9fr)             #
# --------------------------------------------------------------------------- #
def test_scan_status_strip_tile_widths_follow_flex_ratio():
    from gui.run_state_viewmodel import RunStateViewModel

    engine = _engine()
    vm = RunStateViewModel()
    bridge, _state = _shell_bridge()
    engine.rootContext().setContextProperty("runState", vm)
    engine.rootContext().setContextProperty("shell", bridge)
    component, obj = _load(engine, _QML_DIR / "ScanStatusStrip.qml")
    try:
        assert _errs(component) == []
        obj.setProperty("width", 900)
        _pump(0.02)

        state_w = obj.findChild(QObject, "tileState").property("width")
        hv_w = obj.findChild(QObject, "tileHv").property("width")
        progress_w = obj.findChild(QObject, "tileProgress").property("width")
        pos_w = obj.findChild(QObject, "tilePosition").property("width")

        # State (1.5fr) is the most salient (widest); Position (0.9fr) the
        # narrowest — the exact §5 ordering, not just "some tile is bigger".
        assert state_w > hv_w > progress_w > pos_w > 0
        # Ratio check (tolerant of the spacing subtracted from the total).
        assert abs((state_w / pos_w) - (1.5 / 0.9)) < 0.05
    finally:
        obj.deleteLater()
        vm.deleteLater()
        bridge.deleteLater()
        _pump()
