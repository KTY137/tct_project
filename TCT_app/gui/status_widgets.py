"""Small shared status/readout/button widgets for the Qt GUI.

These helpers intentionally stay thin: they reuse ``gui.style`` QSS hooks so
panels get consistent status chips, lamp dots, readout cells, and short button
feedback without each panel owning its own inline styles.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from gui import style as _style
from gui.app_settings import theme_mode
from gui.style import palette, repolish, set_chip_state


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


# ─────────────────────────────────────────────────────────────────────
# Icons (qtawesome) — THE COLOURLESS-ICON BUG, killed at the root.
#
# ``qta.icon(name)`` with no ``color=`` does NOT mean "inherit the theme". It
# resolves qtawesome's default option, which reads the **Qt palette** — and this
# app themes through QSS ONLY (no ``QApplication.setPalette`` beyond the
# Window/WindowText backstop in ``gui.style._apply_app_palette``). So the glyph
# came out the default palette's BLACK, baked into a PIXMAP at construction and
# never re-tinted afterwards: black-on-slate on the shipped dark theme, and
# frozen there through every light/dark toggle for the life of the widget.
# Measured on the dark default: 1.11:1 against a panel, 1.37:1 against a
# field/raised surface — i.e. invisible. (Icons are non-text UI components:
# WCAG 1.4.11 wants >= 3:1.)
#
# The fix lives HERE, in the shared helper, not in the ~50 call sites: a call
# that passes no colour now resolves the ACTIVE theme's palette token (default
# "text" — the button's own label ink) instead of falling through to qtawesome.
# Every existing ``set_button_icon(btn, "mdi.play")`` is fixed where it stands.
#
# Re-tinting on a theme switch is per-widget and event-driven (no locked file,
# no panel edits, and explicitly NOT a QApplication.allWidgets() walk — that
# walk is a documented native-crash vector, see gui.style._apply_pyqtgraph):
# gui.style.apply_theme sets its module-level ``_active_mode`` BEFORE it installs
# the new stylesheet, and Qt then delivers QEvent.StyleChange to every widget
# (measured: parented, unparented, shown and unshown alike). A registered button
# rebuilds its pixmap from the palette on that event; a same-mode re-assert
# installs an identical stylesheet, emits nothing, and costs nothing.
#
# NOTE — hazard controls are deliberately NOT in this system. STOP / Abort /
# Execute / Output OFF / Switch-polarity carry their glyph as a unicode
# character in the button's LABEL TEXT, which takes the QSS ``color`` like any
# other text and is theme-correct already. They must never be converted into
# pixmaps.
# ─────────────────────────────────────────────────────────────────────
_ICON_NAME_PROP = "_ui_icon_name"     # qtawesome name, e.g. "mdi.play"
_ICON_TOKEN_PROP = "_ui_icon_token"   # palette token the ink must MATCH
_ICON_COLOR_PROP = "_ui_icon_color"   # ink currently baked into the pixmap
_ICON_WATCHED_PROP = "_ui_icon_watched"


def active_theme_mode() -> str:
    """The theme mode an icon built *right now* must be tinted for.

    ``gui.style.apply_theme`` records the mode it is applying (``_active_mode``)
    *before* it calls ``setStyleSheet``, so during the resulting StyleChange
    delivery this is already the NEW theme — whereas the persisted QSettings key
    is still the old one at that moment (``tct_gui._toggle_theme`` writes it
    last). Fall back to the persisted setting when no stylesheet has been
    installed at all (a panel constructed standalone in a test, before/without
    ``apply_theme``) — the same source every panel's ``__init__`` already uses.
    """
    app = QApplication.instance()
    if app is not None and app.styleSheet():
        mode = getattr(_style, "_active_mode", "")
        if mode:
            return str(mode)
    return theme_mode()


def icon_ink(token: str = "text", mode: str | None = None) -> str:
    """Palette ink for an icon: the token an icon must carry in *mode*.

    The tokenized replacement for "no colour" (see the block comment above) and
    for hand-rolled hex at a call site (``tests/test_no_inline_hex_gui.py``).
    """
    return palette(mode or active_theme_mode())[token]


def _build_qta_icon(icon_name: str, color: str):
    """A qtawesome icon tinted *color*, or None when qtawesome/the glyph is
    unavailable (icons are never a hard dependency for a control to work — the
    button keeps its text-only fallback)."""
    try:
        import qtawesome as qta
        return qta.icon(icon_name, color=color)
    except Exception:
        return None


class _IconThemeWatcher(QObject):
    """Re-tints a registered button's icon when the app stylesheet changes.

    One shared instance, installed as an event filter on each button that asked
    for a token-bound icon. Filters die with the widget they watch, so nothing
    here can touch a half-destroyed QWidget."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.StyleChange:
            _retint_button_icon(obj)
        return False


_icon_watcher: _IconThemeWatcher | None = None


def _watcher() -> _IconThemeWatcher:
    global _icon_watcher
    if _icon_watcher is None:
        _icon_watcher = _IconThemeWatcher()
    return _icon_watcher


def _retint_button_icon(button) -> None:
    """Rebuild a token-bound icon's pixmap against the live palette (no-op for
    an unregistered button, or one whose ink has not actually changed — Qt
    delivers StyleChange more than once per apply, and a pixmap rebuild is the
    only expensive thing in this path)."""
    name = button.property(_ICON_NAME_PROP)
    token = button.property(_ICON_TOKEN_PROP)
    if not name or not token:
        return
    try:
        color = icon_ink(str(token))
    except KeyError:
        return
    if button.property(_ICON_COLOR_PROP) == color:
        return
    icon = _build_qta_icon(str(name), color)
    if icon is None:
        return
    button.setProperty(_ICON_COLOR_PROP, color)
    button.setIcon(icon)


def set_button_icon(
    button: QPushButton,
    icon_name: str,
    color: str | None = None,
    *,
    token: str = "text",
) -> None:
    """Attach a qtawesome icon when available; silently keep text-only fallback.

    With no *color*, the icon is bound to the palette *token* (default "text",
    the button's own label ink) in the ACTIVE theme and re-tinted automatically
    on every theme switch — see the block comment above; never qtawesome's
    palette-derived black.

    An explicit *color* is the caller's own (e.g. a fixed safety token like
    ``WARN_AMBER``, or a colour a panel re-resolves itself inside its
    ``refresh_theme``): it is applied verbatim and NOT auto-re-tinted, so a
    panel that owns its icon ink keeps owning it.
    """
    if color is None:
        try:
            color = icon_ink(token)
        except KeyError:
            return
        button.setProperty(_ICON_NAME_PROP, icon_name)
        button.setProperty(_ICON_TOKEN_PROP, token)
        if not button.property(_ICON_WATCHED_PROP):
            button.installEventFilter(_watcher())
            button.setProperty(_ICON_WATCHED_PROP, True)
    else:
        # Caller-owned ink: drop any token binding a previous call left behind,
        # so the watcher cannot fight the panel for this button's icon.
        button.setProperty(_ICON_TOKEN_PROP, None)
    icon = _build_qta_icon(icon_name, color)
    if icon is None:
        return
    button.setProperty(_ICON_COLOR_PROP, color)
    button.setIcon(icon)
