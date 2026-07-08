"""Small shared status/readout/button widgets for the Qt GUI.

These helpers intentionally stay thin: they reuse ``gui.style`` QSS hooks so
panels get consistent status chips, lamp dots, readout cells, and short button
feedback without each panel owning its own inline styles.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gui.style import repolish, set_chip_state


_STATE_ALIASES = {
    "connected": "good",
    "ok": "good",
    "ready": "good",
    "saved": "good",
    "off": "good",
    "disconnected": "neutral",
    "unknown": "neutral",
    "idle": "neutral",
    "invalid": "crit",
    "error": "crit",
    "alarm": "crit",
    "compliance": "crit",
    "warning": "warn",
    "warn": "warn",
    "running": "busy",
    "busy": "busy",
    "live": "busy",
    "armed": "armed",
    "on": "armed",
    "sim": "simulated",
    "simulation": "simulated",
}


def normalize_state(state: str | None) -> str:
    """Return the compact visual state used by QSS selectors."""
    key = str(state or "neutral").strip().lower()
    return _STATE_ALIASES.get(key, key)


class StatusChip(QLabel):
    """Compact pill label driven by the shared ``statusChip`` QSS hook."""

    def __init__(
        self,
        text: str = "",
        state: str = "neutral",
        parent: QWidget | None = None,
        min_width: int | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("statusChip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if min_width is not None:
            self.setMinimumWidth(min_width)
        self.set_status(text, state)

    def set_status(
        self,
        text: str | None = None,
        state: str | None = None,
        tooltip: str | None = None,
    ) -> None:
        if text is not None:
            self.setText(text)
        if tooltip is not None:
            self.setToolTip(tooltip)
        set_chip_state(self, normalize_state(state))


class StatusLamp(QFrame):
    """Tiny dot indicator that shares the same state language as StatusChip."""

    def __init__(self, state: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusLamp")
        self.setFixedSize(9, 9)
        self.set_state(state)

    def set_state(self, state: str | None) -> None:
        self.setProperty("state", normalize_state(state))
        repolish(self)


class StatusPill(QFrame):
    """Lamp + label pill, useful for device status strips and legends."""

    def __init__(
        self,
        text: str,
        state: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statusPill")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 2, 10, 2)
        lay.setSpacing(6)
        self._lamp = StatusLamp(state)
        self._label = QLabel(text)
        self._label.setObjectName("statusPillText")
        lay.addWidget(self._lamp)
        lay.addWidget(self._label)
        self.set_status(text, state)

    def set_status(
        self,
        text: str | None = None,
        state: str | None = None,
        tooltip: str | None = None,
    ) -> None:
        visual = normalize_state(state)
        if text is not None:
            self._label.setText(text)
        if tooltip is not None:
            self.setToolTip(tooltip)
        self.setProperty("state", visual)
        self._lamp.set_state(visual)
        repolish(self)


class ReadoutCell(QFrame):
    """Small fixed visual readout with title and monospace value."""

    def __init__(
        self,
        title: str,
        value: str = "-",
        parent: QWidget | None = None,
        min_width: int = 96,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("readoutCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(min_width)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 5, 10, 6)
        lay.setSpacing(1)
        self._title = QLabel(title.upper())
        self._title.setObjectName("readoutCellTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value = QLabel(value)
        self._value.setObjectName("readoutCellValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._title)
        lay.addWidget(self._value)
        self._state = "normal"

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def value(self) -> str:
        return self._value.text()

    def set_state(self, state: str | None) -> None:
        """Tri-state tone hook for the value text (e.g. a bench overheat
        cue) — the tokenized replacement for hand-rolling
        ``label.setStyleSheet(f"#readoutCellValue {{ color: {WARN_RED} }}")``
        per call site (see ``gui/camera_panel.py``'s temperature readout,
        which this generalises for future migration).

        Typical values are ``{"normal", "good", "warn", "crit"}``, driving
        the ``QLabel#readoutCellValue[state=...]`` QSS hook in
        ``gui/style.py``. ``gui.panel_kit.MetricTile`` (built on this class)
        reuses the exact same hook with ``{"normal", "warn", "armed"}``
        instead — any state string without a matching QSS rule simply falls
        through to the default accent colour, the same graceful-unknown
        idiom ``gui.style.set_chip_state`` already uses for ``StatusChip``.
        """
        key = str(state or "normal").strip().lower()
        self._state = key
        self._value.setProperty("state", "" if key == "normal" else key)
        repolish(self._value)

    def state(self) -> str:
        return self._state


def add_chips(layout: QHBoxLayout, chips: Iterable[QWidget], stretch: bool = True) -> None:
    """Add chips to an existing horizontal layout with an optional tail stretch."""
    for chip in chips:
        layout.addWidget(chip)
    if stretch:
        layout.addStretch(1)


def set_button_busy(
    button: QPushButton,
    busy: bool,
    busy_text: str | None = None,
    *,
    disable: bool = True,
) -> None:
    """Show a button-level busy state and restore its idle text afterward."""
    if busy:
        if not button.property("_ui_busy"):
            button.setProperty("_ui_idle_text", button.text())
        button.setProperty("_ui_busy", True)
        button.setProperty("state", "busy")
        if busy_text:
            button.setText(busy_text)
        if disable:
            button.setEnabled(False)
    else:
        idle = button.property("_ui_idle_text")
        if isinstance(idle, str):
            button.setText(idle)
        button.setProperty("_ui_busy", False)
        button.setProperty("state", "")
        if disable:
            button.setEnabled(True)
    repolish(button)


def flash_button(
    button: QPushButton,
    state: str = "good",
    text: str | None = None,
    timeout_ms: int = 900,
) -> None:
    """Briefly mark a command button as successful/warning/error."""
    if button.property("_ui_busy"):
        return
    old_text = button.text()
    old_state = button.property("state") or ""
    button.setProperty("state", normalize_state(state))
    if text:
        button.setText(text)
    repolish(button)

    def _restore() -> None:
        if button.property("_ui_busy"):
            return
        button.setProperty("state", old_state)
        button.setText(old_text)
        repolish(button)

    QTimer.singleShot(timeout_ms, _restore)


def set_button_icon(button: QPushButton, icon_name: str, color: str | None = None) -> None:
    """Attach a qtawesome icon when available; silently keep text-only fallback."""
    try:
        import qtawesome as qta
        icon = qta.icon(icon_name, color=color) if color else qta.icon(icon_name)
    except Exception:
        return
    button.setIcon(icon)
