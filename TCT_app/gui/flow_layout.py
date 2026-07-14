"""A wrapping (flow) layout — items that do not fit on a row move to the next
row instead of being clipped.

WHY THIS EXISTS (safety, not cosmetics). The system ribbon used to live in a
``QScrollArea`` with a fixed 54 px height, vertical scrollbar off and the
horizontal policy left at Qt's default ``AsNeeded``. At the shipped default
window width the ribbon's content is wider than the viewport, so the right-hand
groups — including **MOTION**, the motor/homing state chip, the single most
safety-relevant item in the strip — were cut off at the right edge with no
usable affordance that anything existed off-screen (the themed scrollbar is a
3 px translucent sliver on a 54 px strip; the on-screen audit
``artifacts_claude/ui_onscreen_20260713T202649Z`` shows the chip simply gone).

A status strip that can silently hide a hazard chip is a lie about the machine
(design law 7). Scrolling is the wrong primitive for it: the operator never
scrolls a status readout, they GLANCE at it. So the ribbon wraps instead — it
grows a second row on a narrow window and every chip stays on screen, always.

Standard Qt "flow layout" contract (``QLayout`` + ``heightForWidth``); the only
non-boilerplate parts are documented inline. Deliberately dependency-free and
widget-agnostic: it is a layout, not a panel, so it carries no tokens/colours
and needs no ``refresh_theme``.
"""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    """Left-to-right layout that wraps onto a new row when it runs out of width.

    ``h_spacing``/``v_spacing`` default to the layout's ``spacing()`` so a caller
    can keep using ``setSpacing()``; pass them explicitly for a different rhythm
    between columns and rows.
    """

    def __init__(self, parent=None, margins: QMargins | None = None,
                 h_spacing: int = -1, v_spacing: int = -1) -> None:
        super().__init__(parent)
        self._items: list = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        if margins is not None:
            self.setContentsMargins(margins)

    # -- QLayout plumbing ------------------------------------------------- #

    def addItem(self, item) -> None:            # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):               # noqa: N802 (Qt override)
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):               # noqa: N802 (Qt override)
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):              # noqa: N802 (Qt override)
        # The strip must never demand extra width/height from the window; it
        # takes what it is given and wraps to fit.
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:        # noqa: N802 (Qt override)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt override)
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt override)
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:                # noqa: N802 (Qt override)
        return self.minimumSize()

    def minimumSize(self) -> QSize:             # noqa: N802 (Qt override)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    # -- spacing ---------------------------------------------------------- #

    def _spacing(self, explicit: int, pm) -> int:
        if explicit >= 0:
            return explicit
        parent = self.parent()
        if parent is None:
            return 0
        if parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        return self.spacing()

    def horizontal_spacing(self) -> int:
        from PySide6.QtWidgets import QStyle
        return self._spacing(self._h_space, QStyle.PM_LayoutHorizontalSpacing)

    def vertical_spacing(self) -> int:
        from PySide6.QtWidgets import QStyle
        return self._spacing(self._v_space, QStyle.PM_LayoutVerticalSpacing)

    # -- the wrap itself -------------------------------------------------- #

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        """Place every item, wrapping at *rect*'s right edge; return the total
        height consumed (which is what ``heightForWidth`` reports)."""
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = effective.x(), effective.y()
        row_height = 0
        h_space = self.horizontal_spacing()
        v_space = self.vertical_spacing()

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + h_space
            if next_x - h_space > effective.right() and row_height > 0:
                # Wrap: this item does not fit on the current row.
                x = effective.x()
                y = y + row_height + v_space
                next_x = x + hint.width() + h_space
                row_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            row_height = max(row_height, hint.height())

        return y + row_height - rect.y() + m.bottom()


def make_wrapping_strip(widget, *, margins: QMargins, spacing: int) -> FlowLayout:
    """Install a :class:`FlowLayout` on *widget* and set the size policy a
    wrapping strip needs (``heightForWidth`` is only honoured when the widget's
    own size policy advertises it — without this the strip keeps its one-row
    height hint and the wrapped rows are clipped, i.e. exactly the bug this
    module exists to remove)."""
    layout = FlowLayout(widget, margins=margins,
                        h_spacing=spacing, v_spacing=spacing)
    policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    policy.setHeightForWidth(True)
    widget.setSizePolicy(policy)
    return layout
