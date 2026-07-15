"""U2.2 — kit component conformance suite (kit_spec_v1.md §3 inventory, the
ScanViewer-consumed subset): ``gui/qml/kit/{PanelHeader,StatusPill,Card,
MetricTile,MetricGrid,CollapsibleCard,ActionBar,EmptyState,FormRow,
FigureCard}.qml``.

Same bare-``QQmlEngine`` harness as tests/test_qml_kit_surface.py /
tests/test_qml_scan_status.py (leaf/composed view components; no window
chrome needed). Every component is ``Surface`` + content (or, for the
"(typography)"/"(layout)" rows the spec itself marks as owning no material —
PanelHeader/FormRow/MetricGrid — a plain ``Item``); state/motion assertions
follow kit_spec_v1.md §2.6/§3/§5.1 per component.

Visual-parent note: a QML item's ``QObject.parent()`` (Python/C++ object
ownership, set once at document-creation time) is NOT the same thing as its
Qt Quick VISUAL parent (the ``Item.parent`` QML property / scene-graph
``parentItem()``, which is what a ``default property alias X: inner.data``
override actually redirects). Content-routing assertions below therefore
resolve ``parent.objectName`` via a ``QQmlExpression`` evaluated in the
child's own QML context (``_visual_parent_name``), never ``obj.parent()``.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtWidgets import QApplication

_QML_DIR = Path(__file__).resolve().parent.parent / "gui" / "qml"
_KIT_DIR = _QML_DIR / "kit"

SHELF, CARD, TILE, WELL, ISLAND, HAZARD = 0, 1, 2, 3, 4, 5


# --------------------------------------------------------------------------- #
# Harness (mirrors tests/test_qml_kit_surface.py / test_qml_scan_status.py)    #
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
    _app()
    from gui import qml_shell, qml_theme
    qml_shell._ensure_qml_dll_path()
    qml_theme.set_theme_mode("light")
    return QQmlEngine()


def _load(engine: QQmlEngine, path: Path, props: dict | None = None):
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    _pump(0.02)
    if props:
        obj = component.createWithInitialProperties(props)
    else:
        obj = component.create()
    return component, obj


def _errs(component: QQmlComponent) -> list[str]:
    return [e.toString() for e in component.errors()]


def _load_wrapper(engine: QQmlEngine, qml_body: str, name: str):
    """Build a throwaway wrapper document nesting consumer content inside a
    kit type the same way a real panel author would (``Kit.Card { Text {
    ... } }``), using the SAME relative ``import "kit" as Kit`` convention
    gui/qml/ScanStatusStrip.qml itself uses.

    ``tmp_path`` (pytest's per-test temp dir) is NOT usable here: an
    absolute-path directory import from an unrelated filesystem location hit
    a real QQmlEngine quirk during this beat's own verification ("Network
    error" resolving the imported directory's own qmldir-relative
    dependencies) — the wrapper is instead written as a THROWAWAY sibling of
    ``kit/`` inside ``gui/qml/`` itself (deleted immediately after the
    component is compiled; the source file is not needed once ``create()``
    has run) so the relative import resolves exactly like production."""
    wrapper = (
        "import QtQuick\nimport Tct\nimport \"kit\" as Kit\n"
        "Item {\n    id: wrap\n    width: 400\n    height: 400\n" + qml_body + "\n}\n"
    )
    path = _QML_DIR / f"_test_probe_{name}"
    path.write_text(wrapper, encoding="utf-8")
    try:
        return _load(engine, path)
    finally:
        path.unlink(missing_ok=True)


def _visual_parent_name(obj) -> str:
    """The Qt Quick VISUAL parent's objectName (see module docstring) — NOT
    ``QObject.parent()``, which stays the document's declaring scope and
    does not reflect a ``default property alias`` content-routing target."""
    ctx = QQmlEngine.contextForObject(obj)
    expr = QQmlExpression(ctx, obj, 'parent ? parent.objectName : "<no-parent>"')
    val = expr.evaluate()
    if isinstance(val, tuple):
        val = val[0]
    assert not expr.hasError(), expr.error().toString()
    return str(val)


def _color_name(obj, prop: str) -> str:
    return obj.property(prop).name().lower()


# --------------------------------------------------------------------------- #
# PanelHeader — typography-only (kit_spec_v1.md §3 "(typography)" row)         #
# --------------------------------------------------------------------------- #
def test_panel_header_loads_and_binds_eyebrow_title():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "PanelHeader.qml",
                           {"eyebrow": "scan viewer", "title": "Scan Viewer"})
    try:
        assert _errs(component) == []
        assert obj.property("objectName") == "kitPanelHeader"
        eyebrow = obj.findChild(QObject, "panelHeaderEyebrow")
        title = obj.findChild(QObject, "panelHeaderTitle")
        assert eyebrow.property("text") == "scan viewer"
        assert title.property("text") == "Scan Viewer"
    finally:
        obj.deleteLater()
        _pump()


def test_panel_header_trailing_content_routes_into_trailing_row():
    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.PanelHeader {
        id: ph
        objectName: "probePH"
        eyebrow: "state"
        title: "Idle"
        Rectangle { objectName: "probeTrailing"; width: 10; height: 10 }
    }
    """, "panel_header_trailing.qml")
    try:
        assert _errs(component) == []
        trailing = obj.findChild(QObject, "probeTrailing")
        assert trailing is not None
        assert _visual_parent_name(trailing) == "panelHeaderTrailing"
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# StatusPill — glyph + WORD + colour, never colour alone (kit_spec_v1.md §3)   #
# --------------------------------------------------------------------------- #
def test_status_pill_loads_with_zero_errors():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "StatusPill.qml",
                           {"text": "RUNNING", "state": "busy"})
    try:
        assert _errs(component) == []
        assert obj.property("objectName") == "kitStatusPill"
        assert obj.property("rung") == TILE
    finally:
        obj.deleteLater()
        _pump()


