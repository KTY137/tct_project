"""Reusable panel-composition helpers — the "next level" design pass (M2.4).

These encode, as thin Qt wrappers, the calm card-based instrument aesthetic
prototyped in ``artifacts_claude/scan_planner_preview_claude.html`` and first
built by hand in ``gui/planner_panel.py`` (titled cards with an eyebrow
header, instrument-style readouts, axis-rail accents). ``gui/planner_panel.py``
is left untouched — it already speaks this language — but every *other* panel
had to re-derive the same header/spacing/readout patterns by eye. This module
gives them one shared vocabulary instead.

Design rules (matching ``gui/style.py`` and every existing panel):
  * Thin wrappers over Qt + ``gui.style`` tokens / ``gui.status_widgets``
    widgets — no new dependencies, no parallel styling system.
  * Both themes.  Anything that bakes a colour (axis rail) at construction
    time exposes a way to re-resolve it after a live theme switch — the same
    ``refresh_theme()`` idiom ``gui/motor_panel.py`` and ``gui/bias_panel.py``
    already use; see ``axis_rail_css``.
  * Structural chrome (card surface, header divider, spacing) lives in
    ``gui/style.py`` QSS (``QFrame#cardHeader``, ``QLabel#cardTitle``,
    ``QLabel#cardSubtitle``, the pre-existing ``QFrame#cardPane``); this
    module only assembles widgets against those hooks.
"""
from __future__ import annotations

from collections.abc import Iterable

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLayout,
    QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from gui.status_widgets import ReadoutCell, StatusLamp
from gui.style import (
    FONT_BODY_PX, FONT_LG, FONT_PANEL_TITLE_PX, PLOT_BG, SPACE_LG,
    SPACE_SM, SPACE_XS, WEIGHT_BODY, WEIGHT_PANEL_TITLE, axis_color, palette,
    repolish,
)

# Default Card body padding — the v4 artifact's own card padding (`.card`
# 17px / `.pbody` 15px), and byte-identical to the QGroupBox QSS padding in
# gui/style.py, so a Card and a QGroupBox sitting side by side share one
# breathing rhythm (round-2 composition pass: "recipes, not boxes").
# (left, top, right, bottom).
CARD_MARGINS = (SPACE_LG + 1, SPACE_LG - 1, SPACE_LG + 1, SPACE_LG - 1)

__all__ = [
    "Card",
    "eyebrow_title",
    "panel_header",
    "section_header",
    "readout_cell",
    "form_row",
    "axis_rail_css",
    "FigureCard",
    "MetricTile",
    "MetricGrid",
    "ActionBar",
    "CheckableCard",
    "CollapsibleCard",
    "SegmentedControl",
    "EmptyState",
]


# --------------------------------------------------------------------------- #
# Axis-rail colour plumbing                                                   #
# --------------------------------------------------------------------------- #

def axis_rail_css(
    axis: str, theme_mode: str, *,
    selector: str = "*", side: str = "left", width: int = 3,
) -> str:
    """QSS fragment tinting *selector*'s ``border-{side}`` with the axis-rail
    colour for *axis* (bias/z/x/y/laser/delay/hazard — see
    ``gui.style.AXIS_RAIL``).

    Generalises the ``f"#name {{ border-left: 3px solid {color}; }}"`` idiom
    every existing axis-coloured widget hand-rolls (``MotorPanel``'s jog
    buttons/readouts, ``BiasPanel``'s voltage rail, ``PlannerPanel``'s loop
    rows) into one call. Callers still own ``widget.setStyleSheet(...)`` (an
    instance-level stylesheet cascades on top of the shared objectName's
    app-wide rule — the same instance-per-colour pattern those panels use),
    and should re-call this from their own ``refresh_theme()`` after a light/
    dark switch, since the colour is resolved once at call time, not live.
    """
    color = axis_color(axis, theme_mode)
    return f"{selector} {{ border-{side}: {width}px solid {color}; }}"


# --------------------------------------------------------------------------- #
# Titles / headers                                                            #
# --------------------------------------------------------------------------- #

