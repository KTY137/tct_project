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
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        # Inherit the cockpit's window opacity (theme/window_opacity, clamped to
        # the 0.80 safety floor): a torn-off panel is part of the same cockpit,
        # so it must not float as an opaque slab over a translucent shell.
        self.setWindowOpacity(style.get_window_opacity())
        self.setCentralWidget(content)
        # Reparenting hides a widget in Qt — show it again or the window is blank.
        content.show()

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
        btn.clicked.connect(lambda: self.detach(self.currentIndex()))
        self.setCornerWidget(btn, Qt.Corner.TopRightCorner)

    # -- detach / redock ------------------------------------------------- #

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