def test_status_pill_never_colour_alone_across_states():
    """Every state carries BOTH the glyph (shape) and the WORD (text) —
    colour (the glyph/word ink) is never the sole channel."""
    from gui.style import palette

    p = palette("light")
    expected_dot = {
        "neutral": p["muted"], "good": p["good"], "warn": p["warn"],
        "armed": p["warn"], "crit": p["crit"], "fault": p["crit"],
        "busy": p["accent"], "info": p["accent"], "simulated": p["sim"],
    }
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "StatusPill.qml", {"text": "X"})
    try:
        assert _errs(component) == []
        glyph = obj.findChild(QObject, "statusPillGlyph")
        word = obj.findChild(QObject, "statusPillWord")
        for state, hexval in expected_dot.items():
            obj.setProperty("state", state)
            obj.setProperty("text", state.upper())
            _pump(0.3)   # settle the dot's ColorAnimation (Theme.transitionMs)
            assert glyph.property("visible") is not False   # shape channel present
            assert word.property("text") == state.upper()   # text channel present
            assert _color_name(glyph, "color") == hexval.lower(), state
    finally:
        obj.deleteLater()
        _pump()


def test_status_pill_chip_fill_and_hit_target():
    """Fill resolves the spec-mandated `chip` token (the Surface knob-gap
    workaround — see StatusPill.qml's own header note) and the pill clears
    the >= 36 px interactive hit-target floor (§2.6)."""
    from gui.style import palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "StatusPill.qml", {"text": "IDLE"})
    try:
        assert _errs(component) == []
        fill = obj.findChild(QObject, "statusPillChipFill")
        assert _color_name(fill, "color") == palette("light")["chip"].lower()
        assert obj.property("implicitHeight") >= 36
    finally:
        obj.deleteLater()
        _pump()


def test_status_pill_width_springs_on_text_change(monkeypatch):
    """Motion obligation (§3 StatusPill row): width change springs
    (`motionSpringUi`) — a settle-time check mirroring the CollapsibleCard
    unfold spring test below."""
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "StatusPill.qml", {"text": "A"})
    try:
        assert _errs(component) == []
        _pump(0.3)
        narrow = obj.property("width")

        obj.setProperty("text", "A MUCH LONGER STATUS WORD")
        _pump(0.02)   # not yet settled
        mid = obj.property("width")
        _pump(0.6)
        wide = obj.property("width")

        assert wide > narrow
        # Mid-transition width sits strictly between the two endpoints —
        # proof the change eases rather than jumping instantly.
        assert narrow <= mid < wide
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# Card — the workhorse (kit_spec_v1.md §3 Card row)                            #
# --------------------------------------------------------------------------- #
def test_card_loads_binds_title_subtitle_and_resolves_card_radius():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Card.qml",
                           {"title": "Z-focus", "subtitle": "advanced"})
    try:
        assert _errs(component) == []
        assert obj.property("objectName") == "kitCard"
        assert obj.property("rung") == CARD
        from gui.style import RADIUS
        assert obj.property("radiusPx") == RADIUS["xl"]

        title = obj.findChild(QObject, "cardTitle")
        subtitle = obj.findChild(QObject, "cardSubtitle")
        assert title.property("text") == "Z-focus"
        assert subtitle.property("text") == "advanced"
        assert subtitle.property("visible") is True
    finally:
        obj.deleteLater()
        _pump()