def eyebrow_title(
    eyebrow: str, title: str, *, title_px: int = FONT_PANEL_TITLE_PX,
) -> QWidget:
    """Small-caps eyebrow caption stacked over a larger title.

    The ``TCT CONTROL · RECIPE`` / ``Scan Routine Planner`` idiom from the
    Planner panel's top bar (and the design-preview's ``.titlewrap``), as a
    reusable widget instead of a hand-built ``QVBoxLayout`` per panel.
    Round-2 type pass: the default title now sits on the §3 panel-title role
    (``FONT_PANEL_TITLE_PX``/``WEIGHT_PANEL_TITLE`` — 18px/650) instead of an
    off-scale 16px/640, so every kit-built panel header matches the Planner's
    reference header without each call site re-picking a size.
    """
    col = QWidget()
    lay = QVBoxLayout(col)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    cap = QLabel(eyebrow.upper())
    cap.setObjectName("eyebrow")
    head = QLabel(title)
    head.setStyleSheet(
        f"font-size: {title_px}px; font-weight: {WEIGHT_PANEL_TITLE};")
    lay.addWidget(cap)
    lay.addWidget(head)
    return col


def panel_header(
    eyebrow: str, title: str, trailing: list[QWidget] | None = None, *,
    mark: str | None = None, theme_mode: str = "light",
) -> QWidget:
    """A panel-level top bar: eyebrow+title (left) + optional trailing
    widgets (right, e.g. status chips or action buttons) — the panel
    equivalent of the design-preview's ``.topbar``.

    Cockpit kit (Phase 0) extension: an optional *mark* — an axis-rail name
    (``gui.style.AXIS_RAIL``, e.g. ``"hazard"``/``"bias"``) rendered as a
    small coloured accent dot ahead of the eyebrow/title block, resolved via
    ``gui.style.axis_color(mark, theme_mode)`` (never a raw hex — rule 1).
    The returned widget exposes ``.mark_label`` (``None`` when no *mark* was
    given) so a panel keeping this header alive across a live theme switch
    can re-tint it, the same "re-resolve on refresh_theme()" idiom every
    axis-rail consumer already follows (see ``gui/motor_panel.py``).
    """
    bar = QWidget()
    row = QHBoxLayout(bar)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(SPACE_SM)
    mark_label: QLabel | None = None
    if mark:
        mark_label = QLabel()
        mark_label.setFixedSize(8, 8)
        color = axis_color(mark, theme_mode)
        mark_label.setStyleSheet(f"background: {color}; border-radius: 4px;")
        row.addWidget(mark_label, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(eyebrow_title(eyebrow, title))
    row.addStretch(1)
    for w in trailing or ():
        row.addWidget(w)
    bar.mark_label = mark_label   # type: ignore[attr-defined]
    return bar


def section_header(title: str, subtitle: str | None = None) -> QWidget:
    """A card-header row: bold title (left) + muted monospace subtitle
    (right) — the design-preview's ``.card-hd`` (``<h2>`` + ``.sub``).

    Returned widget exposes ``.title_label`` / ``.subtitle_label`` (the
    latter ``None`` when no *subtitle* was given) so a caller can update the
    text later without rebuilding the row — e.g. a live channel count.
    Used standalone for an in-card subsection heading, or by :class:`Card`
    to build its own header.
    """
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SPACE_SM)
    title_label = QLabel(title)
    title_label.setObjectName("cardTitle")
    lay.addWidget(title_label)
    lay.addStretch(1)
    subtitle_label: QLabel | None = None
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("cardSubtitle")
        lay.addWidget(subtitle_label)
    row.title_label = title_label          # type: ignore[attr-defined]
    row.subtitle_label = subtitle_label    # type: ignore[attr-defined]
    return row


# --------------------------------------------------------------------------- #
# Card — the titled panel-surface container                                   #
# --------------------------------------------------------------------------- #

