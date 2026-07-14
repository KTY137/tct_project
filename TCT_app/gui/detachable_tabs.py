"""
A QTabWidget whose tabs can be torn off into their own floating windows
(multi-monitor friendly) and re-docked by closing the window.

Detach: double-click a tab, or click the ⧉ corner button.
Re-dock: close the floating window — the page returns to its original tab slot.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMainWindow, QTabWidget, QToolButton, QWidget

from gui import style


class _DetachedWindow(QMainWindow):
    """Floating host for a single torn-off tab page."""
    closed = Signal(object)   # emits self

    def __init__(self, content: QWidget, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Alpha-capable surface FIRST — before the torn-off page (which may host a
        # GL view or any widget that realizes the native window) is installed. Qt
        # fixes a top-level's surface alpha at creation; miss that and the
        # material attaches with S_OK and composites nothing. No-op unless a
        # material is the active preference. See gui.style.prepare_window_surface.
        style.prepare_window_surface(self)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        # The central widget goes in FIRST, before the backdrop. This ORDER is
        # the whole reason a detached panel showed no glass (2026-07-13, beat
        # G-B1): gui.backdrop._canvas_widgets() must make the QMainWindow's
        # CENTRAL widget translucent too — a QMainWindow's client area is
        # painted by that child, not by the window, so a translucent top-level
        # with an opaque child carries no alpha down to DWM and the material
        # never composites. This constructor used to apply the backdrop while
        # centralWidget() was still None, so the canvas prep silently skipped
        # the one widget that mattered, and the torn-off panel came up opaque
        # while the theme editor (a flat QDialog, which IS its own canvas)
        # showed glass. Never re-order these two.
        self.setCentralWidget(content)
        # Reparenting hides a widget in Qt — show it again or the window is blank.
        content.show()
        # Inherit the cockpit's material + opacity through the ONE entry point
        # (gui.style.reassert_window_backdrop): DWM chain first, then the
        # WS_EX_LAYERED opacity pin — a torn-off panel is part of the same
        # cockpit, and a layered window suppresses the material outright, so a
        # window created while a material is live must NOT be handed the raw
        # stored opacity (which is what the old two-liner here did — the second
        # half of why detached panels had no glass). It also installs the event
        # spine's guard, so this window re-asserts on WinIdChange/Show. A true
        # no-op pre-Win11 22H2 / non-Windows / headless; ships "none" by default.
        style.reassert_window_backdrop(self)

    def closeEvent(self, event) -> None:
        self.closed.emit(self)
        # Hand the page back to the tab widget before we are destroyed so the
        # central widget isn't deleted with us.
        self.takeCentralWidget()
        super().closeEvent(event)


class DetachableTabWidget(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # title -> (window, content, original_index)
        self._detached: dict[str, tuple[_DetachedWindow, QWidget, int]] = {}
        self.tabBarDoubleClicked.connect(self._on_double_click)

        btn = QToolButton()
        btn.setObjectName("detachTabButton")
        btn.setText("⧉")
        btn.setAutoRaise(True)
        btn.setToolTip("Detach the current tab into its own window "
                       "(double-click a tab does the same)")
        # A bound method, never ``lambda: self.detach(self.currentIndex())``:
        # the corner button is a CHILD of this tab widget, and PySide6 stores a
        # lambda slot strongly in the child's C++ connection list — closing a
        # cycle (tabs -> button -> connection -> closure -> tabs) that gc cannot
        # see, so the tab widget and every page in it becomes immortal. Bound
        # methods are held weakly. See tests/test_no_immortal_panels.py.
        btn.clicked.connect(self._detach_current)
        self.setCornerWidget(btn, Qt.Corner.TopRightCorner)

    # -- detach / redock ------------------------------------------------- #

    def _detach_current(self) -> None:
        """Detach the currently-visible tab (the ⧉ corner button)."""
        self.detach(self.currentIndex())

    def _on_double_click(self, index: int) -> None:
        if index >= 0:
            self.detach(index)

    def detach(self, index: int) -> None:
        if index < 0 or index >= self.count():
            return
        title = self.tabText(index)
        content = self.widget(index)
        self.removeTab(index)
        win = _DetachedWindow(content, title, self.window())
        win.closed.connect(self._on_detached_closed)
        win.resize(960, 680)
        win.show()
        self._detached[title] = (win, content, index)

    def _on_detached_closed(self, win: _DetachedWindow) -> None:
        for title, (w, content, index) in list(self._detached.items()):
            if w is win:
                del self._detached[title]
                idx = min(index, self.count())
                self.insertTab(idx, content, title)
                self.setCurrentIndex(idx)
                break

    # -- helpers for persistence / teardown ------------------------------ #

    def detach_by_title(self, title: str) -> bool:
        for i in range(self.count()):
            if self.tabText(i) == title:
                self.detach(i)
                return True
        return False

    def detached_titles(self) -> list[str]:
        return list(self._detached.keys())

    def redock_all(self) -> None:
        """Close every floating window so all pages return to tabs."""
        for _title, (win, _content, _index) in list(self._detached.items()):
            win.close()