def test_card_bare_title_hides_header_row():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "Card.qml")
    try:
        assert _errs(component) == []
        header = obj.findChild(QObject, "cardHeader")
        assert header.property("visible") is False
    finally:
        obj.deleteLater()
        _pump()


def test_card_body_content_routes_into_card_body():
    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.Card {
        id: card
        objectName: "probeCard"
        title: "Terminal"
        Text { objectName: "probeBodyChild"; text: "child" }
    }
    """, "card_body.qml")
    try:
        assert _errs(component) == []
        child = obj.findChild(QObject, "probeBodyChild")
        assert child is not None
        assert _visual_parent_name(child) == "cardBody"
    finally:
        obj.deleteLater()
        _pump()


def test_card_header_leading_and_trailing_slots():
    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.Card {
        id: card
        objectName: "probeCard2"
        title: "State"
        headerLeadingData: [ Rectangle { objectName: "probeLeading"; width: 8; height: 8 } ]
        headerTrailingData: [ Rectangle { objectName: "probeTrailing2"; width: 8; height: 8 } ]
    }
    """, "card_header_slots.qml")
    try:
        assert _errs(component) == []
        leading = obj.findChild(QObject, "probeLeading")
        trailing = obj.findChild(QObject, "probeTrailing2")
        assert _visual_parent_name(leading) == "cardHeaderLeading"
        assert _visual_parent_name(trailing) == "cardHeaderTrailing"
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# MetricTile (kit) — stale ink-only + unconditional STALE marker              #
# (kit_spec_v1.md §2.6 stale row / §3 MetricTile row, the ratified law)       #
# --------------------------------------------------------------------------- #
def test_kit_metric_tile_loads_with_zero_errors():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        assert obj.property("objectName") == "kitMetricTile"
        assert obj.property("rung") == TILE
    finally:
        obj.deleteLater()
        _pump()


def test_kit_metric_tile_stale_is_ink_only_with_unconditional_marker():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        stale_mark = obj.findChild(QObject, "tileStaleMark")
        assert stale_mark is not None

        obj.setProperty("stale", False)
        _pump(0.02)
        assert obj.property("opacity") == 1.0
        assert stale_mark.property("visible") is False

        obj.setProperty("stale", True)
        obj.setProperty("compact", True)
        _pump(0.05)
        # Surface itself never dims (ink-only law, ruling 2) — same
        # assertion the pre-kit suite pins for gui/qml/MetricTile.qml.
        assert obj.property("opacity") == 1.0
        assert stale_mark.property("visible") is True
        assert stale_mark.property("text") != ""
        # Unconditional: still shows even in compact mode (whose OTHER
        # redundant channel, the caption, is hidden).
        caption = obj.findChild(QObject, "tileCaption")
        assert caption.property("visible") is False
    finally:
        obj.deleteLater()
        _pump()