class Card(QFrame):
    """A titled panel-surface container: header (title + optional monospace
    subtitle) over a divider, then a body ``QVBoxLayout`` — the design-
    preview's ``.card`` / ``.card-hd`` pattern, built on the existing
    ``cardPane`` QSS surface (``gui/style.py``) so a Card sits visually level
    with every ``QGroupBox`` / other ``cardPane`` frame already in a panel.

    Panels add content via ``card.body`` (a ``QVBoxLayout``) or the
    ``add_widget``/``add_layout`` convenience methods. Pass ``title=None``
    for a bare card (surface + body, no header) — e.g. to wrap a plot that
    already carries its own labelling.
    """

    def __init__(
        self,
        title: str | None = None,
        subtitle: str | None = None,
        *,
        margins: tuple[int, int, int, int] = CARD_MARGINS,
        spacing: int = SPACE_SM,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("cardPane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header: QFrame | None = None
        self._header_layout: QHBoxLayout | None = None
        self._title_label: QLabel | None = None
        self._subtitle_label: QLabel | None = None
        if title:
            header = QFrame()
            header.setObjectName("cardHeader")
            header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            hlay = QHBoxLayout(header)
            # Header inset matches the body's horizontal padding (artifact
            # `.ptitle` 10/15) so title and content share one left edge.
            hlay.setContentsMargins(SPACE_LG + 1, SPACE_SM + 2, SPACE_LG + 1, SPACE_SM)
            hlay.setSpacing(SPACE_SM)
            hdr_row = section_header(title, subtitle)
            hlay.addWidget(hdr_row)
            self._header = header
            self._header_layout = hlay
            self._title_label = hdr_row.title_label      # type: ignore[attr-defined]
            self._subtitle_label = hdr_row.subtitle_label  # type: ignore[attr-defined]
            outer.addWidget(header)

        body_widget = QWidget()
        self.body = QVBoxLayout(body_widget)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)
        outer.addWidget(body_widget, 1)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout: QLayout) -> None:
        self.body.addLayout(layout)

    def set_title(self, text: str) -> None:
        if self._title_label is not None:
            self._title_label.setText(text)

    def set_subtitle(self, text: str) -> None:
        if self._subtitle_label is not None:
            self._subtitle_label.setText(text)

    def add_header_widget(self, widget: QWidget, *, before_title: bool = False) -> None:
        """Insert *widget* into this card's header row — a no-op when the
        card was built without a title (no header row exists).  Cockpit kit
        (Phase 0) extension used by :class:`CheckableCard` to slot an
        enable/disable checkbox into the header, and available to any other
        header-adjacent control (status chip, icon button) instead of a
        one-off header rebuild per caller.

        ``before_title=True`` places it left of the eyebrow/title block
        (the checkbox position); otherwise it's appended after the
        title/subtitle block (right side, e.g. a small header action)."""
        if self._header_layout is None:
            return
        if before_title:
            self._header_layout.insertWidget(0, widget)
        else:
            self._header_layout.addWidget(widget)

    def set_rail(self, axis: str, theme_mode: str, *, width: int = 3) -> None:
        """Tint this card's left edge with an axis-rail colour (see
        :func:`axis_rail_css`) — call again from the panel's own
        ``refresh_theme()`` after a light/dark switch to keep it resolved.

        The selector is scoped via a dynamic ``railAxis`` property so the
        instance stylesheet tints THIS card only: a bare ``#cardPane``
        selector would cascade onto any same-objectName Card nested inside
        (reviewer-verified), double-railing it.  A nested card that rails
        itself sets its own property + sheet, which takes precedence."""
        self.setProperty("railAxis", axis)
        self.setStyleSheet(axis_rail_css(
            axis, theme_mode, selector=f'QFrame#cardPane[railAxis="{axis}"]',
            width=width))


# --------------------------------------------------------------------------- #
# Readouts / form rows                                                        #
# --------------------------------------------------------------------------- #

def readout_cell(title: str, value: str = "—", *, min_width: int = 96) -> ReadoutCell:
    """Small instrument-style readout (title + monospace value) — a thin
    named re-export of ``gui.status_widgets.ReadoutCell`` so panels adopting
    the composition kit can import everything (Card, headers, readouts) from
    one place."""
    return ReadoutCell(title, value, min_width=min_width)


def form_row(caption: str, widget: QWidget, *, axis: str | None = None,
             theme_mode: str = "light") -> QWidget:
    """A caption-over-control column: an eyebrow caption above *widget*,
    optionally axis-tinted — the ``MotorPanel`` Absolute-Move X/Y/Z pattern
    (``_restyle_abs_move_captions``) generalised for reuse.

    Returns the wrapping widget; the caption label is reachable as
    ``returned.caption_label`` for a later ``refresh_theme()`` re-tint.
    """
    col = QWidget()
    lay = QVBoxLayout(col)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    cap = QLabel(caption.upper())
    cap.setObjectName("eyebrow")
    if axis:
        cap.setStyleSheet(f"#eyebrow {{ color: {axis_color(axis, theme_mode)}; }}")
    lay.addWidget(cap)
    lay.addWidget(widget)
    col.caption_label = cap   # type: ignore[attr-defined]
    return col


