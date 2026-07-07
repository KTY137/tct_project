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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLayout, QLabel, QVBoxLayout, QWidget,
)

from gui.status_widgets import ReadoutCell
from gui.style import SPACE_MD, SPACE_SM, axis_color

__all__ = [
    "Card",
    "eyebrow_title",
    "panel_header",
    "section_header",
    "readout_cell",
    "form_row",
    "axis_rail_css",
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

def eyebrow_title(eyebrow: str, title: str, *, title_px: int = 16) -> QWidget:
    """Small-caps eyebrow caption stacked over a larger title.

    The ``TCT CONTROL · RECIPE`` / ``Scan Routine Planner`` idiom from the
    Planner panel's top bar (and the design-preview's ``.titlewrap``), as a
    reusable widget instead of a hand-built ``QVBoxLayout`` per panel.
    """
    col = QWidget()
    lay = QVBoxLayout(col)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    cap = QLabel(eyebrow.upper())
    cap.setObjectName("eyebrow")
    head = QLabel(title)
    head.setStyleSheet(f"font-size: {title_px}px; font-weight: 640;")
    lay.addWidget(cap)
    lay.addWidget(head)
    return col


def panel_header(eyebrow: str, title: str, trailing: list[QWidget] | None = None) -> QWidget:
    """A panel-level top bar: eyebrow+title (left) + optional trailing
    widgets (right, e.g. status chips or action buttons) — the panel
    equivalent of the design-preview's ``.topbar``."""
    bar = QWidget()
    row = QHBoxLayout(bar)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(SPACE_SM)
    row.addWidget(eyebrow_title(eyebrow, title))
    row.addStretch(1)
    for w in trailing or ():
        row.addWidget(w)
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
        margins: tuple[int, int, int, int] = (SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD),
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
        self._title_label: QLabel | None = None
        self._subtitle_label: QLabel | None = None
        if title:
            header = QFrame()
            header.setObjectName("cardHeader")
            header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            hlay = QHBoxLayout(header)
            hlay.setContentsMargins(SPACE_MD, SPACE_SM + 2, SPACE_MD, SPACE_SM)
            hlay.setSpacing(SPACE_SM)
            hdr_row = section_header(title, subtitle)
            hlay.addWidget(hdr_row)
            self._header = header
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