def test_kit_metric_tile_meter_and_compact_parity():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "MetricTile.qml")
    try:
        assert _errs(component) == []
        meter = obj.findChild(QObject, "tileMeter")
        assert meter.property("visible") is False
        obj.setProperty("meterFraction", 0.5)
        _pump(0.02)
        assert meter.property("visible") is True

        full_height = obj.property("implicitHeight")
        obj.setProperty("compact", True)
        _pump(0.02)
        assert obj.property("implicitHeight") < full_height
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# MetricGrid — layout only (kit_spec_v1.md §3 "(layout)" row)                  #
# --------------------------------------------------------------------------- #
def test_metric_grid_lays_out_tiles_in_columns():
    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.MetricGrid {
        id: mg
        objectName: "probeMG"
        columns: 2
        Kit.MetricTile { objectName: "t1"; title: "A" }
        Kit.MetricTile { objectName: "t2"; title: "B" }
        Kit.MetricTile { objectName: "t3"; title: "C" }
    }
    """, "metric_grid.qml")
    try:
        assert _errs(component) == []
        t1 = obj.findChild(QObject, "t1")
        t2 = obj.findChild(QObject, "t2")
        t3 = obj.findChild(QObject, "t3")
        assert _visual_parent_name(t1) == "kitMetricGridInner"
        # 2 columns: t1/t2 share a row (same y), t3 wraps to the next row.
        assert t1.property("y") == t2.property("y")
        assert t3.property("y") > t1.property("y")
        assert t1.property("x") == t3.property("x")   # both column 0
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# CollapsibleCard — spring unfold (kit_spec_v1.md §3/§5.1)                     #
# --------------------------------------------------------------------------- #
def test_collapsible_card_collapsed_by_default():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "CollapsibleCard.qml", {"title": "Z-focus"})
    try:
        assert _errs(component) == []
        assert obj.property("expanded") is False
        body = obj.findChild(QObject, "collapsibleBody")
        assert body.property("height") == 0
        assert body.property("visible") is False
        toggle = obj.findChild(QObject, "collapsibleToggle")
        assert toggle.property("width") >= 36 and toggle.property("height") >= 36
    finally:
        obj.deleteLater()
        _pump()


def test_collapsible_card_content_routes_into_unfold_host():
    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.CollapsibleCard {
        id: cc
        objectName: "probeCC"
        title: "Z-focus"
        Text { objectName: "probeFormChild"; text: "form"; height: 24 }
    }
    """, "collapsible_card_content.qml")
    try:
        assert _errs(component) == []
        child = obj.findChild(QObject, "probeFormChild")
        assert _visual_parent_name(child) == "collapsibleBody"
    finally:
        obj.deleteLater()
        _pump()


def test_collapsible_card_spring_unfolds_over_real_time():
    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.CollapsibleCard {
        id: cc
        objectName: "probeCC2"
        title: "Z-focus"
        Text { text: "form"; height: 30 }
    }
    """, "collapsible_card_spring.qml")
    try:
        assert _errs(component) == []
        body = obj.findChild(QObject, "collapsibleBody")
        cc = obj.findChild(QObject, "probeCC2")
        assert body.property("height") == 0

        cc.setProperty("expanded", True)
        _pump(0.02)
        mid = body.property("height")
        _pump(0.6)
        settled = body.property("height")

        assert 0 <= mid < settled
        assert abs(settled - 30) < 1.0
        assert body.property("visible") is True

        cc.setProperty("expanded", False)
        _pump(0.6)
        assert abs(body.property("height")) < 1.0
        assert body.property("visible") is False
    finally:
        obj.deleteLater()
        _pump()


def test_collapsible_card_reduced_motion_snaps(monkeypatch):
    from gui import app_settings
    monkeypatch.setattr(app_settings, "motion_enabled", lambda store=None: False)
    from gui import qml_theme
    qml_theme.set_theme_mode(qml_theme.current_mode())  # re-push Theme.changed

    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.CollapsibleCard {
        id: cc
        objectName: "probeCC3"
        title: "Z-focus"
        Text { text: "form"; height: 30 }
    }
    """, "collapsible_card_reduced_motion.qml")
    try:
        assert _errs(component) == []
        body = obj.findChild(QObject, "collapsibleBody")
        cc = obj.findChild(QObject, "probeCC3")
        cc.setProperty("expanded", True)
        _pump(0.02)   # a live spring would still be far from settled here
        assert abs(body.property("height") - 30) < 1.0
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# ActionBar — frame + reserved holes, never buttons (kit_spec_v1.md §3;       #
# u2_hero_plan.md §2 U2.2/U2.5)                                                #
# --------------------------------------------------------------------------- #
def test_action_bar_is_shelf_rung_frame_with_reserved_holes():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "ActionBar.qml")
    try:
        assert _errs(component) == []
        assert obj.property("objectName") == "kitActionBar"
        assert obj.property("rung") == SHELF

        holes = {
            "actionBarSecondaryHole": 36,
            "actionBarPrimaryHole": 36,
            "actionBarMotionHole": 44,     # motion class hit-target floor
            "actionBarDangerHole": 44,     # danger class hit-target floor
        }
        for name, floor in holes.items():
            item = obj.findChild(QObject, name)
            assert item is not None, name
            assert item.property("width") >= floor, name
            assert item.property("height") >= floor, name
            # A hole is a plain transparent Item — never a button/Rectangle
            # of its own (the kit draws frames, never command content).
            assert item.property("color") is None
    finally:
        obj.deleteLater()
        _pump()