# --------------------------------------------------------------------------- #
# FigureCard — a Card hosting a pyqtgraph plot/image (cockpit kit, Phase 0)    #
# --------------------------------------------------------------------------- #

class FigureCard(Card):
    """A :class:`Card` that hosts a pyqtgraph plot/image on the fixed-dark
    "instrument screen" canvas (``gui.style.PLOT_BG``/``PLOT_FG``), with a
    tokenized header — cockpit_style_overhaul.md §2's ``FigureCard`` mapping.

    Defaults to building its own ``pyqtgraph.PlotWidget`` (dark background +
    grid pre-wired, the same two calls every existing hot-path plot repeats
    by hand — see ``gui/motor_panel.py``/``gui/scope_panel.py``); pass an
    already-built widget via *figure* for non-PlotWidget content (an image
    ``QLabel``, a ``pg.ImageView``, ...). The hosted widget is reachable as
    ``card.plot``.

    HARD RULE 3 (cockpit_style_overhaul.md §1): the camera view and every
    pyqtgraph plot repaint continuously, so neither this card nor its
    children may ever carry a ``QGraphicsEffect`` (drop shadow / glow /
    animated) — depth here is *static* only (the existing ``cardPane``
    border + the dark canvas step). No ``setGraphicsEffect()`` call exists
    anywhere in this class; a headless test asserts
    ``card.graphicsEffect() is None`` and ``card.plot.graphicsEffect() is
    None``.
    """

    def __init__(
        self,
        title: str | None = None,
        subtitle: str | None = None,
        *,
        figure: QWidget | None = None,
        margins: tuple[int, int, int, int] = CARD_MARGINS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, subtitle, margins=margins, parent=parent)
        if figure is None:
            figure = pg.PlotWidget(background=PLOT_BG)
            figure.showGrid(x=True, y=True, alpha=0.25)
        self.plot = figure
        self.plot.setMinimumHeight(160)
        self.add_widget(self.plot)


# --------------------------------------------------------------------------- #
# MetricTile / MetricGrid — tokenized run-state readouts (cockpit kit)        #
# --------------------------------------------------------------------------- #

