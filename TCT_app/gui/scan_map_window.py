"""
Detachable 2-D Scan Map Window.

Opens as a standalone QMainWindow with a full-size ImageView, axis
labels in mm, a quantity selector, independent colour-scale controls,
and an export button.  It stays in sync with the live scan through
:meth:`update_point`.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFileDialog,
    QCheckBox,
)

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from gui.status_widgets import StatusChip, flash_button, set_button_icon

# Quantities available for display
_QUANTITIES = [
    "dut_charge_pC",
    "dut_charge_norm",
    "dut_amplitude_V",
    "ref_amplitude_V",
    "baseline_rms_V",
    "drift_time_s",
    "rise_time_s",
    "cfd_time_s",
]


class ScanMapWindow(QMainWindow):
    """
    Standalone window showing a 2-D scan map (one quantity at a time).

    Parameters
    ----------
    parent:
        Optional parent widget.  Pass the main window so that this
        window is raised/lowered with it.

    Usage
    -----
    window = ScanMapWindow(parent=main_window)
    window.show()
    # During scan:
    window.update_point(result)          # called per ScanResult
    # After scan or at any time:
    window.clear()
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("TCT — 2D Scan Map")
        self.resize(700, 600)

        self._map_data: dict[tuple[float, float], float] = {}
        self._x_vals: list[float] = []
        self._y_vals: list[float] = []

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ── Toolbar ────────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("Quantity:"))
        self._combo_qty = QComboBox()
        self._combo_qty.addItems(_QUANTITIES)
        self._combo_qty.currentTextChanged.connect(self._redraw)
        toolbar.addWidget(self._combo_qty)

        self._chk_auto_levels = QCheckBox("Auto levels")
        self._chk_auto_levels.setChecked(True)
        self._chk_auto_levels.toggled.connect(self._redraw)
        toolbar.addWidget(self._chk_auto_levels)
        self._chip_data = StatusChip("No data", "neutral")
        self._chip_levels = StatusChip("Auto levels", "info")
        self._chip_export = StatusChip("Export --", "neutral")
        toolbar.addWidget(self._chip_data)
        toolbar.addWidget(self._chip_levels)
        toolbar.addWidget(self._chip_export)

        btn_clear = QPushButton("Clear")
        set_button_icon(btn_clear, "mdi.delete-outline")
        btn_clear.clicked.connect(self.clear)
        toolbar.addWidget(btn_clear)

        self._btn_export_png = QPushButton("Export PNG")
        set_button_icon(self._btn_export_png, "mdi.image")
        self._btn_export_png.clicked.connect(self._export_png)
        toolbar.addWidget(self._btn_export_png)

        self._btn_export_csv = QPushButton("Export CSV")
        set_button_icon(self._btn_export_csv, "mdi.content-save")
        self._btn_export_csv.clicked.connect(self._export_csv)
        toolbar.addWidget(self._btn_export_csv)

        toolbar.addStretch()
        root.addLayout(toolbar)

        # ── Map view ───────────────────────────────────────────────────
        if _HAS_PG:
            self._img_view = pg.ImageView()

            # Disable rotation on the built-in ROI so users can only
            # resize along X or Y independently.
            _roi = self._img_view.roi
            _roi.rotatable = False
            for _h in list(_roi.handles):
                if _h["type"] == "r":
                    _roi.removeHandle(_h["item"])

            root.addWidget(self._img_view)

            # Overlay: axis labels via a PlotItem (provides axis ticks in mm)
            # We layer a transparent PlotItem on top for tick labels.
            self._plot_overlay = pg.PlotWidget()
            self._plot_overlay.setLabel("bottom", "X", units="mm")
            self._plot_overlay.setLabel("left",   "Y", units="mm")
            self._plot_overlay.setMaximumHeight(30)
            self._plot_overlay.setBackground(None)
            root.addWidget(self._plot_overlay)

            # Status bar info
            self._lbl_info = QLabel("No data")
            root.addWidget(self._lbl_info)
        else:
            root.addWidget(QLabel(
                "pyqtgraph not installed — cannot display map.\n"
                "Run:  pip install pyqtgraph"
            ))

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def update_point(self, result) -> None:
        """
        Accept one :class:`~controller.scan_controller.ScanResult` and
        refresh the map.  Safe to call from the GUI thread only.
        """
        key = (
            round(result.point.x_mm, 6),
            round(result.point.y_mm, 6),
        )
        qty = self._combo_qty.currentText()
        self._map_data[key] = getattr(result, qty, 0.0)
        self._redraw()

    def set_quantity(self, qty: str) -> None:
        """Programmatically select the displayed quantity."""
        idx = self._combo_qty.findText(qty)
        if idx >= 0:
            self._combo_qty.setCurrentIndex(idx)

    def clear(self) -> None:
        """Remove all data and reset the map."""
        self._map_data.clear()
        if _HAS_PG:
            self._img_view.clear()
            self._lbl_info.setText("No data")
        self._chip_data.set_status("No data", "neutral")
        self._chip_export.set_status("Export --", "neutral")

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    def _redraw(self) -> None:
        if not _HAS_PG or not self._map_data:
            return

        qty = self._combo_qty.currentText()
        xs = sorted({k[0] for k in self._map_data})
        ys = sorted({k[1] for k in self._map_data})

        nx, ny = len(xs), len(ys)
        arr = np.full((nx, ny), np.nan)

        xi = {v: i for i, v in enumerate(xs)}
        yi = {v: i for i, v in enumerate(ys)}
        for (x, y), val in self._map_data.items():
            arr[xi[x], yi[y]] = val

        # Replace NaN with zero for display only
        display = np.where(np.isnan(arr), 0.0, arr)

        auto = self._chk_auto_levels.isChecked()
        self._chip_levels.set_status("Auto levels" if auto else "Manual levels",
                                     "info" if auto else "neutral")
        self._img_view.setImage(
            display,
            autoRange=True,
            autoLevels=auto,
            # Map pixel positions to mm coordinates
            pos=(xs[0], ys[0]) if xs and ys else (0, 0),
            scale=(
                (xs[-1] - xs[0]) / max(nx - 1, 1) if nx > 1 else 1.0,
                (ys[-1] - ys[0]) / max(ny - 1, 1) if ny > 1 else 1.0,
            ),
        )

        n_filled = sum(1 for v in arr.flat if not np.isnan(v))
        vmin, vmax = float(np.nanmin(arr)), float(np.nanmax(arr))
        self._lbl_info.setText(
            f"{qty}  |  {n_filled}/{nx*ny} pts  |  "
            f"min={vmin:.4g}  max={vmax:.4g}  |  "
            f"X: [{xs[0]:.3f}, {xs[-1]:.3f}] mm  "
            f"Y: [{ys[0]:.3f}, {ys[-1]:.3f}] mm"
        )
        self._chip_data.set_status(f"{n_filled}/{nx*ny} pts",
                                   "good" if n_filled == nx * ny else "busy")
        self._chip_export.set_status("Export ready", "good")

    def _export_png(self) -> None:
        if not _HAS_PG:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Map as PNG", "", "PNG (*.png)"
        )
        if not path:
            return
        try:
            exporter = pg.exporters.ImageExporter(self._img_view.imageItem)
            exporter.export(path)
            flash_button(self._btn_export_png, "good", "Exported")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Error", str(exc))

    def _export_csv(self) -> None:
        if not self._map_data:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Map as CSV", "", "CSV (*.csv)"
        )
        if not path:
            return
        qty = self._combo_qty.currentText()
        try:
            import csv
            with open(path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["x_mm", "y_mm", qty])
                for (x, y), val in sorted(self._map_data.items()):
                    writer.writerow([f"{x:.6f}", f"{y:.6f}", f"{val:.8g}"])
            flash_button(self._btn_export_csv, "good", "Exported")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Error", str(exc))
