"""Small shared status/readout/button widgets for the Qt GUI.

These helpers intentionally stay thin: they reuse ``gui.style`` QSS hooks so
panels get consistent status chips, lamp dots, readout cells, and short button
feedback without each panel owning its own inline styles.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from gui.style import repolish, set_chip_state


# cockpit v5 (docs/design/cockpit_design_system.md law 1/6/7) state
# normalization. Every raw device/run string funnels through here into the
# small canonical set the QSS in gui/style.py actually draws
# ({{neutral, disconnected, unknown, good, warn, crit, armed, fault, info,
# busy, simulated}}).
#
# Law 1 ("quiet nominal"): "connected"/"ok"/"ready"/"off" used to resolve to
# "good" (a persistent green light for routine, working-as-intended state) —
# exactly the ISA-101 anti-pattern the spec calls out ("Green is spent
# sparingly; the accent never means good"). They now resolve to "neutral"
# (quiet grey), the same bucket as "idle". "saved" stays "good": a one-off
# confirmation flash (gui.status_widgets.flash_button) for an actual
# accomplishment is the sparing, legitimate use the law still allows — the
# fix targets a *persistent* status dot claiming "fine" is an event, not a
# momentary "done" toast.
#
# Law 7 ("never lie about hardware"): "disconnected" and "unknown" used to
# both collapse into "neutral" too, discarding the difference between
# "confirmed nothing there" and "we don't actually know" — now each keeps
# its own name, and gui/style.py renders them with distinct chrome (hollow
# ring vs. dashed ring) instead of the identical quiet dot "idle" gets.
#
# "fault" is a new explicit alias (still resolves to "crit"/danger-red,
# alongside the pre-existing invalid/error/alarm/compliance) so call sites
# that already say "fault" (the vocabulary gui/style.py's QSS comments and
# docs/design/cockpit_design_system.md §6 use for HV/motor trips) do not
# have to first translate to one of the older synonyms.
_STATE_ALIASES = {
    "connected": "neutral",
    "ok": "neutral",
    "ready": "neutral",
    "off": "neutral",
    "saved": "good",
    "disconnected": "disconnected",
    "unknown": "unknown",
    "idle": "neutral",
    "invalid": "crit",
    "error": "crit",
    "alarm": "crit",
    "compliance": "crit",
    "fault": "crit",
    "warning": "warn",
    "warn": "warn",
    "running": "busy",
    "busy": "busy",
    "live": "busy",
    "armed": "armed",
    "on": "armed",
    "sim": "simulated",
    "simulation": "simulated",
    "simulated": "simulated",
}


def normalize_state(state: str | None) -> str:
    """Return the compact visual state used by QSS selectors."""
    key = str(state or "neutral").strip().lower()
    return _STATE_ALIASES.get(key, key)


def _set_pulse_phase(widget, on: bool) -> None:
    """Toggle the generic ``pulsePhase`` dynamic property (law 8: "only live
    states pulse") that ``QFrame#statusLamp[state="busy"][pulsePhase="1"]``/
    the ``statusChip``/``statusPill`` equivalents in ``gui/style.py`` key
    off. This function holds NO timer of its own — per-architecture rule
    "no new threads/timers/locks" (docs/design/cockpit_design_system.md §10):
    an external 1 Hz-cadence driver (the existing marshaled-signal timer
    already ticking elsewhere) is expected to call
    ``widget.set_pulse_phase(...)`` alternately; this only applies ONE
    toggle and repolishes."""
    widget.setProperty("pulsePhase", "1" if on else "0")
    repolish(widget)


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

    def set_pulse_phase(self, on: bool) -> None:
        """See the module-level ``_set_pulse_phase`` docstring — law 8's
        "only live states pulse" hook. A no-op look-wise unless this chip's
        current state is "busy" (see the QSS's ``[state="busy"][pulsePhase]``
        selector in ``gui/style.py``); harmless to call for any state."""
        _set_pulse_phase(self, on)


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

    def set_pulse_phase(self, on: bool) -> None:
        """See ``StatusChip.set_pulse_phase`` / the module-level
        ``_set_pulse_phase`` docstring."""
        _set_pulse_phase(self, on)


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

    def set_pulse_phase(self, on: bool) -> None:
        """See ``StatusChip.set_pulse_phase`` / the module-level
        ``_set_pulse_phase`` docstring. Pulses both this pill's own QSS hook
        and its lamp's, since the lamp is a separate objectName."""
        _set_pulse_phase(self, on)
        self._lamp.set_pulse_phase(on)


class ReadoutCell(QFrame):
    """Small fixed visual readout with title and monospace value.

    cockpit v5 (docs/design/cockpit_design_system.md §3: "Values must
    ellipsize/fit — a tile can never bleed into a neighbour") — both labels
    elide (``QFontMetrics.elidedText``) against the CELL's own available
    width (not the child label's, which is not reliably resized yet at the
    moment a Qt ``resizeEvent`` fires) rather than growing the tile/its
    ``MetricGrid``/``QHBoxLayout`` siblings to fit the full string. This is
    the fix for the class of bug the QML strip hit (a DISCONNECTED-length
    value pushing a neighbour tile out of the row) on the QWidget side: the
    two labels get ``QSizePolicy.Ignored`` on their horizontal policy so
    their natural (full-text) size hint cannot inflate this frame's — or its
    layout siblings' — minimum size, and the full text is always still
    reachable via the tooltip.
    """

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
        self._title_full = title.upper()
        self._title = QLabel(self._title_full)
        self._title.setObjectName("readoutCellTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setToolTip(self._title_full)
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._value_full = value
        self._value = QLabel(value)
        self._value.setObjectName("readoutCellValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value.setToolTip(value)
        self._value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self._title)
        lay.addWidget(self._value)
        self._state = "normal"
        self._elide_labels()

    def set_value(self, value: str) -> None:
        self._value_full = value
        self._value.setToolTip(value)
        self._elide_labels()

    def value(self) -> str:
        return self._value_full

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._elide_labels()

    def _elide_labels(self) -> None:
        """Elide both labels against THIS frame's own current width minus its
        fixed layout margins (10 px each side — see ``__init__``), rather
        than the child label's ``width()`` — which, at the moment a
        ``resizeEvent`` fires, is not guaranteed to already reflect the new
        layout pass. Never runs before the frame has a real width (avoids
        eliding to nothing during construction, before any ``show()``/
        layout has happened)."""
        avail = self.width() - 20  # 10px left + 10px right margin
        if avail <= 0:
            return
        title_fm = QFontMetrics(self._title.font())
        self._title.setText(
            title_fm.elidedText(self._title_full, Qt.TextElideMode.ElideRight, avail))
        value_fm = QFontMetrics(self._value.font())
        self._value.setText(
            value_fm.elidedText(self._value_full, Qt.TextElideMode.ElideRight, avail))

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

    # OWNED timer (context-object overload): _restore closes over `button`, so
    # an unowned singleShot outlives the widget — close the window / rebuild the
    # panel / soft-reload the config inside the flash window and the timer still
    # fires, touching a deleted C++ object (RuntimeError: "Internal C++ object
    # already deleted").  Passing `button` as the context object makes Qt drop
    # the pending invocation when the button is destroyed.  This also kept the
    # test suite honest: a pending _restore armed near the end of one test used
    # to fire inside the NEXT test's event pumping, which is why the parallel
    # (-n auto) suite failed tests that pass in isolation.
    QTimer.singleShot(timeout_ms, button, _restore)


def set_button_icon(button: QPushButton, icon_name: str, color: str | None = None) -> None:
    """Attach a qtawesome icon when available; silently keep text-only fallback."""
    try:
        import qtawesome as qta
        icon = qta.icon(icon_name, color=color) if color else qta.icon(icon_name)
    except Exception:
        return
    button.setIcon(icon)