class MetricTile(ReadoutCell):
    """A single tokenized label/value tile — the ``MetricGrid`` unit cell,
    built on the ``ReadoutCell``/``readout_cell`` idiom
    (cockpit_style_overhaul.md §2; behaviours below are the cockpit v5 D0
    pass, docs/design/cockpit_design_system.md §3-4).

    ``state`` is one of ``{"normal", "good", "warn", "crit", "armed", "sim"}``
    (the canonical spec semantic set, plus "normal"/quiet-nominal) and drives
    the value INK ONLY through ``ReadoutCell.set_state()``'s
    ``QLabel#readoutCellValue[state=...]`` QSS hook — cockpit v5 dropped the
    previous "armed" full-frame emphasis border: law 1 says state should read
    through value colour, not an added accent side-bar/border (the frame
    itself stays the same quiet card in every state). A small
    :class:`~gui.status_widgets.StatusLamp` ("LED-in-label") sits ahead of
    the title text instead, giving a second, at-a-glance state cue that
    still does not touch the frame's border/background.

    :meth:`set_stale` implements law 4 ("staleness is designed"): a stale
    tile desaturates its ink (a QSS ``stale`` property the value/title/
    caption/frame all key off — see ``gui/style.py``) and shows a caption
    explaining why (never a raw ``--``). Fit/ellipsize (never bleed into a
    neighbour) is inherited from ``ReadoutCell`` itself, which this class
    does not override.
    """

    _VALID_STATES = {"normal", "good", "warn", "crit", "armed", "sim"}
    # LED-in-label colour per tile state — reuses StatusLamp's own state
    # language (gui.status_widgets.normalize_state already treats these as
    # its canonical names, so no extra translation table is needed).
    _LED_STATE = {
        "normal": "neutral", "good": "good", "warn": "warn",
        "crit": "crit", "armed": "armed", "sim": "simulated",
    }

    def __init__(
        self,
        label: str,
        value: str = "-",
        state: str = "normal",
        *,
        min_width: int = 110,
        caption: str = "",
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(label, value, parent=parent, min_width=min_width)
        # Compact variant (spec §3: primary values 24-28 px, "compact
        # 17-20 px") — drives the QSS ``[compact="true"]`` size rule on the
        # value label (gui/style.py FONT_VALUE_COMPACT_PX) instead of an
        # inline font-size, so state/stale ink rules still cascade normally.
        self._compact = bool(compact)
        if self._compact:
            self._value.setProperty("compact", "true")
            repolish(self._value)
        self._led = StatusLamp("neutral")
        self._led.setFixedSize(6, 6)
        self._install_led()
        self._caption = QLabel(caption)
        self._caption.setObjectName("metricTileCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setVisible(bool(caption))
        self.layout().addWidget(self._caption)
        self._stale = False
        self.set_state(state)
        if caption:
            self.set_caption(caption)

    def _install_led(self) -> None:
        """Re-parent the (already-built, by ``ReadoutCell.__init__``) title
        label into a [led][title] head row — the "LED-in-label" look —
        without touching ``ReadoutCell`` itself (every OTHER ``ReadoutCell``
        consumer, e.g. motor/calibration readouts, keeps its plain title;
        this is a ``MetricTile``-only augmentation).

        Layout note (bug fix, batch A): the title label inherits
        ``QSizePolicy.Ignored`` horizontally from ``ReadoutCell`` (the
        anti-overflow rule — its full-text size hint must never inflate the
        tile). An Ignored-policy widget between two stretches is allocated
        ZERO width, which silently blanked every MetricTile title app-wide.
        Give the title the row's leftover width via a stretch factor instead
        (Ignored + stretch fills, exactly like the value label fills the
        VBox) and let its own centred text alignment do the centring; the
        LED reads as a status dot anchored at the row's left edge."""
        outer = self.layout()
        outer.removeWidget(self._title)
        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.setSpacing(SPACE_XS)
        head_lay.addWidget(self._led, 0, Qt.AlignmentFlag.AlignVCenter)
        head_lay.addWidget(self._title, 1)
        outer.insertWidget(0, head)

    def set_state(self, state: str | None) -> None:
        key = str(state or "normal").strip().lower()
        if key not in self._VALID_STATES:
            key = "normal"
        super().set_state(key)
        self._led.set_state(self._LED_STATE.get(key, "neutral"))

    def set_caption(self, text: str) -> None:
        """Set/replace the small body caption under the value (law 3:
        sentence-case prose, never uppercased here)."""
        self._caption.setText(text or "")
        self._caption.setVisible(bool(text))
        self._caption.setProperty("stale", "true" if self._stale else "")
        repolish(self._caption)

    def set_stale(self, stale: bool, caption: str | None = None) -> None:
        """Law 4: a tile with nothing current to say goes stale (dim +
        desaturate, via the QSS ``stale`` property — never a raw ``--``) and
        should carry a *caption* explaining why (e.g. "not connected", "no
        run", "value aged 12s"). Both are independent: passing only
        ``stale`` re-applies the last caption's stale styling; passing a
        *caption* while already stale/live just updates the text."""
        self._stale = bool(stale)
        flag = "true" if self._stale else ""
        self.setProperty("stale", flag)
        repolish(self)
        self._value.setProperty("stale", flag)
        repolish(self._value)
        self._title.setProperty("stale", flag)
        repolish(self._title)
        self._caption.setProperty("stale", flag)
        repolish(self._caption)
        if caption is not None:
            self.set_caption(caption)

    def is_stale(self) -> bool:
        return self._stale

    def is_compact(self) -> bool:
        return self._compact


class MetricGrid(QWidget):
    """A grid arrangement of :class:`MetricTile`\\ s — pure layout, no custom
    painting (cockpit_style_overhaul.md §2: "a grid arrangement, not a new
    widget class with its own painting"). Items may be pre-built
    ``MetricTile``\\ s or ``(label, value)``/``(label, value, state)``
    tuples, built into tiles on the fly.
    """

    def __init__(
        self,
        tiles: Iterable[MetricTile | tuple] | None = None,
        *,
        columns: int = 4,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns = max(1, int(columns))
        self._compact = bool(compact)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(SPACE_SM)
        self._tiles: list[MetricTile] = []
        for spec in tiles or ():
            self.add_tile(spec)

    def add_tile(self, tile: MetricTile | tuple) -> MetricTile:
        """Append *tile* (a built ``MetricTile``, or a ``(label, value)``/
        ``(label, value, state)`` tuple) to the next grid cell. Tuple-built
        tiles inherit this grid's ``compact`` mode (see ``MetricTile``)."""
        if not isinstance(tile, MetricTile):
            label, value, *rest = tile
            state = rest[0] if rest else "normal"
            tile = MetricTile(label, value, state, compact=self._compact)
        idx = len(self._tiles)
        row, col = divmod(idx, self._columns)
        self._grid.addWidget(tile, row, col)
        self._tiles.append(tile)
        return tile

    def tiles(self) -> list[MetricTile]:
        return list(self._tiles)


# --------------------------------------------------------------------------- #
# ActionBar — layout-only primary/secondary/danger button row (cockpit kit)   #
# --------------------------------------------------------------------------- #

class ActionBar(QWidget):
    """A styled row of primary/secondary/motion/danger action buttons
    (cockpit_style_overhaul.md §2; command classes per
    docs/design/cockpit_design_system.md law 2). This class owns *layout*
    only — the colour comes entirely from the existing button ``state``
    property variants in ``gui/style.py``
    (``primary``/``secondary``/``ghost``/``motion``/``danger``), which this
    class assigns; it never defines its own button QSS. Danger sits alone on
    the right, separated from the rest by a stretch, and gets both the
    ``danger`` state variant (byte-identical to ``#dangerBtn``) and the
    ``dangerBtn`` objectName so existing ``#dangerBtn``-keyed lookups/tests
    keep finding it — one danger visual language app-wide (rule 2). *motion*
    (law 2: "Motion commands are amber-gated") sits in the left/primary
    cluster, after *primary* — a motion command (stage move, homing, ...) is
    call-out-worthy but not as extreme as danger, so it does not join danger
    on the right.

    *secondary* accepts a single button or an iterable of buttons. Callers
    still wire ``clicked``/feedback themselves — e.g.
    ``gui.status_widgets.flash_button``/``set_button_busy`` — this class
    only arranges and colours them.
    """

    def __init__(
        self,
        primary: QPushButton | None = None,
        secondary: QPushButton | Iterable[QPushButton] | None = None,
        danger: QPushButton | None = None,
        *,
        motion: QPushButton | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_SM)

        self.secondary: list[QPushButton] = (
            [secondary] if isinstance(secondary, QPushButton)
            else list(secondary or ()))
        self.primary = primary
        self.motion = motion
        self.danger = danger

        for btn in self.secondary:
            btn.setProperty("state", "secondary")
            row.addWidget(btn)
        if primary is not None:
            primary.setProperty("state", "primary")
            row.addWidget(primary)
        if motion is not None:
            motion.setProperty("state", "motion")
            row.addWidget(motion)
        row.addStretch(1)
        if danger is not None:
            danger.setProperty("state", "danger")
            danger.setObjectName("dangerBtn")
            row.addWidget(danger)

        for btn in (*self.secondary, primary, motion, danger):
            if btn is not None:
                repolish(btn)


# --------------------------------------------------------------------------- #
# CheckableCard — a Card whose header checkbox greys its body (cockpit kit)   #
# --------------------------------------------------------------------------- #

class CheckableCard(Card):
    """A :class:`Card` whose header carries an enable/disable checkbox that
    greys out (disables) the body content — cockpit_style_overhaul.md §2's
    "Card + header checkbox" mapping. Unchecking disables the body container
    widget, which Qt cascades to every child automatically (the same
    single-``setEnabled()`` idiom every panel already uses for its own
    busy/motion-widget groups) — no bespoke per-widget muting system.
    """

    toggled = Signal(bool)   # forwards the header checkbox's toggled signal

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        checked: bool = True,
        margins: tuple[int, int, int, int] = CARD_MARGINS,
        spacing: int = SPACE_SM,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, subtitle, margins=margins, spacing=spacing, parent=parent)
        self._checkbox = QCheckBox()
        self._checkbox.setChecked(checked)
        self._checkbox.setToolTip(f"Enable/disable {title}")
        self.add_header_widget(self._checkbox, before_title=True)
        self._body_widget = self.body.parentWidget()
        self._checkbox.toggled.connect(self._on_toggled)
        self._on_toggled(checked)

    def _on_toggled(self, checked: bool) -> None:
        if self._body_widget is not None:
            self._body_widget.setEnabled(checked)
        self.toggled.emit(checked)

    def is_checked(self) -> bool:
        return self._checkbox.isChecked()

    def set_checked(self, checked: bool) -> None:
        self._checkbox.setChecked(checked)


# --------------------------------------------------------------------------- #
# CollapsibleCard — a Card whose header discloses/hides its body (cockpit v5) #
# --------------------------------------------------------------------------- #

class CollapsibleCard(Card):
    """A :class:`Card` with a disclosure toggle in the header that shows or
    hides the body — the design-system §7 "collapsed by default" recipe
    (Scan Viewer's Z-focus card, Bias's "Standalone sweeps (advanced)").

    Unlike :class:`CheckableCard` (whose checkbox *disables* the body — an
    enable/off semantic), collapsing only hides detail: whatever summary the
    caller puts in the header (a status chip, a primary action via
    ``add_header_widget``) stays live and reachable while collapsed, so the
    card still says what it knows and offers its main verb at a glance.

    Pure layout/visibility — no timers, no animation (law 8: nothing
    decorative moves; expansion is an instant relayout).
    """

    expansion_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        expanded: bool = False,
        margins: tuple[int, int, int, int] = CARD_MARGINS,
        spacing: int = SPACE_SM,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, subtitle, margins=margins, spacing=spacing, parent=parent)
        self._toggle = QToolButton()
        self._toggle.setObjectName("collapseToggle")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(bool(expanded))
        self._toggle.setToolTip(f"Show/hide {title} details")
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.add_header_widget(self._toggle, before_title=True)
        self._body_widget = self.body.parentWidget()
        self._toggle.toggled.connect(self._on_toggled)
        if self._body_widget is not None:
            self._body_widget.setVisible(bool(expanded))

    def _on_toggled(self, expanded: bool) -> None:
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if self._body_widget is not None:
            self._body_widget.setVisible(expanded)
        self.expansion_changed.emit(expanded)

    def is_expanded(self) -> bool:
        return self._toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(bool(expanded))


# --------------------------------------------------------------------------- #
# SegmentedControl — exclusive mode switcher on the shared #segmented QSS     #
# --------------------------------------------------------------------------- #

class SegmentedControl(QFrame):
    """An exclusive row of mode buttons styled by the pre-existing
    ``QFrame#segmented`` / ``QPushButton#segBtn`` QSS hooks (``gui/style.py``
    — the jog-step-preset look ``gui/motor_panel.py``/``gui/stage_view.py``
    already hand-roll), generalised for the design-system §7 "segmented
    modes" recipe (Analysis 2D-map/CCE modes, Scope Live/Single/Avg).

    *segments* is an iterable of ``(key, label)`` pairs (or bare label
    strings, in which case the label is its own key). Emits
    ``selection_changed(key)`` and exposes ``current_key()`` /
    ``set_current(key)``. Layout + the shared QSS only — no bespoke painting,
    no new colours.
    """

    selection_changed = Signal(str)

    def __init__(
        self,
        segments: Iterable[str | tuple[str, str]],
        *,
        current: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for seg in segments:
            key, label = (seg, seg) if isinstance(seg, str) else seg
            btn = QPushButton(label)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.toggled.connect(
                lambda on, _key=key: on and self.selection_changed.emit(_key))
            self._group.addButton(btn)
            self._buttons[str(key)] = btn
            lay.addWidget(btn)
        if self._buttons:
            start = str(current) if current in self._buttons else next(iter(self._buttons))
            self._buttons[start].setChecked(True)

    def current_key(self) -> str | None:
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return None

    def set_current(self, key: str) -> None:
        btn = self._buttons.get(str(key))
        if btn is not None:
            btn.setChecked(True)

    def button(self, key: str) -> QPushButton | None:
        return self._buttons.get(str(key))


# --------------------------------------------------------------------------- #
# EmptyState — centred icon/label/hint placeholder (cockpit kit)              #
# --------------------------------------------------------------------------- #

class EmptyState(QWidget):
    """A centred icon + label + hint placeholder — for an unloaded Analysis
    run or a disconnected Camera surface (cockpit_style_overhaul.md §2).

    *icon* is an optional qtawesome name (e.g. ``"fa5s.camera"``); the
    import is optional/best-effort, the same graceful-degrade idiom as
    ``gui.status_widgets.set_button_icon``/``gui/motor_panel.py``'s
    ``_icon()`` — a missing qtawesome install just means no icon, never a
    hard failure. The icon is tinted from ``gui.style.palette(theme_mode)``
    (never a raw hex); call :meth:`refresh_theme` after a live theme switch
    to re-tint it (the same "re-resolve cached colour" idiom every
    axis-rail/instance-styled widget already follows).

    Cockpit v5 D0 (docs/design/cockpit_design_system.md §2's "EmptyState
    error variant" / §6 "Failed connects are designed error states ... not
    message boxes"): pass ``variant="error"`` for a failed-connect/failed-
    load surface — the icon and title tint to the danger token instead of
    the neutral/muted default. *reason* is a second, quiet sentence-case
    line ("WHY" — e.g. the driver's actual exception text), distinct from
    *hint* (a generic caption shown regardless of variant, e.g. "connect a
    device to begin"). *retry_slot* reserves a place for a caller-supplied
    widget (typically a "Retry" QPushButton) — this class only lays it out
    and never wires the click itself: retrying a failed connect is a
    controller/device-manager call, out of a pure-view widget's remit.
    """

    def __init__(
        self,
        icon: str | None,
        label: str,
        hint: str | None = None,
        *,
        variant: str = "default",
        reason: str | None = None,
        retry_slot: QWidget | None = None,
        theme_mode: str = "light",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon
        self._theme_mode = theme_mode
        self._variant = "error" if str(variant).lower() == "error" else "default"

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(SPACE_SM)

        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._icon_label)

        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._label)

        self._hint: QLabel | None = None
        if hint:
            self._hint = QLabel(hint)
            self._hint.setObjectName("cardSubtitle")
            self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._hint.setWordWrap(True)
            lay.addWidget(self._hint)

        self._reason: QLabel | None = None
        if reason:
            self._reason = QLabel(reason)
            self._reason.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._reason.setWordWrap(True)
            lay.addWidget(self._reason)

        self.retry_slot = retry_slot
        if retry_slot is not None:
            lay.addWidget(retry_slot, 0, Qt.AlignmentFlag.AlignCenter)

        self._apply_icon()
        self._apply_variant_ink()

    def _apply_variant_ink(self) -> None:
        """Tint the title (and reason, if present) from the current theme's
        palette — error variant uses the danger token for the title (the
        ONE emphasised line; the reason stays quiet/muted body prose, law 3:
        "Explanations: sentence-case sans", never a second red line)."""
        p = palette(self._theme_mode)
        title_color = p["crit"] if self._variant == "error" else p["text"]
        self._label.setStyleSheet(
            f"font-size: {FONT_LG}px; font-weight: 600; color: {title_color};")
        if self._reason is not None:
            self._reason.setStyleSheet(
                f"color: {p['muted']}; font-size: {FONT_BODY_PX}px; "
                f"font-weight: {WEIGHT_BODY};")

    def set_reason(self, text: str) -> None:
        if self._reason is not None:
            self._reason.setText(text)

    def _apply_icon(self) -> None:
        if not self._icon_name:
            return
        try:
            import qtawesome as qta
            p = palette(self._theme_mode)
            color = p["crit"] if self._variant == "error" else p["muted"]
            self._icon_label.setPixmap(qta.icon(self._icon_name, color=color).pixmap(40, 40))
        except Exception:
            pass

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_hint(self, text: str) -> None:
        if self._hint is not None:
            self._hint.setText(text)

    def refresh_theme(self, mode: str | None = None) -> None:
        if mode:
            self._theme_mode = str(mode)
        self._apply_icon()
        self._apply_variant_ink()
