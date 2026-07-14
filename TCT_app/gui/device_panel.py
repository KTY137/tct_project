"""Device Manager Window — shows connection status for every device and
allows individual connect / disconnect without touching the rest of the app.

Round-03 glass kit migration (wave beat 6/12, mirrors ``LaserPanel``/
``IntensityPanel``): the whole window body is now ONE ``GlassPane`` shelf
(chrome head + table + bulk-action card). This window is a ``QMainWindow``
top-level (a satellite, like the theme editor / settings dialog), so its own
DWM material/opacity already goes through the single entry point every other
satellite uses (``gui.style.prepare_window_surface`` +
``gui.style.reassert_window_backdrop``, both called in ``__init__`` below,
predating this migration) — nothing new invented there, only the CONTENT
inside the window's central widget changed.

Register decision: the shelf itself does **not** register — its body hosts
the live device table directly, and ``QTableWidget`` is one of the Z-ladder's
own disqualifiers (``tests/test_panel_glass_rollout.py``'s
``_glass_disqualifiers``: "Z4 live data table"). That is a *content*
consequence, not a hazard-panel blanket stance like ``BiasPanel``'s/
``SequencerPanel``'s — this window is classed non-hazard by the census, so
the pure-chrome bulk-action card (Connect All / Disconnect All — no table, no
danger control) registers instead, the same "register the specific chrome
sub-card, not the content-hosting shell" pattern ``laser_panel``/
``intensity_panel`` already use for their own hero content.

No axis-rail/hazard colour is cached anywhere in this window (no bias/motor
axis accents, no ``HazardSurface``) — every kit surface here resolves purely
through ``gui.style``'s app-wide QSS, which ``apply_theme()`` regenerates and
reapplies globally on every switch. ``refresh_theme()`` still exists (a thin
theme-mode bookkeeping hook) so this window is *wireable* into
``tct_gui._toggle_theme``'s panel fan-out the same way ``_settings_window``/
``_theme_editor`` already are — not done in this beat (see the file-scope
note in the task ledger); flagged as a handoff.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox,
)

from controller.device_manager import DeviceManager
from gui import style
from gui.app_settings import theme_mode
from gui.panel_kit import Card, GlassPane, panel_header, register_glass_pane
from gui.status_bus import notify
from gui.status_widgets import StatusChip, flash_button, set_button_busy, set_button_icon
from gui.style import ERROR_ORANGE, OK_GREEN, SIM_PURPLE, WARN_RED


_STATUS_STYLE = {
    "connected":    ("CONNECTED",    OK_GREEN),      # green
    "simulated":    ("SIMULATED",    SIM_PURPLE),    # purple
    "disconnected": ("DISCONNECTED", WARN_RED),      # red
    "error":        ("ERROR",        ERROR_ORANGE),  # orange
}

#: Qt property carrying a row button's table row, so its ``clicked`` slot can be
#: a plain bound method instead of a row-capturing lambda (which leaks the whole
#: window — see the connect/disconnect buttons in ``_build`` below).
_ROW_PROPERTY = "tctDeviceRow"


def device_state(dev) -> str:
    """Return the live state key: 'connected' | 'simulated' | 'disconnected'.

    Shared by the Device Manager table and the main-window status strip so both
    agree on what each colour means.  A device in simulation mode reports
    'simulated' (not 'connected') so it is never mistaken for real hardware.
    """
    if getattr(dev, "connected", False):
        return "simulated" if getattr(dev, "simulation", False) else "connected"
    return "disconnected"


def _device_status(dev) -> tuple[str, str]:
    """Return (label, colour) describing the device state."""
    return _STATUS_STYLE[device_state(dev)]


class _DeviceTask(QObject):
    """Runs one blocking device-manager action off the GUI thread."""

    done = Signal(object, str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn(), "")
        except Exception as exc:
            self.done.emit(None, str(exc))


class DeviceManagerWindow(QMainWindow):
    """
    Floating window listing all hardware devices with:
      • live status badge (Connected / Simulated / Disconnected)
      • Connect / Disconnect buttons per device
      • Auto-refresh every second
    """

    def __init__(self, devices: DeviceManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Alpha-capable surface BEFORE any child exists (a child that realizes
        # the HWND first would lock this window out of per-pixel alpha for good —
        # see gui.style.prepare_window_surface). No-op with the "none" default.
        style.prepare_window_surface(self)
        self.setWindowTitle("Device Manager")
        self.resize(620, 380)
        self._devices = devices
        self._last_errors: dict[str, str] = {}
        self._bg_thread: QThread | None = None
        self._bg_task: _DeviceTask | None = None
        self._bg_on_done = None
        # Theme mode for the kit surfaces below (header mark / refresh_theme
        # bookkeeping) — read once from the same QSettings key main.py/
        # tct_gui.py use, mirroring BiasPanel/LaserPanel/IntensityPanel.
        self._theme_mode = theme_mode()
        self._build_ui()
        # Same cockpit material + opacity + event-spine guard as every other
        # satellite window (theme editor, settings, torn-off panels) — through
        # the one entry point, AFTER _build_ui() so the central widget exists:
        # a QMainWindow's client is painted by that child, and it has to go
        # translucent too or no alpha ever reaches DWM (see
        # gui.backdrop._canvas_widgets). A true no-op headless / pre-Win11 22H2.
        style.reassert_window_backdrop(self)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(1000)

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ── The one shelf (round-03 kit §2.1) ──────────────────────────
        # register=False is a CONTENT consequence (the live device table
        # below is a Z4 disqualifier — see the module docstring), not a
        # hazard-panel blanket stance; the bulk-action card further down
        # registers instead.
        shelf = GlassPane(register=False)
        self._shelf = shelf

        # ── Pane head: eyebrow + title + the two status chips (chrome) ──
        self._chip_summary = StatusChip("Devices idle", "neutral")
        self._chip_busy = StatusChip("Idle", "neutral")
        shelf.add_widget(panel_header(
            "TCT Control · Devices", "Device Manager",
            trailing=[self._chip_summary, self._chip_busy],
            theme_mode=self._theme_mode))

        # ── Table: Name | Status | Simulation | Connect | Disconnect ────
        # QTableWidget is one of the Z-ladder's own disqualifiers ("Z4 live
        # data table" — tests/test_panel_glass_rollout.py), so this card
        # stays an opaque cardPane surface at every tier and is never
        # registered, independent of the window's non-hazard classification.
        table_card = Card("Hardware devices")
        self._table_card = table_card
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Device", "Status", "Sim Mode", "Connect", "Disconnect"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.verticalHeader().setVisible(False)
        table_card.add_widget(self._table)
        # Stretch=1 on the shelf's own body slot (Card.add_widget has no
        # stretch parameter — same idiom IntensityPanel uses for its own
        # hero content) so the table grows to fill the window.
        shelf.body.addWidget(table_card, 1)

        # ── Bulk actions (pure chrome — no table, no danger control) ────
        # The dynamic per-row Connect/Disconnect buttons stay OUT of this
        # card (and out of an ActionBar — their gating/enable state is wired
        # in _populate_rows/_set_busy exactly as before); this card is only
        # the two "All" buttons, which is why it is the one surface here
        # that registers for glass.
        action_card = Card("Bulk actions")
        self._action_card = action_card
        bottom = QHBoxLayout()
        self._btn_connect_all = QPushButton("Connect All")
        set_button_icon(self._btn_connect_all, "mdi.lan-connect")
        self._btn_connect_all.clicked.connect(self._connect_all)
        self._btn_disconnect_all = QPushButton("Disconnect All")
        set_button_icon(self._btn_disconnect_all, "mdi.lan-disconnect")
        self._btn_disconnect_all.clicked.connect(self._disconnect_all)
        bottom.addWidget(self._btn_connect_all)
        bottom.addWidget(self._btn_disconnect_all)
        bottom.addStretch()
        action_card.add_layout(bottom)
        register_glass_pane(action_card)
        shelf.add_widget(action_card)

        # The one shelf now holds the whole window body (head + table +
        # bulk actions); it grows with the window so the table can too.
        root.addWidget(shelf, 1)

        self._populate_rows()
        self._refresh()

    # ------------------------------------------------------------------ #
    # Theme                                                               #
    # ------------------------------------------------------------------ #

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve theme-mode bookkeeping after a light/dark switch.

        Nothing in this window caches an axis-rail/hazard colour at
        construction time (no bias/motor accents, no ``HazardSurface``) — the
        Card/GlassPane header and every status chip resolve purely through
        ``gui.style``'s app-wide QSS, which ``apply_theme()`` regenerates and
        reapplies globally on every switch (the same "nothing to re-resolve"
        case as ``IntensityPanel``). This hook exists so the window CAN be
        wired into ``tct_gui._toggle_theme``'s panel fan-out the same way
        ``_settings_window``/``_theme_editor`` already are.
        """
        if mode:
            self._theme_mode = str(mode)

    def _populate_rows(self) -> None:
        """Create one row per device (buttons only created once)."""
        named = self._devices.named_devices()
        self._table.setRowCount(len(named))
        self._row_map: dict[int, str] = {}   # row → device name
        self._row_buttons: list[QPushButton] = []

        for row, (name, dev) in enumerate(named.items()):
            self._row_map[row] = name

            # Name
            item_name = QTableWidgetItem(name)
            item_name.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self._table.setItem(row, 0, item_name)

            # Status label (updated in _refresh)
            lbl_status = StatusChip("-", "neutral", min_width=108)
            lbl_status.setAlignment(Qt.AlignCenter)
            self._table.setCellWidget(row, 1, lbl_status)

            # Simulation badge
            is_sim = bool(getattr(dev, "simulation", False))
            lbl_sim = StatusChip("Sim" if is_sim else "Real",
                                 "simulated" if is_sim else "neutral",
                                 min_width=64)
            lbl_sim.setAlignment(Qt.AlignCenter)
            self._table.setCellWidget(row, 2, lbl_sim)

            # Connect / Disconnect buttons.
            #
            # The row travels on the BUTTON (a Qt property), not in a lambda's
            # closure. ``lambda _, r=row: self._connect_one(r)`` captured
            # ``self`` and was stored strongly inside the button's C++
            # connection list — panel -> table -> button -> connection ->
            # closure -> panel, a cycle whose Qt hop gc cannot traverse, so the
            # whole window leaked. A bound-method slot is held weakly.
            # See tests/test_no_immortal_panels.py.
            btn_conn = QPushButton("Connect")
            set_button_icon(btn_conn, "mdi.lan-connect")
            btn_conn.setProperty(_ROW_PROPERTY, row)
            btn_conn.clicked.connect(self._on_connect_clicked)
            self._table.setCellWidget(row, 3, btn_conn)
            self._row_buttons.append(btn_conn)

            # Disconnect button
            btn_disc = QPushButton("Disconnect")
            set_button_icon(btn_disc, "mdi.lan-disconnect")
            btn_disc.setProperty(_ROW_PROPERTY, row)
            btn_disc.clicked.connect(self._on_disconnect_clicked)
            self._table.setCellWidget(row, 4, btn_disc)
            self._row_buttons.append(btn_disc)

        self._table.resizeRowsToContents()

    def _sender_row(self) -> int | None:
        """The table row of the button that emitted the signal being handled."""
        button = self.sender()
        if button is None:
            return None
        row = button.property(_ROW_PROPERTY)
        return None if row is None else int(row)

    def _on_connect_clicked(self) -> None:
        row = self._sender_row()
        if row is not None:
            self._connect_one(row)

    def _on_disconnect_clicked(self) -> None:
        row = self._sender_row()
        if row is not None:
            self._disconnect_one(row)

    # ------------------------------------------------------------------ #
    # Refresh                                                             #
    # ------------------------------------------------------------------ #

    def _refresh(self) -> None:
        named = self._devices.named_devices()
        connected = 0
        simulated = 0
        for row, name in self._row_map.items():
            dev = named[name]
            state = device_state(dev)
            label, _colour = _device_status(dev)
            if state == "connected":
                connected += 1
            elif state == "simulated":
                connected += 1
                simulated += 1
            lbl: StatusChip = self._table.cellWidget(row, 1)
            err = self._last_errors.get(name, "")
            lbl.set_status(label, state, err or label.title())
            # Update sim badge in case it changed at runtime
            is_sim = bool(getattr(dev, "simulation", False))
            lbl_sim: StatusChip = self._table.cellWidget(row, 2)
            lbl_sim.set_status("Sim" if is_sim else "Real",
                               "simulated" if is_sim else "neutral")
        total = len(named)
        if connected == 0:
            self._chip_summary.set_status(f"0/{total} connected", "neutral")
        elif connected == total and simulated:
            self._chip_summary.set_status(f"{connected}/{total} connected, {simulated} sim", "simulated")
        elif connected == total:
            # Quiet nominal (law 1): all-connected is routine, not a green
            # light -- state-color census D4 rank-1 hit (this was still
            # "good"/green; matches the fix multi_bias_panel.py's own
            # channel-summary chip already carries).
            self._chip_summary.set_status(f"{connected}/{total} connected", "neutral")
        else:
            self._chip_summary.set_status(f"{connected}/{total} connected", "warn")

    # ------------------------------------------------------------------ #
    # Actions                                                             #
    # ------------------------------------------------------------------ #

    def _connect_one(self, row: int) -> None:
        name = self._row_map[row]
        self._run_bg(
            lambda: (name, self._devices.connect_device(name)),
            lambda result, err: self._on_one_done("Connect", result, err),
        )

    def _disconnect_one(self, row: int) -> None:
        name = self._row_map[row]
        self._run_bg(
            lambda: (name, self._devices.disconnect_device(name)),
            lambda result, err: self._on_one_done("Disconnect", result, err),
        )

    def _connect_all(self) -> None:
        self._run_bg(self._devices.connect_all, self._on_connect_all_done)

    def _disconnect_all(self) -> None:
        self._run_bg(self._devices.disconnect_all, self._on_disconnect_all_done)

    def _run_bg(self, fn, on_done) -> bool:
        # One device operation at a time (single slot, no arbitrary-depth
        # queue).  Surface the busy state instead of the old silent no-op —
        # the "clicking Connect/Disconnect does nothing" bench report.
        if self._bg_thread is not None and self._bg_thread.isRunning():
            notify("Device Manager is still busy — wait for the current "
                   "connect/disconnect to finish.", "warn")
            self._chip_busy.set_status("Still working…", "busy",
                                       "A device operation is already running.")
            return False
        self._set_busy(True)
        self._bg_task = _DeviceTask(fn)
        self._bg_thread = QThread(self)
        self._bg_on_done = on_done
        self._bg_task.moveToThread(self._bg_thread)
        self._bg_thread.started.connect(self._bg_task.run)
        # Receiver MUST be a bound method of this GUI-thread QObject.  A bare
        # closure has no receiver QObject, so PySide6 delivers ``done`` on the
        # *worker* thread (the sender was moveToThread'd) — running _set_busy,
        # _refresh panel rebuilds and a modal QMessageBox off the GUI thread
        # (the intermittent crash + hard freeze; Paul's thread-id probe,
        # 2026-07-14).  A bound method routes queued delivery to this window's
        # (GUI) thread.
        self._bg_task.done.connect(self._bg_finished, Qt.QueuedConnection)
        self._bg_thread.start()
        return True

    def _bg_finished(self, result, err) -> None:
        """Runs on the GUI thread (bound-method receiver + queued delivery).

        The worker has already emitted ``done`` and is unwinding, so quitting/
        waiting on it here can never deadlock (unlike the old closure, where the
        worker waited on itself)."""
        thread = self._bg_thread
        on_done = self._bg_on_done
        self._bg_thread = None
        self._bg_task = None
        self._bg_on_done = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)
        self._set_busy(False)
        if on_done is not None:
            on_done(result, err)

    def _set_busy(self, busy: bool) -> None:
        self._chip_busy.set_status("Working..." if busy else "Idle",
                                   "busy" if busy else "neutral")
        self._table.setEnabled(not busy)
        set_button_busy(self._btn_connect_all, busy, "Connecting...")
        set_button_busy(self._btn_disconnect_all, busy, "Disconnecting...")
        for btn in self._row_buttons:
            btn.setEnabled(not busy)

    def _on_one_done(self, action: str, result, err: str) -> None:
        self._refresh()
        if err:
            if result and isinstance(result, tuple):
                self._last_errors[str(result[0])] = err
            QMessageBox.critical(self, f"{action} Failed", err)
            return
        name, status = result
        if status != "ok":
            self._last_errors[name] = str(status)
            QMessageBox.warning(self, f"{action} Failed", f"{name}:\n{status}")
        else:
            self._last_errors.pop(name, None)

    def _on_connect_all_done(self, results, err: str) -> None:
        self._refresh()
        if err:
            self._last_errors["Connect All"] = err
            QMessageBox.critical(self, "Connect All", err)
            return
        failed = {k: v for k, v in (results or {}).items() if v != "ok"}
        if failed:
            self._last_errors.update({k: str(v) for k, v in failed.items()})
            detail = "\n".join(f"  {k}: {v}" for k, v in failed.items())
            QMessageBox.warning(self, "Connect All", f"Some failed:\n{detail}")
        else:
            self._last_errors.clear()
            flash_button(self._btn_connect_all)

    def _on_disconnect_all_done(self, _result, err: str) -> None:
        self._refresh()
        if err:
            self._last_errors["Disconnect All"] = err
            QMessageBox.warning(self, "Disconnect All", err)
        else:
            flash_button(self._btn_disconnect_all)

    def showEvent(self, event) -> None:
        self._refresh_timer.start(1000)
        self._refresh()
        super().showEvent(event)

    def shutdown(self) -> None:
        self._refresh_timer.stop()
        try:
            if self._bg_thread is not None and self._bg_thread.isRunning():
                self._bg_thread.quit()
                self._bg_thread.wait(2000)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        # Hide rather than destroy — avoids a dead C++ wrapper when re-opened.
        self._refresh_timer.stop()
        event.ignore()
        self.hide()
