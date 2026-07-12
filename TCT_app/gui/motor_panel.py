"""Motor control panel — works with any MotorStageBase implementation."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QSettings
from PySide6.QtWidgets import (
    QApplication, QWidget, QGridLayout, QHBoxLayout, QVBoxLayout,
    QLabel, QDoubleSpinBox, QPushButton, QSizePolicy, QSplitter,
    QButtonGroup, QFrame,
)

from devices.motor_base import MotorStageBase
from gui.panel_kit import Card, panel_header
from gui.stage_view import StageView
from gui.style import axis_color, palette, repolish
from gui.status_widgets import StatusChip, flash_button
from PySide6.QtCore import QObject

# Optional vector icons — the panel degrades to plain text when qtawesome is
# missing (same graceful-fallback pattern as gui/scope_panel.py).
try:
    import qtawesome as qta
    _HAS_QTA = True
except ImportError:
    _HAS_QTA = False


def _icon(name: str, color: str | None = None):
    """qtawesome icon or None when the lib/icon is unavailable (buttons fall
    back to text-only — never a hard dependency for a control to work)."""
    if not _HAS_QTA:
        return None
    try:
        return qta.icon(name, color=color) if color else qta.icon(name)
    except Exception:
        return None


def _apply_icon(button: QPushButton, name: str, color: str | None = None) -> None:
    """Attach an optional qtawesome icon without making icons a dependency."""
    icon = _icon(name, color=color)
    if icon is not None:
        button.setIcon(icon)


class _PositionPoller(QObject):
    """
    Runs get_position() in a dedicated QThread so serial I/O never blocks
    the GUI thread.  Emits position_updated with the (x, y, z) floats in mm;
    the panel formats the labels and drives the stage visualisation from the
    same numbers (one source of truth).
    """
    position_updated = Signal(float, float, float)

    def __init__(self, motor: MotorStageBase) -> None:
        super().__init__()
        self._motor = motor
        self._paused = False
        # Parent the timer to self so moveToThread() carries it to the worker
        # thread automatically.  An unparented QTimer stays on the main thread
        # and 'startTimer from another thread' warnings / silent failures result.
        self._timer = QTimer(self)
        self._timer.setInterval(500)   # poll every 500 ms — fast enough for display
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_paused(self, paused: bool) -> None:
        """Pause status polling while a move/home runs in the task thread, so
        only one thread ever talks to the serial port at a time (a bool write
        is atomic in CPython — safe to flip from the GUI thread)."""
        self._paused = paused

    def _poll(self) -> None:
        if self._paused or not self._motor.connected:
            return
        try:
            pos = self._motor.get_position()
            self.position_updated.emit(pos.x_mm, pos.y_mm, pos.z_mm)
        except Exception as exc:
            logging.getLogger(__name__).debug("position poll failed: %s", exc)


class _MotorTask(QObject):
    """Runs one blocking motor operation off the GUI thread.

    Homing and long absolute moves take seconds; running them directly in a
    button slot froze the whole window.  This carries the call into a worker
    QThread and reports completion (or the error) back via a signal.
    """
    done = Signal(str)   # "" on success, else the error message

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
            self.done.emit("")
        except Exception as exc:
            self.done.emit(str(exc))


class MotorPanel(QWidget):
    """
    X/Y/Z jog, absolute move, home, and emergency stop.

    Accepts any MotorStageBase subclass — swapping the motor backend
    requires no changes here.
    """

    # Emitted when user clicks "Set as Scan Start" — carries (x, y, z)
    set_as_scan_start = Signal(float, float, float)
    # Emitted after a home or Zero-Here completes successfully — either shifts
    # the driver's user/machine display offset, so any consumer holding
    # user-frame stage limits (the Scan Planner's PlanLimits) must re-read them.
    # Authored as run-control/state logic (Abel); pure notification, no payload.
    origin_changed = Signal()
    _poll_stop_requested = Signal()

    def __init__(self, motor: MotorStageBase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._motor = motor
        self._motion_widgets: list[QWidget] = []   # disabled while a move runs
        self._task_thread: QThread | None = None
        self._task: _MotorTask | None = None
        # Kind of the in-flight async op ("home"/"zero"/None). Home and Zero
        # Here shift the driver's display offset, so on success we notify
        # (origin_changed) any consumer holding user-frame limits.
        self._task_kind: str | None = None
        # Theme mode for the axis-rail accents (gui.style.axis_color).  Read
        # once from the same QSettings key main.py/tct_gui.py use, so a
        # freshly built panel matches the already-applied app theme; see
        # refresh_theme() for why there is no live change notification yet.
        self._theme_mode = str(QSettings("TCT", "TCTSetup").value("theme", "light"))
        self._readout_caps: dict[str, QLabel] = {}
        self._jog_axis_btns: dict[str, list[QPushButton]] = {"x": [], "y": [], "z": []}
        self._abs_captions: dict[str, QLabel] = {}
        # Last position seen from the poller — lets the connection/homed chip
        # refresh (below) repaint without needing a live poll of its own; see
        # _refresh_connection_state().
        self._last_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._build_ui()

        # Frame contract (docs/ARCHITECTURE.md "Motor frame contract"): the
        # stage view's travel envelope must live in the SAME user frame the
        # position marker does.  Home / Zero Here shift that frame, so re-pull
        # the envelope on every origin change — the same trigger tct_gui uses
        # to rebuild the planner's PlanLimits.
        self.origin_changed.connect(self._refresh_stage_limits)

        # Position polling runs in a separate thread so serial I/O never
        # blocks the GUI (especially important for Marlin M114 queries).
        #
        # Deliberately parented to the QApplication instance, NOT to ``self``
        # (QThread(self)) — same fix/idiom as gui/settings_window.py's
        # _VisaScanManager._start(): a soft config-reload tears this panel
        # down and Qt's setCentralWidget() deletes the old widget tree
        # shortly after.  shutdown() below waits for this thread with a
        # bound, but a bound is not a guarantee — a bench-observed case is a
        # task thread stuck inside a long move holding the driver lock (see
        # _run_async's _task_thread), which can make the poll thread's own
        # quit() take longer than the bound too.  A QThread whose Qt parent
        # is cascade-deleted while still running is a hard Qt6 crash
        # ("QThread: Destroyed while thread is still running"); parenting to
        # the long-lived QApplication instead means the thread survives this
        # widget's teardown and finishes cleanly via its own
        # quit -> finished -> deleteLater chain below, regardless of what
        # happens to this panel.
        self._poller = _PositionPoller(motor)
        self._poll_thread = QThread(QApplication.instance())
        self._poller.moveToThread(self._poll_thread)
        self._poll_thread.started.connect(self._poller.start)
        self._poll_stop_requested.connect(self._poller.stop)
        self._poll_thread.finished.connect(self._poller.deleteLater)
        self._poll_thread.finished.connect(self._poll_thread.deleteLater)
        self._poller.position_updated.connect(self._on_position_updated)
        self._poll_thread.start()

        # Connection/homed chip refresh — a *separate*, GUI-thread-only timer
        # that reads only plain ``connected``/``homed`` attributes (no device
        # I/O, same as tct_gui.py's top-bar status strip).  The poller above
        # only emits position_updated (which drives _refresh_status_chips)
        # after a successful get_position() call, and it skips calling
        # get_position() at all while the motor is disconnected — so a
        # freshly-built panel for a not-yet-connected device would otherwise
        # be stuck showing its construction-time default chip text ("Not
        # homed") forever instead of an accurate "Offline".
        self._conn_timer = QTimer(self)
        self._conn_timer.setInterval(1000)
        self._conn_timer.timeout.connect(self._refresh_connection_state)
        self._conn_timer.start()
        self._refresh_connection_state()   # paint the correct state immediately

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        controls = QWidget()
        root = QVBoxLayout(controls)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        root.addWidget(panel_header("TCT Control — Motion", "Motor Stage"))

        # ── Position display — the panel's hero readout ───────────────
        # A dark "instrument screen" readout (same visual language as the
        # plot canvas); the subtitle names the FRAME the numbers live in
        # (user frame — Home/Zero-Here shift the display offset, law 7).
        pos_box = Card("Position", "user frame · mm")
        pos_v = pos_box.body
        pos_v.setSpacing(10)

        readout = QFrame()
        readout.setObjectName("instrumentReadout")
        readout.setAttribute(Qt.WA_StyledBackground, True)
        readout_grid = QGridLayout(readout)
        readout_grid.setContentsMargins(16, 10, 16, 10)
        readout_grid.setHorizontalSpacing(28)
        readout_grid.setVerticalSpacing(2)
        self._lbl_x = QLabel("—")
        self._lbl_y = QLabel("—")
        self._lbl_z = QLabel("—")
        for col, (axis, lbl) in enumerate(
            (("X", self._lbl_x), ("Y", self._lbl_y), ("Z", self._lbl_z))
        ):
            cap = QLabel(axis)
            cap.setObjectName("readoutAxis")
            cap.setAlignment(Qt.AlignCenter)
            lbl.setObjectName("readoutValue")
            lbl.setAlignment(Qt.AlignCenter)
            readout_grid.addWidget(cap, 0, col)
            readout_grid.addWidget(lbl, 1, col)
            self._readout_caps[axis.lower()] = cap
        pos_v.addWidget(readout)
        self._restyle_axis_readouts()

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._chip_homed = StatusChip("Not homed", "neutral")
        self._chip_motion = StatusChip("Idle", "neutral")
        self._chip_limits = StatusChip("Soft limits --", "neutral")
        # Law 7 honesty: hardware limit-SWITCH state is not read back by the
        # driver (GRBL $ parse backlog is Paul's) — say "unknown", always.
        self._chip_switches = StatusChip("Switches unknown", "unknown")
        self._chip_switches.setToolTip(
            "Hardware limit-switch state is not read back by the driver — "
            "the chips left of this one track SOFT limits only.")
        self._chip_last = StatusChip("Last --", "neutral")
        for chip in (self._chip_homed, self._chip_motion, self._chip_limits,
                     self._chip_switches, self._chip_last):
            status_row.addWidget(chip)
        status_row.addStretch(1)
        pos_v.addLayout(status_row)

        btn_test = QPushButton("Test connection")
        _apply_icon(btn_test, "fa5s.plug")
        btn_test.setToolTip("Send a firmware-identity G-code (M115 / $I) and show the reply — "
                            "confirms the serial link without moving the stage")
        btn_test.clicked.connect(self._test_connection)
        pos_v.addWidget(btn_test)
        root.addWidget(pos_box)

        # ── Jog controls (OctoPrint-style XY cross + Z column) ────────
        # The cross, Z column and step-size presets all live inside one
        # recessed "controlCluster" card so they read as a single jog
        # controller rather than loose buttons in a form.
        jog_box = Card("Jog")
        jog_v = jog_box.body

        cluster = QFrame()
        cluster.setObjectName("controlCluster")
        cluster.setAttribute(Qt.WA_StyledBackground, True)
        cluster_v = QVBoxLayout(cluster)
        cluster_v.setContentsMargins(14, 12, 14, 12)
        cluster_v.setSpacing(12)

        pads_row = QHBoxLayout()
        pads_row.setSpacing(22)

        # XY cross: classic plus-shape, Y+ up top, X-/X+ either side, Y- at
        # the bottom.  The centre cell holds a purely decorative crosshair
        # icon (no click handler) — "Home All" below is the single homing
        # entry point; putting a second homing button in the middle of a
        # jog cluster would just invite a stray click to home the stage
        # instead of jogging it.
        xy_col = QVBoxLayout()
        xy_col.setSpacing(6)
        xy_caption = QLabel("XY")
        xy_caption.setObjectName("clusterCaption")
        xy_caption.setAlignment(Qt.AlignCenter)
        # Combines two axes, so it keeps the neutral clusterCaption colour —
        # axis_color() has no meaningful single hue for "xy" (the individual
        # X/X buttons and Y/Y buttons below get their own axis colour instead).
        xy_col.addWidget(xy_caption)

        cross = QGridLayout()
        cross.setSpacing(4)
        btn_y_pos = QPushButton("Y+")
        btn_y_neg = QPushButton("Y−")
        btn_x_pos = QPushButton("X+")
        btn_x_neg = QPushButton("X−")
        for b in (btn_y_pos, btn_y_neg, btn_x_pos, btn_x_neg):
            b.setObjectName("jogBtn")
            b.setMinimumSize(48, 48)   # compact cluster (design system §7)
        _apply_icon(btn_y_pos, "fa5s.arrow-up")
        _apply_icon(btn_y_neg, "fa5s.arrow-down")
        _apply_icon(btn_x_neg, "fa5s.arrow-left")
        _apply_icon(btn_x_pos, "fa5s.arrow-right")
        btn_y_pos.setToolTip("Jog +Y by the selected step")
        btn_y_neg.setToolTip("Jog −Y by the selected step")
        btn_x_pos.setToolTip("Jog +X by the selected step")
        btn_x_neg.setToolTip("Jog −X by the selected step")
        cross.addWidget(btn_y_pos, 0, 1)
        cross.addWidget(btn_x_neg, 1, 0)
        center_decor = QLabel()
        center_decor.setAlignment(Qt.AlignCenter)
        center_decor.setEnabled(False)
        center_icon = _icon("fa5s.crosshairs",
                            color=palette(self._theme_mode)["faint"])
        if center_icon is not None:
            center_decor.setPixmap(center_icon.pixmap(16, 16))
        self._jog_center_decor = center_decor   # re-tinted by refresh_theme()
        cross.addWidget(center_decor, 1, 1)
        cross.addWidget(btn_x_pos, 1, 2)
        cross.addWidget(btn_y_neg, 2, 1)
        btn_y_pos.clicked.connect(lambda: self._jog("y", +1))
        btn_y_neg.clicked.connect(lambda: self._jog("y", -1))
        btn_x_pos.clicked.connect(lambda: self._jog("x", +1))
        btn_x_neg.clicked.connect(lambda: self._jog("x", -1))
        self._motion_widgets.extend([btn_y_pos, btn_y_neg, btn_x_pos, btn_x_neg])
        self._jog_axis_btns["x"].extend([btn_x_pos, btn_x_neg])
        self._jog_axis_btns["y"].extend([btn_y_pos, btn_y_neg])
        xy_col.addLayout(cross)
        pads_row.addLayout(xy_col)

        # Z column: separate vertical Z+/Z- stack, matching OctoPrint's
        # detached Z jog control.
        z_col_outer = QVBoxLayout()
        z_col_outer.setSpacing(6)
        z_caption = QLabel("Z")
        z_caption.setObjectName("clusterCaption")
        z_caption.setAlignment(Qt.AlignCenter)
        z_col_outer.addWidget(z_caption)
        self._z_cluster_caption = z_caption   # single-axis caption — safe to tint (see "XY" below)

        z_col = QVBoxLayout()
        z_col.setSpacing(4)
        btn_z_pos = QPushButton("Z+")
        btn_z_neg = QPushButton("Z−")
        for b in (btn_z_pos, btn_z_neg):
            b.setObjectName("jogBtn")
            b.setMinimumSize(48, 48)
        _apply_icon(btn_z_pos, "fa5s.arrow-up")
        _apply_icon(btn_z_neg, "fa5s.arrow-down")
        btn_z_pos.setToolTip("Jog +Z by the selected step")
        btn_z_neg.setToolTip("Jog −Z by the selected step")
        z_col.addWidget(btn_z_pos)
        z_col.addStretch(1)
        z_col.addWidget(btn_z_neg)
        btn_z_pos.clicked.connect(lambda: self._jog("z", +1))
        btn_z_neg.clicked.connect(lambda: self._jog("z", -1))
        self._motion_widgets.extend([btn_z_pos, btn_z_neg])
        self._jog_axis_btns["z"].extend([btn_z_pos, btn_z_neg])
        z_col_outer.addLayout(z_col)
        pads_row.addLayout(z_col_outer)
        pads_row.addStretch(1)
        cluster_v.addLayout(pads_row)
        self._restyle_jog_buttons()

        # Micro-step presets: one-click exclusive step size, styled as a
        # segmented control (OctoPrint uses 0.1 / 1 / 10 / 100 mm; this
        # stage moves in fractions of a mm so the presets go down to
        # 1 micron instead).
        step_row = QHBoxLayout()
        step_row.setSpacing(8)
        step_caption = QLabel("Step size")
        step_caption.setObjectName("clusterCaption")
        step_row.addWidget(step_caption)

        seg_frame = QFrame()
        seg_frame.setObjectName("segmented")
        seg_frame.setAttribute(Qt.WA_StyledBackground, True)
        seg_h = QHBoxLayout(seg_frame)
        seg_h.setContentsMargins(3, 3, 3, 3)
        seg_h.setSpacing(2)

        self._step_group = QButtonGroup(self)
        self._step_group.setExclusive(True)
        self._step_buttons: dict[QPushButton, float] = {}
        for val in (0.001, 0.01, 0.1, 1.0, 10.0):
            btn = QPushButton(f"{val:g}")
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setToolTip(f"Jog step = {val:g} mm")
            btn.setMinimumWidth(44)
            self._step_group.addButton(btn)
            self._step_buttons[btn] = val
            seg_h.addWidget(btn)
            self._motion_widgets.append(btn)
        # Default matches the old continuous spinbox's default (0.1 mm).
        for btn, val in self._step_buttons.items():
            if val == 0.1:
                btn.setChecked(True)
                break

        # Optional custom step, for values the presets don't cover — stays
        # part of the same exclusive group so exactly one step size is ever
        # active.
        self._step_custom_btn = QPushButton("Custom")
        self._step_custom_btn.setObjectName("segBtn")
        self._step_custom_btn.setCheckable(True)
        self._step_custom_btn.setToolTip(
            "Use the value in the adjacent box as the jog step")
        self._step_group.addButton(self._step_custom_btn)
        seg_h.addWidget(self._step_custom_btn)
        step_row.addWidget(seg_frame)

        self._jog_step_custom = QDoubleSpinBox()
        self._jog_step_custom.setRange(0.0001, 100.0)
        self._jog_step_custom.setDecimals(4)
        self._jog_step_custom.setValue(0.1)
        self._jog_step_custom.setSuffix(" mm")
        self._jog_step_custom.setMaximumWidth(110)
        step_row.addWidget(self._jog_step_custom)
        step_row.addStretch(1)
        self._motion_widgets.extend([self._step_custom_btn, self._jog_step_custom])
        cluster_v.addLayout(step_row)

        jog_v.addWidget(cluster)
        root.addWidget(jog_box)

        # ── Absolute move ─────────────────────────────────────────────
        abs_box = Card("Absolute move")
        abs_layout = QGridLayout()
        abs_layout.setHorizontalSpacing(10)
        abs_layout.setVerticalSpacing(6)
        self._spin_x = self._make_spin()
        self._spin_y = self._make_spin()
        self._spin_z = self._make_spin()
        for col, (axis_key, label, spin) in enumerate(
            [("x", "X (MM)", self._spin_x), ("y", "Y (MM)", self._spin_y),
             ("z", "Z (MM)", self._spin_z)]
        ):
            cap = QLabel(label)
            # A standalone caption (not inside a controlCluster frame like the
            # jog captions), so the general-purpose "eyebrow" hook fits better
            # than "clusterCaption" — same look, more accurate semantics.
            cap.setObjectName("eyebrow")
            abs_layout.addWidget(cap, 0, col)
            abs_layout.addWidget(spin, 1, col)
            self._abs_captions[axis_key] = cap
        self._restyle_abs_move_captions()
        btn_move = QPushButton("Move to")
        # Law 2: an absolute move is a MOTION-class command (amber), never
        # red — red stays reserved for HV/trips/STOP.
        btn_move.setProperty("state", "motion")
        repolish(btn_move)
        _apply_icon(btn_move, "fa5s.location-arrow")
        btn_move.clicked.connect(self._move_abs)
        abs_layout.addWidget(btn_move, 2, 0, 1, 3)
        self._motion_widgets.extend([self._spin_x, self._spin_y, self._spin_z, btn_move])
        abs_box.add_layout(abs_layout)
        root.addWidget(abs_box)

        # ── Action buttons ─────────────────────────────────────────────
        # Clear hierarchy: Home/Center/Zero are ordinary secondary buttons
        # on one row; STOP is its own full-width, red, unmistakable control
        # underneath — never disabled (see _motion_widgets below), so it
        # always fires immediately, mid-move or not.
        actions_box = Card("Actions")
        actions_v = actions_box.body
        actions_v.setSpacing(10)

        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(8)
        self._btn_home = QPushButton("Home all")
        _apply_icon(self._btn_home, "fa5s.home")
        self._btn_home.clicked.connect(self._home)
        btn_center = QPushButton("Center")
        _apply_icon(btn_center, "fa5s.crosshairs")
        btn_center.setToolTip("Move to the centre of the soft-limit envelope")
        btn_center.clicked.connect(self._move_center)
        btn_zero = QPushButton("Zero here")
        _apply_icon(btn_zero, "fa5s.dot-circle")
        btn_zero.setToolTip("Declare the current position as (0, 0, 0) without moving "
                            "(software display offset — does not touch GRBL's G54/G92)")
        btn_zero.clicked.connect(self._zero_position)
        secondary_row.addWidget(self._btn_home)
        secondary_row.addWidget(btn_center)
        secondary_row.addWidget(btn_zero)
        self._motion_widgets.extend([self._btn_home, btn_center, btn_zero])
        actions_v.addLayout(secondary_row)

        btn_stop = QPushButton("STOP")
        btn_stop.setObjectName("dangerBtn")
        _apply_icon(btn_stop, "fa5s.hand-paper", color="white")
        btn_stop.setMinimumHeight(44)
        btn_stop.setToolTip("Emergency stop — immediately halts all axes, "
                            "ahead of any queued motion")
        btn_stop.clicked.connect(self._emergency_stop)
        actions_v.addWidget(btn_stop)
        root.addWidget(actions_box)

        # ── Scan-integration helpers ──────────────────────────────────
        helper_box = Card("Scan integration")
        helper_layout = QHBoxLayout()
        helper_layout.setSpacing(8)
        btn_use_pos = QPushButton("Use current position")
        _apply_icon(btn_use_pos, "fa5s.clipboard-list")
        btn_use_pos.setToolTip("Copy current stage position into the Absolute-move spinboxes")
        btn_use_pos.clicked.connect(self._use_current_pos)
        self._btn_set_start = QPushButton("Set as scan start")
        _apply_icon(self._btn_set_start, "fa5s.thumbtack")
        self._btn_set_start.setToolTip("Copy current X/Y/Z into the Scan panel start position")
        self._btn_set_start.clicked.connect(self._emit_set_as_start)
        helper_layout.addWidget(btn_use_pos)
        helper_layout.addWidget(self._btn_set_start)
        helper_box.add_layout(helper_layout)
        root.addWidget(helper_box)
        root.addStretch(1)

        # ── Stage cockpit: controls (left) + live setup view (right) ──
        # The stage view sits in a "cardPane" frame so it reads level with
        # the group-box cards in the controls column instead of floating
        # unframed next to them.
        stage_card = QFrame()
        stage_card.setObjectName("cardPane")
        stage_card.setAttribute(Qt.WA_StyledBackground, True)
        stage_card_v = QVBoxLayout(stage_card)
        stage_card_v.setContentsMargins(12, 12, 12, 12)
        # USER-frame limits, not raw ``motor.limits`` (MACHINE frame for
        # GRBL): the marker is driven from get_position() (user frame), so an
        # envelope drawn in the machine frame teleports the marker relative to
        # it the moment Zero Here shifts the display offset.
        self._stage_view = StageView(
            self._limits_user_frame(),
            theme_mode=self._theme_mode,
        )
        stage_card_v.addWidget(self._stage_view)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(controls)
        split.addWidget(stage_card)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 560])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(split)

    # ------------------------------------------------------------------ #
    # Axis-rail styling (gui.style.axis_color) — re-run by refresh_theme() #
    # ------------------------------------------------------------------ #

    def _restyle_axis_readouts(self) -> None:
        """Tint each axis's caption and give its value a quiet coloured rail
        border, echoing the planner preview's axis-rail language (each axis
        keeps its own hue; nothing gets a painted background)."""
        values = {"x": self._lbl_x, "y": self._lbl_y, "z": self._lbl_z}
        for axis, cap in self._readout_caps.items():
            color = axis_color(axis, self._theme_mode)
            cap.setStyleSheet(f"#readoutAxis {{ color: {color}; }}")
            val = values.get(axis)
            if val is not None:
                val.setStyleSheet(
                    f"#readoutValue {{ border-left: 3px solid {color}; padding-left: 8px; }}"
                )

    def _restyle_jog_buttons(self) -> None:
        """Give each jog button a quiet axis-coloured left-edge rail — the
        same idiom gui/scope_panel.py uses for its per-channel ``channelCard``
        border, applied per-axis instead of per-channel here."""
        for axis, buttons in self._jog_axis_btns.items():
            color = axis_color(axis, self._theme_mode)
            for btn in buttons:
                btn.setStyleSheet(f"#jogBtn {{ border-left: 3px solid {color}; }}")
        # "Z" is a single-axis caption (unlike the combined "XY" one above
        # it), so it can safely take the Z-axis colour directly.
        z_cap = getattr(self, "_z_cluster_caption", None)
        if z_cap is not None:
            z_cap.setStyleSheet(f"#clusterCaption {{ color: {axis_color('z', self._theme_mode)}; }}")
        # The decorative centre crosshair is faint-token tinted (baked as a
        # pixmap, so it needs the same explicit re-resolve).
        decor = getattr(self, "_jog_center_decor", None)
        if decor is not None:
            icon = _icon("fa5s.crosshairs", color=palette(self._theme_mode)["faint"])
            if icon is not None:
                decor.setPixmap(icon.pixmap(16, 16))

    def _restyle_abs_move_captions(self) -> None:
        """Tint the Absolute-Move X/Y/Z eyebrow captions with the same
        per-axis colour used for the readout and jog cluster, so every place
        an axis appears in the panel reads as the same identity."""
        for axis, cap in self._abs_captions.items():
            color = axis_color(axis, self._theme_mode)
            cap.setStyleSheet(f"#eyebrow {{ color: {color}; }}")

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve axis-rail colours after a light/dark theme switch.

        ``gui.style.apply_theme(app, mode)`` re-applies the QApplication-wide
        stylesheet, which already repaints every objectName-based QSS hook
        (dangerBtn, statusChip, jogBtn, ...) automatically. The axis colours
        painted above are baked in as instance-level inline styles at
        construction time (Qt style sheets have no "current axis" selector),
        so they need this explicit refresh.

        Called live by ``tct_gui._toggle_theme`` right after
        ``apply_theme(app, mode)`` (alongside the bias panel's own
        ``refresh_theme``), so a theme switch re-resolves these
        instance-level colours immediately.
        """
        if mode:
            self._theme_mode = str(mode)
        self._restyle_axis_readouts()
        self._restyle_jog_buttons()
        self._restyle_abs_move_captions()
        stage_view = getattr(self, "_stage_view", None)
        if stage_view is not None:
            stage_view.refresh_theme(self._theme_mode)

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _current_jog_step_mm(self) -> float:
        """Return the mm step selected in the micro-step preset row."""
        if self._step_custom_btn.isChecked():
            return self._jog_step_custom.value()
        for btn, val in self._step_buttons.items():
            if btn.isChecked():
                return val
        return 0.1   # exclusive group always has a checked button; fallback only

    def _jog(self, axis: str, direction: int) -> None:
        step = self._current_jog_step_mm() * direction
        self._run_async(lambda: self._motor.move_relative(
            dx_mm=step if axis == "x" else 0.0,
            dy_mm=step if axis == "y" else 0.0,
            dz_mm=step if axis == "z" else 0.0,
        ))

    def _move_abs(self) -> None:
        x, y, z = self._spin_x.value(), self._spin_y.value(), self._spin_z.value()
        self._run_async(lambda: self._motor.move_to(x, y, z))

    def _move_center(self) -> None:
        self._run_async(self._motor.move_to_center)

    def _home(self) -> None:
        self._run_async(self._motor.home, kind="home")

    def _zero_position(self) -> None:
        self._run_async(self._motor.zero_position, kind="zero")

    def _emergency_stop(self) -> None:
        # Runs on the GUI thread on purpose: it must fire immediately and the
        # GRBL backend writes the real-time hold byte without taking any lock.
        try:
            self._motor.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Async motor-operation runner (keeps the GUI responsive)             #
    # ------------------------------------------------------------------ #

    def _run_async(self, fn, kind: str | None = None) -> None:
        """Run a blocking motor call in a worker thread; ignore if one is busy.

        *kind* tags offset-changing ops ("home"/"zero") so ``_on_task_done``
        can emit ``origin_changed`` on success — see that signal's docstring.
        """
        if self._task_thread is not None and self._task_thread.isRunning():
            return
        self._task_kind = kind
        self._set_busy(True)
        self._poller.set_paused(True)      # only the task thread talks serial now
        self._task = _MotorTask(fn)
        # Parented to QApplication, same reason as _poll_thread above: a soft
        # config-reload can tear this panel down while a home()/move() is
        # still running (up to ~120 s), so this thread must be free to
        # outlive — and clean itself up after — the widget that started it.
        self._task_thread = QThread(QApplication.instance())
        self._task.moveToThread(self._task_thread)
        self._task_thread.started.connect(self._task.run)
        self._task_thread.finished.connect(self._task_thread.deleteLater)
        self._task.done.connect(self._on_task_done)
        self._task_thread.start()

    def _on_task_done(self, err: str) -> None:
        thread = self._task_thread
        kind = self._task_kind
        self._task_thread = None
        self._task = None
        self._task_kind = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)
        self._poller.set_paused(False)     # resume live position updates
        self._set_busy(False)
        if err:
            self._chip_last.set_status("Last error", "crit", err)
            self._show_error(err)
        else:
            # Quiet nominal: a completed op is routine, not a green light.
            self._chip_last.set_status("Last done", "neutral")
            # Home/Zero Here shifted the driver's user/machine offset — tell any
            # consumer holding user-frame stage limits (the Scan Planner) to
            # re-read them so its soft-limit gate tracks the new origin.
            if kind in ("home", "zero"):
                self.origin_changed.emit()

    # ------------------------------------------------------------------ #
    # Coordinate-frame plumbing (docs/ARCHITECTURE.md "Motor frame contract")
    # ------------------------------------------------------------------ #

    def _limits_user_frame(self):
        """Soft limits in the motor's USER frame — the frame ``get_position()``
        returns and ``move_to()`` accepts, i.e. the ONLY frame this panel may
        draw or compare positions against.  Pure attribute arithmetic in every
        backend (no device I/O), so it is safe on the GUI thread.  Falls back
        to raw ``limits`` for a hot-swapped backend without the helper (for
        which the two frames are identical by definition) — same fallback as
        tct_gui._plan_limits."""
        try:
            return self._motor.limits_user_frame()
        except Exception:
            logging.getLogger(__name__).debug(
                "motor.limits_user_frame() failed", exc_info=True)
            return getattr(self._motor, "limits", None)

    def _refresh_stage_limits(self) -> None:
        """Redraw the stage view's travel envelope after the origin moved.

        Home / Zero Here shift the driver's user/machine display offset, so an
        envelope drawn once at construction time stays in the OLD frame while
        the position marker (poller → user frame) jumps to the new origin: the
        marker visually teleports even though the stage never moved (bench
        bug, 2026-07-11 — same frame-mixing family as the planner PlanLimits
        fix in 2f91e00).  Re-pulling ``limits_user_frame()`` shifts the
        envelope by exactly the same offset, so the marker's RELATIVE position
        inside it is preserved.  Wired to ``origin_changed`` in __init__.
        """
        self._stage_view.set_limits(self._limits_user_frame())

    def _set_busy(self, busy: bool) -> None:
        for w in self._motion_widgets:
            w.setEnabled(not busy)
        self._chip_motion.set_status("Moving..." if busy else "Idle",
                                     "busy" if busy else "neutral")

    def _test_connection(self) -> None:
        """Run the backend's firmware handshake and show the reply."""
        from PySide6.QtWidgets import QMessageBox, QApplication
        if not self._motor.connected:
            QMessageBox.information(
                self, "Test Connection",
                "Motor is not connected.\nClick 'Connect All' in the top bar first.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            msg = self._motor.test_connection()
        except Exception as exc:
            msg = f"Test failed: {exc}"
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Motor Connection Test", msg)

    def _on_position_updated(self, x: float, y: float, z: float) -> None:
        self._last_pos = (x, y, z)
        # The axis letter already sits in the caption row above each value —
        # the value itself is a pure signed quantity (law 3).
        self._lbl_x.setText(f"{x:+.4f} mm")
        self._lbl_y.setText(f"{y:+.4f} mm")
        self._lbl_z.setText(f"{z:+.4f} mm")
        self._stage_view.set_position(x, y, z)
        self._refresh_status_chips(x, y, z)

    def _refresh_connection_state(self) -> None:
        """GUI-thread-only, I/O-free refresh of the connected/homed chip.

        Reads only plain ``connected``/``homed`` attributes (exactly what
        tct_gui.py's top-bar status strip already does on its own 1 s timer),
        so it keeps the panel's own chip accurate even while the poller is
        paused or the motor is disconnected — see the _conn_timer comment in
        __init__ for why that case would otherwise go stale.
        """
        x, y, z = self._last_pos
        self._refresh_status_chips(x, y, z)

    def _refresh_status_chips(self, x: float, y: float, z: float) -> None:
        connected = bool(getattr(self._motor, "connected", False))
        homed = bool(getattr(self._motor, "homed", False))
        if not connected:
            self._chip_homed.set_status("Offline", "disconnected")
            self._chip_limits.set_status("Soft limits --", "neutral")
            return
        if homed:
            # Quiet nominal (law 1): homed is routine, not a green light.
            self._chip_homed.set_status("Homed", "neutral")
        else:
            self._chip_homed.set_status("Not homed", "warn")

        # x/y/z here come from the poller = USER frame, so compare against the
        # limits in that same frame.  Raw ``motor.limits`` (machine frame for
        # GRBL) flagged a false "soft-limit error" right after Zero Here.
        lim = self._limits_user_frame()
        if lim is None:
            self._chip_limits.set_status("Soft limits --", "neutral")
            return
        margin_mm = 0.5
        near: list[str] = []
        for axis, value in (("X", x), ("Y", y), ("Z", z)):
            lo = getattr(lim, f"{axis.lower()}_min", None)
            hi = getattr(lim, f"{axis.lower()}_max", None)
            if lo is None or hi is None:
                continue
            if value < float(lo) or value > float(hi):
                self._chip_limits.set_status(f"{axis} soft-limit error", "crit")
                return
            if min(abs(value - float(lo)), abs(float(hi) - value)) <= margin_mm:
                near.append(axis)
        if near:
            self._chip_limits.set_status(
                "Near " + "/".join(near) + " soft limit", "warn")
        else:
            # Quiet nominal — inside the envelope is the normal state.
            self._chip_limits.set_status("Soft limits ok", "neutral")

    def _update_position(self) -> None:
        """Legacy stub — polling now handled by _PositionPoller in a QThread."""

    def shutdown(self) -> None:
        """Stop all worker threads — call before discarding the panel.

        Order matters (bench bug: a soft config-reload froze the panel):
          1. Pause the poller *first* (a plain bool write, safe from the GUI
             thread) so no new get_position() read can start while we tear
             down — mirrors _run_async's own set_paused(True) use.
          2. Best-effort interrupt any in-flight task (home/move) via
             motor.stop() — the same call _emergency_stop() uses, and it is
             deliberately safe/non-blocking even mid-move (see
             MotorStageBase.stop() and GRBLMotorStage.stop(), which never
             takes the command lock a running move holds).  This gives the
             bounded wait below the best chance of the worker thread
             *actually* finishing instead of merely timing out.
          3. Quit + a BOUNDED wait — never an unbounded wait, which a stuck
             serial read/long move could hang the GUI thread on.  A timeout
             here is survivable (not a freeze): both worker threads are
             parented to QApplication, not to this widget, and
             self-deleteLater() on ``finished`` (see __init__ / _run_async),
             so a thread that outlives this bounded wait cleans itself up on
             its own later instead of Qt destroying a still-running QThread
             as a side effect of this widget being deleted
             (setCentralWidget() during a soft reload) — that
             undefined-behaviour path was the actual freeze.
        """
        self._conn_timer.stop()
        self._poller.set_paused(True)
        if self._task_thread is not None and self._task_thread.isRunning():
            try:
                self._motor.stop()
            except Exception:
                logging.getLogger(__name__).debug(
                    "motor.stop() during panel shutdown failed", exc_info=True)
            self._task_thread.quit()
            self._task_thread.wait(3000)
        self._task_thread = None
        self._task = None
        self._poll_stop_requested.emit()
        self._poll_thread.quit()
        self._poll_thread.wait(3000)

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def _use_current_pos(self) -> None:
        """Copy current stage position into the absolute-move spinboxes."""
        if not self._motor.connected:
            return
        try:
            pos = self._motor.get_position()
            self._spin_x.setValue(pos.x_mm)
            self._spin_y.setValue(pos.y_mm)
            self._spin_z.setValue(pos.z_mm)
        except Exception:
            pass

    def _emit_set_as_start(self) -> None:
        """Emit set_as_scan_start with the current stage position."""
        if not self._motor.connected:
            return
        try:
            pos = self._motor.get_position()
            self.set_as_scan_start.emit(pos.x_mm, pos.y_mm, pos.z_mm)
            flash_button(self._btn_set_start, "good", "Copied")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _make_spin(self) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        # Wide enough for full printer travel (the old ±100 mm clamp made most
        # of the envelope unreachable); the motor's software limits do the real
        # bounds-checking before any move is sent.
        s.setRange(-2000.0, 2000.0)
        s.setDecimals(4)
        s.setSuffix(" mm")
        return s

    def _show_error(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Motor Error", msg)

    def set_motor(self, motor: MotorStageBase) -> None:
        """Hot-swap the motor backend at runtime."""
        self._motor = motor
        # New backend ⇒ new envelope (and possibly a new frame) — redraw so
        # the stage view never keeps showing the previous device's limits.
        self._refresh_stage_limits()
