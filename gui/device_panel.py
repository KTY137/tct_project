"""Device Manager Window — shows connection status for every device and
allows individual connect / disconnect without touching the rest of the app."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox,
)

from controller.device_manager import DeviceManager


_STATUS_STYLE = {
    "connected":    ("CONNECTED",    "#27ae60"),   # green
    "simulated":    ("SIMULATED",    "#8e44ad"),   # purple
    "disconnected": ("DISCONNECTED", "#c0392b"),   # red
    "error":        ("ERROR",        "#e67e22"),   # orange
}


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
        self.setWindowTitle("Device Manager")
        self.resize(620, 380)
        self._devices = devices
        self._bg_thread: QThread | None = None
        self._bg_task: _DeviceTask | None = None
        self._build_ui()

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

        box = QGroupBox("Hardware Devices")
        root.addWidget(box)
        box_layout = QVBoxLayout(box)

        # Table: Name | Status | Simulation | Connect | Disconnect
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
        box_layout.addWidget(self._table)

        # Bottom row
        bottom = QHBoxLayout()
        self._btn_connect_all = QPushButton("Connect All")
        self._btn_connect_all.clicked.connect(self._connect_all)
        self._btn_disconnect_all = QPushButton("Disconnect All")
        self._btn_disconnect_all.clicked.connect(self._disconnect_all)
        bottom.addWidget(self._btn_connect_all)
        bottom.addWidget(self._btn_disconnect_all)
        bottom.addStretch()
        root.addLayout(bottom)

        self._populate_rows()
        self._refresh()

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
            lbl_status = QLabel("—")
            lbl_status.setAlignment(Qt.AlignCenter)
            lbl_status.setAutoFillBackground(True)
            self._table.setCellWidget(row, 1, lbl_status)

            # Simulation badge
            sim_text = "Yes" if getattr(dev, "simulation", False) else "No"
            lbl_sim = QLabel(sim_text)
            lbl_sim.setAlignment(Qt.AlignCenter)
            self._table.setCellWidget(row, 2, lbl_sim)

            # Connect button
            btn_conn = QPushButton("Connect")
            btn_conn.clicked.connect(lambda _, r=row: self._connect_one(r))
            self._table.setCellWidget(row, 3, btn_conn)
            self._row_buttons.append(btn_conn)

            # Disconnect button
            btn_disc = QPushButton("Disconnect")
            btn_disc.clicked.connect(lambda _, r=row: self._disconnect_one(r))
            self._table.setCellWidget(row, 4, btn_disc)
            self._row_buttons.append(btn_disc)

        self._table.resizeRowsToContents()

    # ------------------------------------------------------------------ #
    # Refresh                                                             #
    # ------------------------------------------------------------------ #

    def _refresh(self) -> None:
        named = self._devices.named_devices()
        for row, name in self._row_map.items():
            dev = named[name]
            label, colour = _device_status(dev)
            lbl: QLabel = self._table.cellWidget(row, 1)
            lbl.setText(label)
            lbl.setStyleSheet(
                f"background-color: {colour}; color: white; "
                "border-radius: 4px; padding: 2px 6px; font-weight: bold;"
            )
            # Update sim badge in case it changed at runtime
            lbl_sim: QLabel = self._table.cellWidget(row, 2)
            lbl_sim.setText("Yes" if getattr(dev, "simulation", False) else "No")

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
        if self._bg_thread is not None and self._bg_thread.isRunning():
            return False
        self._set_busy(True)
        self._bg_task = _DeviceTask(fn)
        self._bg_thread = QThread(self)
        self._bg_task.moveToThread(self._bg_thread)
        self._bg_thread.started.connect(self._bg_task.run)

        def _finish(result, err):
            thread = self._bg_thread
            self._bg_thread = None
            self._bg_task = None
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            self._set_busy(False)
            on_done(result, err)

        self._bg_task.done.connect(_finish)
        self._bg_thread.start()
        return True

    def _set_busy(self, busy: bool) -> None:
        self._table.setEnabled(not busy)
        self._btn_connect_all.setEnabled(not busy)
        self._btn_disconnect_all.setEnabled(not busy)
        for btn in self._row_buttons:
            btn.setEnabled(not busy)

    def _on_one_done(self, action: str, result, err: str) -> None:
        self._refresh()
        if err:
            QMessageBox.critical(self, f"{action} Failed", err)
            return
        name, status = result
        if status != "ok":
            QMessageBox.warning(self, f"{action} Failed", f"{name}:\n{status}")

    def _on_connect_all_done(self, results, err: str) -> None:
        self._refresh()
        if err:
            QMessageBox.critical(self, "Connect All", err)
            return
        failed = {k: v for k, v in (results or {}).items() if v != "ok"}
        if failed:
            detail = "\n".join(f"  {k}: {v}" for k, v in failed.items())
            QMessageBox.warning(self, "Connect All", f"Some failed:\n{detail}")

    def _on_disconnect_all_done(self, _result, err: str) -> None:
        self._refresh()
        if err:
            QMessageBox.warning(self, "Disconnect All", err)

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
