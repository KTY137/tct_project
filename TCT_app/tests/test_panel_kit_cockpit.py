"""Headless tests for the "TCT Cockpit" kit primitives — Phase 0
(docs/design/cockpit_style_overhaul.md §2/§4). Kit-only: no panel is
migrated in this batch (see tests/test_panel_kit_rollout_batch*.py for the
already-migrated panels), so every check here targets gui/panel_kit.py's
new components and gui/style.py's new tokens directly.

Follows the existing gui test idiom (see test_panel_kit.py /
test_panel_kit_rollout_batch3.py): QT_QPA_PLATFORM=offscreen, a shared
QApplication.instance() helper, no pytest-qt.
"""
from __future__ import annotations

import ast
import inspect
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import gui.panel_kit as panel_kit
from gui.panel_kit import (
    ActionBar,
    Card,
    CheckableCard,
    EmptyState,
    FigureCard,
    MetricGrid,
    MetricTile,
    panel_header,
)
from gui.status_widgets import ReadoutCell
from gui.style import (
    DARK,
    GLOW,
    LIGHT,
    PLOT_GRID,
    PLOT_OVERLAY,
    apply_theme,
    axis_color,
    glow_color,
    palette,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _grab_both_themes(make_widget, *, has_refresh: bool = True) -> None:
    """Build *make_widget()*, render it under light then dark, call
    ``refresh_theme`` if present, and confirm the pixmap is non-empty both
    times — the same idiom every panel_kit_rollout_batch*.py test uses."""
    app = _app()
    apply_theme(app, "light")
    widget = make_widget()
    pm_light = widget.grab()
    assert not pm_light.isNull()

    apply_theme(app, "dark")
    if has_refresh and hasattr(widget, "refresh_theme"):
        widget.refresh_theme("dark")
    pm_dark = widget.grab()
    assert not pm_dark.isNull()

    if has_refresh and hasattr(widget, "refresh_theme"):
        widget.refresh_theme("light")
    apply_theme(app, "light")


# --------------------------------------------------------------------------- #
# gui/style.py — new tokens                                                   #
# --------------------------------------------------------------------------- #

_NEW_PALETTE_KEYS = (
    "canvas", "material", "material_strong", "field",
    "hairline", "hairline_strong", "toplight", "faint",
    "on_accent", "tint", "sim", "error",
    "panel_2", "panel_3", "sunk", "border_strong", "hover", "active",
)


def test_new_layering_tokens_present_in_both_themes():
    for key in _NEW_PALETTE_KEYS:
        assert key in LIGHT and LIGHT[key], key
        assert key in DARK and DARK[key], key
        # Additive: light/dark values differ (real per-theme tokens, not a
        # stray shared placeholder).
        assert LIGHT[key] != DARK[key], key


def test_existing_palette_keys_untouched():
    # Compatibility guarantee: the long-standing public palette keys still
    # exist after the v5 value refresh, so callers using palette()["accent"] /
    # ["bg"] / ["good"] do not break.
    for key in ("accent", "accent_strong", "bg", "panel", "border",
                "text", "muted", "pressed", "disabled_bg",
                "good", "warn", "crit", "amber"):
        assert key in LIGHT and LIGHT[key], key
        assert key in DARK and DARK[key], key


def test_v5_palette_values_match_polish_artifact():
    # Ratified design-system v4 tokens (docs/design/cockpit_design_system.md
    # section 2, sourced verbatim from tct_cockpit_design_v4_final.html). If a
    # future artifact refresh changes these, update spec + here together.
    assert DARK["bg"] == "#0A0D13"
    assert DARK["panel"] == "#121824"
    assert DARK["accent"] == "#5AA9FF"
    assert DARK["good"] == "#3DD68C"
    assert DARK["warn"] == "#FFB84D"
    assert DARK["crit"] == "#FF5A61"

    assert LIGHT["bg"] == "#E9EDF4"
    assert LIGHT["accent"] == "#2A6FE0"
    assert LIGHT["good"] == "#128A63"
    assert LIGHT["warn"] == "#B26F00"
    assert LIGHT["crit"] == "#DE434B"


def test_plot_grid_overlay_tokens_present_both_themes_and_fixed():
    for pal in (LIGHT, DARK):
        assert pal["plot_grid"] == PLOT_GRID
        assert pal["plot_overlay"] == PLOT_OVERLAY


def test_palette_helper_resolves_light_and_dark():
    assert palette("light") is LIGHT
    assert palette("dark") is DARK
    assert palette("anything-else") is LIGHT


def test_static_glow_set_is_not_per_theme():
    for kind in ("accent", "good", "warn", "crit", "armed"):
        assert kind in GLOW
        assert glow_color(kind) == GLOW[kind]
    # Genuinely "static": same call, same value regardless of app theme.
    app = _app()
    apply_theme(app, "light")
    light_val = glow_color("warn")
    apply_theme(app, "dark")
    dark_val = glow_color("warn")
    assert light_val == dark_val
    apply_theme(app, "light")


def test_button_variant_qss_present_for_all_six_states():
    app = _app()
    apply_theme(app, "dark")
    css = app.styleSheet()
    for variant in ("primary", "secondary", "armed", "danger", "ghost", "busy"):
        assert f'state="{variant}"' in css, variant
    apply_theme(app, "light")


def test_danger_state_variant_shares_dangerbtn_selector():
    """rule 2: one danger visual language — state="danger" must be folded
    into literally the same selector as #dangerBtn, not a look-alike rule."""
    app = _app()
    apply_theme(app, "light")
    css = app.styleSheet()
    assert 'QPushButton#dangerBtn, QPushButton[state="danger"]' in css


def test_readout_cell_value_tristate_qss_present():
    app = _app()
    apply_theme(app, "light")
    css = app.styleSheet()
    for state in ("good", "warn", "crit", "armed"):
        assert f'QLabel#readoutCellValue[state="{state}"]' in css


# --------------------------------------------------------------------------- #
# gui/status_widgets.py — ReadoutCell.set_state() (the parity-pass gap)       #
# --------------------------------------------------------------------------- #

def test_readout_cell_set_state_drives_value_property():
    _app()
    cell = ReadoutCell("Temp", "30.0 C")
    assert cell.state() == "normal"
    assert cell._value.property("state") in (None, "")

    cell.set_state("crit")
    assert cell.state() == "crit"
    assert cell._value.property("state") == "crit"

    cell.set_state("warn")
    assert cell._value.property("state") == "warn"

    cell.set_state(None)
    assert cell.state() == "normal"
    assert cell._value.property("state") == ""


# --------------------------------------------------------------------------- #
# panel_header() — accent mark extension                                      #
# --------------------------------------------------------------------------- #

def test_panel_header_mark_uses_axis_color_not_raw_hex():
    _app()
    bar = panel_header("TCT Control", "Scan Viewer", mark="hazard", theme_mode="dark")
    assert bar.mark_label is not None
    color = axis_color("hazard", "dark")
    assert color in bar.mark_label.styleSheet()


def test_panel_header_without_mark_has_none():
    _app()
    bar = panel_header("TCT Control", "Motor Stage")
    assert bar.mark_label is None


# --------------------------------------------------------------------------- #
# Card.add_header_widget()                                                    #
# --------------------------------------------------------------------------- #

def test_card_add_header_widget_inserts_into_header_row():
    _app()
    card = Card("Channels")
    from PySide6.QtWidgets import QCheckBox
    box = QCheckBox()
    card.add_header_widget(box, before_title=True)
    assert card._header_layout.itemAt(0).widget() is box


def test_card_add_header_widget_noop_without_title():
    _app()
    card = Card()
    from PySide6.QtWidgets import QCheckBox
    box = QCheckBox()
    card.add_header_widget(box)   # must not raise
    assert box.parent() is None


# --------------------------------------------------------------------------- #
# FigureCard                                                                   #
# --------------------------------------------------------------------------- #

def test_figure_card_constructs_both_themes():
    _grab_both_themes(lambda: FigureCard("Live map", "x/y raster"), has_refresh=False)


def test_figure_card_builds_default_plot_widget():
    _app()
    import pyqtgraph as pg
    card = FigureCard("Histogram")
    assert isinstance(card.plot, pg.PlotWidget)


def test_figure_card_accepts_custom_figure_widget():
    _app()
    from PySide6.QtWidgets import QLabel
    label = QLabel()
    card = FigureCard("Frame", figure=label)
    assert card.plot is label
    assert label.parent() is not None


def test_figure_card_and_plot_have_no_graphics_effect():
    """HARD RULE 3 — no QGraphicsEffect/glow on the hot path."""
    _app()
    card = FigureCard("Live map")
    assert card.graphicsEffect() is None
    assert card.plot.graphicsEffect() is None


# --------------------------------------------------------------------------- #
# MetricTile / MetricGrid                                                     #
# --------------------------------------------------------------------------- #

def test_metric_tile_constructs_both_themes():
    _grab_both_themes(lambda: MetricTile("Points", "128/400", "armed"), has_refresh=False)


def test_metric_tile_is_a_readout_cell():
    _app()
    tile = MetricTile("ETA", "00:12")
    assert isinstance(tile, ReadoutCell)
    assert tile.value() == "00:12"
    assert tile.state() == "normal"


def test_metric_tile_state_changes_restyle_value_and_border():
    _app()
    tile = MetricTile("Points", "1/10")
    assert tile.styleSheet() == ""

    tile.set_state("warn")
    assert tile.state() == "warn"
    assert tile._value.property("state") == "warn"
    assert tile.styleSheet() == ""   # warn: text colour only, no border emphasis

    tile.set_state("armed")
    assert tile.state() == "armed"
    # Design law 1 (D0): state reads through value ink only — the old armed
    # full-frame emphasis border was removed; no stylesheet for ANY state.
    assert tile.styleSheet() == ""

    tile.set_state("normal")
    assert tile.state() == "normal"
    assert tile.styleSheet() == ""


def test_metric_tile_unknown_state_falls_back_to_normal():
    _app()
    tile = MetricTile("X", "1", "not-a-real-state")
    assert tile.state() == "normal"


def test_metric_grid_lays_out_tiles_and_builds_from_tuples():
    _app()
    grid = MetricGrid([("A", "1"), ("B", "2", "warn"), MetricTile("C", "3")], columns=2)
    tiles = grid.tiles()
    assert len(tiles) == 3
    assert all(isinstance(t, MetricTile) for t in tiles)
    assert tiles[1].state() == "warn"
    # 3 tiles at 2 columns -> rows 0,0 / 0,1 / 1,0
    assert grid._grid.itemAtPosition(0, 0).widget() is tiles[0]
    assert grid._grid.itemAtPosition(0, 1).widget() is tiles[1]
    assert grid._grid.itemAtPosition(1, 0).widget() is tiles[2]


def test_metric_grid_constructs_both_themes():
    _grab_both_themes(
        lambda: MetricGrid([("A", "1"), ("B", "2", "armed")], columns=2),
        has_refresh=False)


def test_metric_tile_title_gets_real_width_next_to_led():
    """Regression (batch A): the LED head row used to sandwich the
    Ignored-size-policy title label between two stretches — a zero-width
    allocation that silently blanked every MetricTile title app-wide. The
    title must end up with real width (and its text intact) once the tile
    has geometry."""
    _app()
    tile = MetricTile("Progress", "0/0")
    tile.resize(160, 70)
    tile.show()
    QApplication.instance().processEvents()
    try:
        assert tile._title.width() > 40
        assert tile._title.text() == "PROGRESS"
    finally:
        tile.hide()


def test_metric_tile_compact_variant_sets_qss_property():
    _app()
    tile = MetricTile("Point", "x=1 y=2 z=3", compact=True)
    assert tile.is_compact()
    assert tile._value.property("compact") == "true"
    # Non-compact tiles carry no property (full 24-28 px hero face).
    plain = MetricTile("Points", "128")
    assert not plain.is_compact()
    assert not plain._value.property("compact")


def test_metric_grid_compact_propagates_to_tuple_tiles():
    _app()
    grid = MetricGrid([("A", "1"), ("B", "2")], columns=2, compact=True)
    assert all(t.is_compact() for t in grid.tiles())


def test_compact_value_qss_rule_present():
    from gui.style import FONT_VALUE_COMPACT_PX, build_qss
    for mode in ("light", "dark"):
        qss = build_qss(palette(mode))
        assert 'QLabel#readoutCellValue[compact="true"]' in qss
        assert f"{FONT_VALUE_COMPACT_PX}px" in qss


# --------------------------------------------------------------------------- #
# CollapsibleCard / SegmentedControl (batch A kit additions)                   #
# --------------------------------------------------------------------------- #

def test_collapsible_card_collapsed_by_default_header_stays_live():
    from gui.panel_kit import CollapsibleCard
    _app()
    card = CollapsibleCard("Z focus", "assist")
    assert not card.is_expanded()
    assert card.body.parentWidget().isHidden()
    # Header widgets (chip/action) stay reachable while collapsed.
    btn = QPushButton("Find focus")
    card.add_header_widget(btn)
    assert btn.parent() is not None

    seen = []
    card.expansion_changed.connect(seen.append)
    card.set_expanded(True)
    assert card.is_expanded()
    assert not card.body.parentWidget().isHidden()
    assert seen == [True]


def test_collapsible_card_constructs_both_themes():
    from gui.panel_kit import CollapsibleCard
    _grab_both_themes(lambda: CollapsibleCard("T", expanded=True), has_refresh=False)


def test_segmented_control_exclusive_selection_and_signal():
    from gui.panel_kit import SegmentedControl
    _app()
    seg = SegmentedControl([("map", "2D map"), ("cce", "CCE vs bias")], current="map")
    assert seg.current_key() == "map"
    seen = []
    seg.selection_changed.connect(seen.append)
    seg.set_current("cce")
    assert seg.current_key() == "cce"
    assert seen == ["cce"]
    # Exclusive: exactly one checked at a time.
    assert not seg.button("map").isChecked()
    assert seg.button("cce").isChecked()
    # Uses the shared #segmented / #segBtn QSS hooks — no bespoke styling.
    assert seg.objectName() == "segmented"
    assert seg.button("map").objectName() == "segBtn"


def test_segmented_control_constructs_both_themes():
    from gui.panel_kit import SegmentedControl
    _grab_both_themes(lambda: SegmentedControl(["A", "B"]), has_refresh=False)


# --------------------------------------------------------------------------- #
# ActionBar                                                                    #
# --------------------------------------------------------------------------- #

def test_action_bar_assigns_variant_states():
    _app()
    primary = QPushButton("Start")
    secondary = [QPushButton("Pause"), QPushButton("Preview")]
    danger = QPushButton("Abort")
    bar = ActionBar(primary=primary, secondary=secondary, danger=danger)

    assert primary.property("state") == "primary"
    assert all(b.property("state") == "secondary" for b in secondary)
    assert danger.property("state") == "danger"
    assert danger.objectName() == "dangerBtn"
    assert bar.layout().count() >= 4   # 2 secondary + primary + stretch + danger


def test_action_bar_works_with_any_subset_of_slots():
    _app()
    danger = QPushButton("STOP")
    bar = ActionBar(danger=danger)   # motor-panel-style: danger-only bar
    assert bar.primary is None
    assert bar.secondary == []
    assert danger.property("state") == "danger"


def test_action_bar_constructs_both_themes():
    def _make():
        return ActionBar(
            primary=QPushButton("Start"),
            secondary=QPushButton("Pause"),
            danger=QPushButton("Abort"),
        )
    _grab_both_themes(_make, has_refresh=False)


# --------------------------------------------------------------------------- #
# CheckableCard                                                               #
# --------------------------------------------------------------------------- #

def test_checkable_card_disables_children_on_uncheck():
    _app()
    card = CheckableCard("Z-focus", checked=True)
    btn = QPushButton("Run")
    card.add_widget(btn)
    assert btn.isEnabled()

    card.set_checked(False)
    assert not card.is_checked()
    assert not btn.isEnabled()

    card.set_checked(True)
    assert btn.isEnabled()


def test_checkable_card_starts_unchecked_when_requested():
    _app()
    card = CheckableCard("Optional stage", checked=False)
    btn = QPushButton("x")
    card.add_widget(btn)
    assert not btn.isEnabled()


def test_checkable_card_emits_toggled_signal():
    _app()
    card = CheckableCard("Z-focus")
    seen = []
    card.toggled.connect(seen.append)
    card.set_checked(False)
    assert seen == [False]


def test_checkable_card_constructs_both_themes():
    def _make():
        card = CheckableCard("Z-focus", checked=True)
        card.add_widget(QPushButton("Run"))
        return card
    _grab_both_themes(_make, has_refresh=False)


# --------------------------------------------------------------------------- #
# EmptyState                                                                   #
# --------------------------------------------------------------------------- #

def test_empty_state_constructs_both_themes_with_refresh():
    _grab_both_themes(
        lambda: EmptyState("fa5s.camera", "No camera connected",
                            "Connect a camera in Device Manager"))


def test_empty_state_without_icon_or_hint():
    _app()
    empty = EmptyState(None, "Nothing loaded")
    empty.refresh_theme("dark")   # must not raise even with no icon
    assert empty._hint is None


def test_empty_state_label_and_hint_setters():
    _app()
    empty = EmptyState("fa5s.chart-line", "No run loaded", "Open a file")
    empty.set_label("Updated label")
    empty.set_hint("Updated hint")
    assert empty._label.text() == "Updated label"
    assert empty._hint.text() == "Updated hint"


# --------------------------------------------------------------------------- #
# Zero inline hex (rule 1) + no QGraphicsEffect anywhere in the kit (rule 3)   #
# --------------------------------------------------------------------------- #

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def test_panel_kit_source_has_zero_inline_hex():
    src = inspect.getsource(panel_kit)
    matches = _HEX_RE.findall(src)
    assert matches == [], f"inline hex literals found in gui/panel_kit.py: {matches}"


def test_panel_kit_never_calls_set_graphics_effect():
    """AST-based (not a substring search) so docstring prose that merely
    *mentions* ``setGraphicsEffect()`` (e.g. this module's own rule-3
    explanations) can't produce a false positive — only an actual call
    expression counts."""
    tree = ast.parse(inspect.getsource(panel_kit))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setGraphicsEffect"
    ]
    assert calls == []