def test_action_bar_danger_hole_sits_apart_from_the_rest():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "ActionBar.qml")
    try:
        assert _errs(component) == []
        obj.setProperty("width", 500)
        _pump(0.02)
        danger = obj.findChild(QObject, "actionBarDangerHole")
        motion = obj.findChild(QObject, "actionBarMotionHole")
        assert danger.property("x") > motion.property("x")
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# EmptyState (+error) — kit_spec_v1.md §3 EmptyState row                       #
# --------------------------------------------------------------------------- #
def test_empty_state_default_variant():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "EmptyState.qml",
                           {"title": "No run loaded", "hint": "Start a scan to see data"})
    try:
        assert _errs(component) == []
        title = obj.findChild(QObject, "emptyStateTitle")
        hint = obj.findChild(QObject, "emptyStateHint")
        glyph = obj.findChild(QObject, "emptyStateGlyph")
        reason = obj.findChild(QObject, "emptyStateReason")
        assert title.property("text") == "No run loaded"
        assert hint.property("visible") is True
        assert glyph.property("visible") is False
        assert reason.property("visible") is False
    finally:
        obj.deleteLater()
        _pump()


def test_empty_state_error_variant_glyph_word_colour():
    """Error variant redundant channels: glyph (shape) + word (title text,
    unconditional) + colour (`error` token on both) — never colour alone."""
    from gui.style import palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "EmptyState.qml", {
        "title": "Connect failed", "variant": "error", "reason": "driver timeout",
    })
    try:
        assert _errs(component) == []
        title = obj.findChild(QObject, "emptyStateTitle")
        glyph = obj.findChild(QObject, "emptyStateGlyph")
        reason = obj.findChild(QObject, "emptyStateReason")
        assert glyph.property("visible") is True
        assert title.property("text") == "Connect failed"
        assert _color_name(title, "color") == palette("light")["error"].lower()
        assert _color_name(glyph, "color") == palette("light")["error"].lower()
        assert reason.property("visible") is True
        assert reason.property("text") == "driver timeout"
    finally:
        obj.deleteLater()
        _pump()


def test_empty_state_entrance_crossfade_reaches_full_opacity():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "EmptyState.qml", {"title": "x"})
    try:
        assert _errs(component) == []
        _pump(0.3)
        assert obj.property("opacity") == 1.0
    finally:
        obj.deleteLater()
        _pump()


