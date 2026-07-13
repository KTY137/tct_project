"""Two-step arm latch — the reusable danger well for design-system law 5.

``ArmLatch`` renders the council-ratified "two-step arm, instant stop" gesture
(``docs/design/cockpit_design_system.md`` law 5 / §11) as a self-contained
danger well:

    ┌ armLatchWell (amber-railed card) ───────────────────────┐
    │  <envelope summary — the ArmedEnvelope text, HV in red>  │
    │  [ Arm — hold 3 s / press twice ]  (amber, motion class)  │
    │  [ Execute ]  (danger red — only visible while armed)     │
    │  <hint / readiness / countdown line>                      │
    └──────────────────────────────────────────────────────────┘

The Arm control authorizes ONCE, via either a **hold-3 s** gesture (a progress
fill grows under the button; releasing or leaving before completion cancels) OR
a **press-twice** gesture (two activations inside a short window — keyboard
parity, so Enter/Space twice arms exactly like two clicks, glove-reliable).
Reaching the armed state reveals the danger-red **Execute** button and starts a
~10 s auto-disarm countdown; a single click on the Arm control disarms at any
time. Abort is never routed through this widget — an abort is one instant tap on
a separate always-live control (law 5: "instant stop").

Pure view: no hardware I/O, no controller reference, no plan knowledge. The
owning panel derives the :class:`~controller.arm_envelope.ArmedEnvelope`, renders
its text via :meth:`set_envelope_text`, and reacts to the widget's four signals
(:attr:`arm_started`, :attr:`armed`, :attr:`disarmed`, :attr:`execute_requested`)
to build the :class:`~controller.arm_envelope.ArmedEnvelopeGate` and start the
run. All colours resolve from ``gui.style`` tokens (never a raw hex); a cached
colour is re-resolved on :meth:`refresh_theme` after a light/dark switch.

Timers (three ``QTimer``\\ s, all owned + stopped in :meth:`shutdown`): a fast
hold-progress ticker, a short two-click window, and a 1 Hz armed-window
countdown. No ``QGraphicsEffect`` anywhere (this is not a hot-path plot, but the
depth is still static per the design charter — the only motion is the deliberate
hold-progress fill and the once-a-second countdown value update, law 8).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gui.style import (
    FONT_BODY_PX, RADIUS_MD, SPACE_SM, SPACE_XS, WEIGHT_BODY, palette, repolish,
)

# Gesture / timing constants (design law 5: hold 3 s, ~10 s armed window).
HOLD_MS = 3000            # hold duration to arm
HOLD_TICK_MS = 30         # progress-fill repaint cadence while holding
DOUBLE_PRESS_MS = 700     # window for the press-twice gesture
ARMED_TIMEOUT_S = 10      # auto-disarm countdown once armed


class ArmButton(QPushButton):
    """The Arm control: a ``motion``-class push button that additionally
    supports a **hold-to-arm** gesture with a live progress fill.

    A quick press-release emits the normal ``clicked`` (feeding the parent's
    press-twice detector and, once armed, the click-to-disarm path). Holding
    past :data:`HOLD_MS` fires :attr:`holdCompleted` and *swallows* the release
    so a completed hold never also counts as a click. Releasing early, or moving
    the cursor off the button mid-hold, cancels the gesture (law 5's
    glove-reliable hold). Keyboard activation (Enter/Space) arrives as a plain
    ``clicked`` and so drives the press-twice path — keyboard parity, no hold
    needed on the keyboard.
    """

    holdCompleted = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("state", "motion")
        self._hold_enabled = True
        self._hold_active = False
        self._hold_fired = False
        self._progress = 0.0          # 0..1 hold completion
        # Resolved to the armed token by ArmLatch.refresh_theme() before any
        # paint; transparent until then (never a hardcoded hex — token only).
        self._fill_color = QColor(Qt.GlobalColor.transparent)
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(HOLD_TICK_MS)
        self._hold_timer.timeout.connect(self._on_hold_tick)

    # -- theming --------------------------------------------------------
    def set_fill_color(self, hex_color: str) -> None:
        c = QColor(hex_color)
        c.setAlphaF(0.28)
        self._fill_color = c
        self.update()

    def set_hold_enabled(self, enabled: bool) -> None:
        """Disable the hold gesture (used once armed, when the button's job is
        click-to-disarm and a hold would be meaningless)."""
        self._hold_enabled = bool(enabled)
        if not enabled:
            self._cancel_hold()

    # -- hold gesture ---------------------------------------------------
    def _cancel_hold(self) -> None:
        if self._hold_active or self._progress:
            self._hold_active = False
            self._progress = 0.0
            self._hold_timer.stop()
            self.update()

    def _on_hold_tick(self) -> None:
        if not self._hold_active:
            return
        self._progress = min(1.0, self._progress + HOLD_TICK_MS / HOLD_MS)
        if self._progress >= 1.0:
            self._hold_active = False
            self._hold_fired = True
            self._hold_timer.stop()
            self.update()
            self.holdCompleted.emit()
        else:
            self.update()

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if (self._hold_enabled and self.isEnabled()
                and event.button() == Qt.MouseButton.LeftButton):
            self._hold_active = True
            self._hold_fired = False
            self._progress = 0.0
            self._hold_timer.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt override
        # Leaving the button mid-hold cancels the gesture (release/leave = cancel).
        if self._hold_active and not self.rect().contains(event.position().toPoint()):
            self._cancel_hold()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        self._hold_timer.stop()
        self._hold_active = False
        self._progress = 0.0
        self.update()
        if self._hold_fired:
            # The hold already armed — swallow the release so no `clicked` fires.
            self._hold_fired = False
            self.setDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # noqa: N802 - Qt override
        super().paintEvent(event)
        if self._progress <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width() * self._progress
        rect = QRectF(0, 0, w, self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._fill_color)
        painter.drawRoundedRect(rect, RADIUS_MD, RADIUS_MD)
        painter.end()


class ArmLatch(QWidget):
    """Reusable two-step arm danger well (see the module docstring).

    Signals
    -------
    arm_started()
        The user began an arm gesture (first hold-press or first of two
        presses). The owner derives + renders the envelope here so its text is
        visible over the latch before the gesture completes.
    armed()
        The arm gesture completed; the latch is armed and Execute is live.
    disarmed(str)
        The latch left the armed state; the argument is the reason
        (``"clicked"`` / ``"timeout"`` / ``"invalidated"`` / ``"running"``).
    execute_requested()
        The armed Execute button was pressed — the owner builds the
        ``ArmedEnvelopeGate`` and starts the run.
    """

    arm_started = Signal()
    armed = Signal()
    disarmed = Signal(str)
    execute_requested = Signal()

    def __init__(self, theme_mode: str = "light", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_mode = str(theme_mode)
        self._armed = False
        self._ready = False
        self._reason = ""
        self._running = False
        self._seconds_left = ARMED_TIMEOUT_S

        self._well = QWidget(self)
        self._well.setObjectName("armLatchWell")
        self._well.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self._well)
        lay.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        lay.setSpacing(SPACE_XS)

        self._envelope_lbl = QLabel("")
        self._envelope_lbl.setObjectName("armLatchEnvelope")
        self._envelope_lbl.setWordWrap(True)
        self._envelope_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._envelope_lbl.setVisible(False)
        lay.addWidget(self._envelope_lbl)

        self._arm_btn = ArmButton("⚡ Arm — hold 3 s or press twice")
        self._arm_btn.setEnabled(False)
        self._arm_btn.clicked.connect(self._on_arm_clicked)
        self._arm_btn.holdCompleted.connect(self._on_hold_completed)
        lay.addWidget(self._arm_btn)

        self._exec_btn = QPushButton("▶ Execute")
        self._exec_btn.setObjectName("dangerBtn")
        self._exec_btn.setProperty("state", "danger")
        self._exec_btn.setVisible(False)
        self._exec_btn.clicked.connect(self._on_execute_clicked)
        lay.addWidget(self._exec_btn)

        self._hint = QLabel("")
        self._hint.setObjectName("armLatchHint")
        self._hint.setWordWrap(True)
        lay.addWidget(self._hint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._well)

        # Two-click (press-twice) detector window.
        self._press_window = QTimer(self)
        self._press_window.setSingleShot(True)
        self._press_window.setInterval(DOUBLE_PRESS_MS)

        # 1 Hz armed-window countdown (auto-disarm).
        self._countdown = QTimer(self)
        self._countdown.setInterval(1000)
        self._countdown.timeout.connect(self._on_countdown_tick)

        self.refresh_theme(self._theme_mode)
        self._update_hint()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def is_armed(self) -> bool:
        return self._armed

    def set_ready(self, ready: bool, reason: str = "") -> None:
        """Gate the Arm control on the owner's readiness ladder. When *ready*
        is false the Arm button is disabled and *reason* is shown as the hint
        (law 5 / §5: say WHY arming is unavailable); a currently-armed latch
        disarms."""
        self._ready = bool(ready)
        self._reason = reason or ""
        if not self._ready and self._armed:
            self._disarm("invalidated")
        self._arm_btn.setEnabled(self._ready and not self._running and not self._armed)
        self._update_hint()

    def set_running(self, running: bool) -> None:
        """A run started/ended. During a run the latch is fully inert (Arm
        disabled, any arm dropped) — the run's own Abort control is the live
        stop, never this widget."""
        self._running = bool(running)
        if self._running and self._armed:
            self._disarm("running")
        self._arm_btn.setEnabled(self._ready and not self._running and not self._armed)
        self._update_hint()

    def disarm(self, reason: str = "invalidated") -> None:
        """Force-disarm (e.g. a plan edit invalidated the armed envelope). Also
        cancels any pending press-twice window. Idempotent."""
        self._press_window.stop()
        if self._armed:
            self._disarm(reason)

    def set_envelope_text(self, html: str) -> None:
        """Render the ArmedEnvelope summary over the latch (rich text; the
        owner colours the HV line via a danger-token span). Empty string hides
        the envelope row."""
        self._envelope_lbl.setText(html or "")
        self._envelope_lbl.setVisible(bool(html))

    def refresh_theme(self, mode: str | None = None) -> None:
        if mode:
            self._theme_mode = str(mode)
        p = palette(self._theme_mode)
        armed = p["armed"]
        self._arm_btn.set_fill_color(armed)
        # Amber-railed danger well (law 2: a scan start that ramps HV is
        # amber-gated; the HV line inside is the only red). Surface + hairline
        # + rail all resolve from tokens.
        self._well.setStyleSheet(
            f"#armLatchWell {{ background: {p['raised']}; "
            f"border: 1px solid {p['hairline']}; "
            f"border-left: 3px solid {armed}; "
            f"border-radius: {RADIUS_MD}px; }}"
        )
        self._envelope_lbl.setStyleSheet(
            f"#armLatchEnvelope {{ color: {p['text']}; font-size: {FONT_BODY_PX}px; "
            f"font-weight: {WEIGHT_BODY}; }}"
        )
        self._hint.setStyleSheet(
            f"#armLatchHint {{ color: {p['muted']}; font-size: {FONT_BODY_PX}px; "
            f"font-weight: {WEIGHT_BODY}; }}"
        )
        repolish(self._arm_btn)
        repolish(self._exec_btn)

    def shutdown(self) -> None:
        """Stop every owned timer before teardown (mirrors the panels'
        ``shutdown()`` idiom). Idempotent."""
        self._hold_timer_stop()
        self._press_window.stop()
        self._countdown.stop()

    def _hold_timer_stop(self) -> None:
        # The hold ticker lives on the button; reach through to stop it.
        self._arm_btn._hold_timer.stop()

    # ------------------------------------------------------------------ #
    # Arm gesture                                                         #
    # ------------------------------------------------------------------ #

    def _on_arm_clicked(self) -> None:
        if self._armed:
            # Armed → a single click (mouse or keyboard) disarms, any time.
            self._disarm("clicked")
            return
        if not self._ready or self._running:
            return
        if self._press_window.isActive():
            # Second press inside the window → press-twice arm.
            self._press_window.stop()
            self._do_arm()
        else:
            # First press → open the window and announce the gesture.
            self._press_window.start()
            self.arm_started.emit()
            self._update_hint()

    def _on_hold_completed(self) -> None:
        if self._armed or not self._ready or self._running:
            return
        # A hold IS the arm gesture start + completion in one; announce then arm
        # so the owner has rendered the envelope by the time we latch.
        self._press_window.stop()
        self.arm_started.emit()
        self._do_arm()

    def _do_arm(self) -> None:
        self._armed = True
        self._seconds_left = ARMED_TIMEOUT_S
        self._arm_btn.set_hold_enabled(False)
        self._arm_btn.setProperty("state", "armed")
        self._arm_btn.setEnabled(True)          # stays clickable to disarm
        repolish(self._arm_btn)
        self._exec_btn.setVisible(True)
        self._countdown.start()
        self._update_arm_text()
        self._update_hint()
        self.armed.emit()

    def _disarm(self, reason: str) -> None:
        self._armed = False
        self._countdown.stop()
        self._exec_btn.setVisible(False)
        self._arm_btn.set_hold_enabled(True)
        self._arm_btn.setText("⚡ Arm — hold 3 s or press twice")
        self._arm_btn.setProperty("state", "motion")
        self._arm_btn.setEnabled(self._ready and not self._running)
        repolish(self._arm_btn)
        self._update_hint()
        self.disarmed.emit(reason)

    def _on_execute_clicked(self) -> None:
        if not self._armed:
            return
        # Consume the latch: Execute is terminal, so reset silently (no
        # `disarmed` — the run is starting, not being cancelled) and emit.
        self._armed = False
        self._countdown.stop()
        self._exec_btn.setVisible(False)
        self._arm_btn.set_hold_enabled(True)
        self._arm_btn.setText("⚡ Arm — hold 3 s or press twice")
        self._arm_btn.setProperty("state", "motion")
        self._arm_btn.setEnabled(self._ready and not self._running)
        repolish(self._arm_btn)
        self.execute_requested.emit()
        self._update_hint()

    def _on_countdown_tick(self) -> None:
        self._seconds_left -= 1
        if self._seconds_left <= 0:
            self._disarm("timeout")
            return
        self._update_arm_text()

    # ------------------------------------------------------------------ #
    # Text                                                                #
    # ------------------------------------------------------------------ #

    def _update_arm_text(self) -> None:
        self._arm_btn.setText(f"✓ Armed · {self._seconds_left}s · click to disarm")

    def _update_hint(self) -> None:
        if self._running:
            self._hint.setText("Run in progress — Abort is the live stop.")
        elif self._armed:
            self._hint.setText(
                "Armed. Press Execute to start, or click Arm to stand down.")
        elif not self._ready:
            self._hint.setText(self._reason or "Not ready to arm.")
        elif self._press_window.isActive():
            self._hint.setText("Press Arm again to authorize (or keep holding).")
        else:
            self._hint.setText(
                "Review the envelope, then hold Arm 3 s or press it twice.")