def test_empty_state_retry_slot_routes_content():
    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.EmptyState {
        id: es
        objectName: "probeES"
        title: "Connect failed"
        variant: "error"
        retrySlotData: [ Rectangle { objectName: "probeRetry"; width: 10; height: 10 } ]
    }
    """, "empty_state_retry.qml")
    try:
        assert _errs(component) == []
        retry = obj.findChild(QObject, "probeRetry")
        assert retry is not None
        assert _visual_parent_name(retry) == "emptyStateRetrySlot"
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# FormRow — caption over a control (kit_spec_v1.md §3 "(typography)" row)      #
# --------------------------------------------------------------------------- #
def test_form_row_caption_and_control_content():
    engine = _engine()
    component, obj = _load_wrapper(engine, """
    Kit.FormRow {
        id: fr
        objectName: "probeFR"
        caption: "Z step"
        Rectangle { objectName: "probeCtl"; width: 80; height: 24 }
    }
    """, "form_row.qml")
    try:
        assert _errs(component) == []
        caption = obj.findChild(QObject, "formRowCaption")
        assert caption.property("text") == "Z step"
        ctl = obj.findChild(QObject, "probeCtl")
        assert ctl is not None
        assert _visual_parent_name(ctl) == "formRowControl"
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# FigureCard — frame + published holeRect, never content into the hole        #
# (kit_spec_v1.md §3 FigureCard row; u2_hero_plan.md §1.3 point 3)             #
# --------------------------------------------------------------------------- #
def test_figure_card_publishes_hole_rect_and_edge_shade():
    from gui.style import palette

    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "FigureCard.qml",
                           {"title": "Map", "holeHeight": 200})
    try:
        assert _errs(component) == []
        assert obj.property("rung") == CARD
        hole = obj.findChild(QObject, "figureCardHole")
        assert hole is not None
        assert hole.property("height") == 200

        rect = obj.property("holeRect")
        assert rect.width() == hole.property("width")
        assert rect.height() == 200

        edge = obj.findChild(QObject, "figureCardHoleEdgeShade")
        assert _color_name(edge, "color") == palette("light")["edge_shade"].lower()
    finally:
        obj.deleteLater()
        _pump()


def test_figure_card_hole_rect_updates_on_resize():
    engine = _engine()
    component, obj = _load(engine, _KIT_DIR / "FigureCard.qml", {"title": "Map"})
    try:
        assert _errs(component) == []
        obj.setProperty("width", 500)
        _pump(0.02)
        rect1 = obj.property("holeRect")
        obj.setProperty("width", 700)
        _pump(0.02)
        rect2 = obj.property("holeRect")
        assert rect2.width() != rect1.width()
        assert abs(rect2.width() - (rect1.width() + 200)) < 1.0
    finally:
        obj.deleteLater()
        _pump()


# --------------------------------------------------------------------------- #
# Inline-hex guard sanity — the kit QML glob (tests/test_no_inline_hex_gui.py) #
# already covers every file under gui/qml/kit/*.qml generically; this test    #
# just pins that this beat's ten new files are actually on disk there (a      #
# glob path regression would otherwise silently stop covering them).          #
# --------------------------------------------------------------------------- #
def test_all_new_components_present_on_disk():
    expected = {
        "PanelHeader.qml", "StatusPill.qml", "Card.qml", "MetricTile.qml",
        "MetricGrid.qml", "CollapsibleCard.qml", "ActionBar.qml",
        "EmptyState.qml", "FormRow.qml", "FigureCard.qml",
    }
    on_disk = {p.name for p in _KIT_DIR.glob("*.qml")}
    assert expected <= on_disk


# --------------------------------------------------------------------------- #
# Standing panel rule: headless construction + theme-switch smoke, for every   #
# new component in one pass (each resolves colour ONLY through Theme.*, so a   #
# live toggle needs no per-component refresh_theme() — NOTIFY does the work).  #
# --------------------------------------------------------------------------- #
def test_headless_construction_and_theme_switch_smoke_all_new_components():
    from gui import qml_theme
    from gui.style import palette

    engine = _engine()
    loaded = []   # (name, component, obj) — the component MUST stay
    # referenced alongside its created object: dropping the last Python
    # reference to the QQmlComponent that created an item can cascade-delete
    # the item itself (a real PySide6/QQmlComponent lifetime gotcha, hit
    # while writing this test), independent of any separate reference kept
    # to the created object alone.
    try:
        for name, props in (
            ("PanelHeader.qml", {"eyebrow": "e", "title": "t"}),
            ("StatusPill.qml", {"text": "X", "state": "good"}),
            ("Card.qml", {"title": "t", "subtitle": "s"}),
            ("MetricTile.qml", {"title": "t", "value": "1"}),
            ("MetricGrid.qml", {}),
            ("CollapsibleCard.qml", {"title": "t"}),
            ("ActionBar.qml", {}),
            ("EmptyState.qml", {"title": "t", "variant": "error", "reason": "r"}),
            ("FormRow.qml", {"caption": "c"}),
            ("FigureCard.qml", {"title": "t"}),
        ):
            component, obj = _load(engine, _KIT_DIR / name, props)
            assert _errs(component) == [], name
            assert obj is not None, name
            loaded.append((name, component, obj))

        by_name = {name: obj for name, _component, obj in loaded}
        assert _color_name(by_name["Card.qml"].findChild(QObject, "cardTitle"), "color") \
            == palette("light")["text"].lower()
        assert _color_name(by_name["StatusPill.qml"].findChild(QObject, "statusPillGlyph"),
                            "color") == palette("light")["good"].lower()
        assert _color_name(by_name["EmptyState.qml"].findChild(QObject, "emptyStateTitle"),
                            "color") == palette("light")["error"].lower()

        qml_theme.set_theme_mode("dark")
        _pump(0.3)   # settle the ColorAnimation Behaviors (Theme.transitionMs)

        assert _color_name(by_name["Card.qml"].findChild(QObject, "cardTitle"), "color") \
            == palette("dark")["text"].lower()
        assert _color_name(by_name["StatusPill.qml"].findChild(QObject, "statusPillGlyph"),
                            "color") == palette("dark")["good"].lower()
        assert _color_name(by_name["EmptyState.qml"].findChild(QObject, "emptyStateTitle"),
                            "color") == palette("dark")["error"].lower()
        assert _color_name(by_name["StatusPill.qml"].findChild(QObject, "statusPillChipFill"),
                            "color") == palette("dark")["chip"].lower()

        qml_theme.set_theme_mode("light")
        _pump(0.3)
        assert _color_name(by_name["Card.qml"].findChild(QObject, "cardTitle"), "color") \
            == palette("light")["text"].lower()
    finally:
        for _name, _component, obj in loaded:
            obj.deleteLater()
        _pump()
