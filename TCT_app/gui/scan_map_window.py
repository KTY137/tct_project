"""
Detachable 2-D Scan Map Window.

Opens as a standalone QMainWindow embedding the shared, canonical
:class:`~gui.scan_map_view.ScanMapView` widget (quantity selector, live
map + colorbar, cursor readout — see that module's docstring for the
duplication history this replaces), plus PNG/CSV export on top.  It stays
in sync with the live scan through :meth:`update_point`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

try:
    import pyqtgraph as pg
    import pyqtgraph.exporters  # noqa: F401 — pg.exporters is not auto-imported; PNG export needs it
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from gui.scan_map_view import ScanMapView
from gui.status_widgets import StatusChip, flash_button, set_button_icon


class ScanMapWindow(QMainWindow):
    """
    Standalone window showing a 2-D scan map (one quantity at a time),
    built on the shared :class:`~gui.scan_map_view.ScanMapView` widget.

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
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ── Toolbar (export controls — the quantity selector, live map,
        # colorbar, and cursor readout all live in the embedded ScanMapView) ──
        toolbar = QHBoxLayout()
        self._chip_export = StatusChip("Export --", "neutral")
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

        # ── Shared map view ────────────────────────────────────────────
        self._map_view = ScanMapView()
        root.addWidget(self._map_view, 1)

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def update_point(self, result) -> None:
        """
        Accept one :class:`~controller.scan_controller.ScanResult` and
        refresh the map.  Safe to call from the GUI thread only.
        """
        self._map_view.update_point(result)
        self._chip_export.set_status("Export ready", "good")

    def set_quantity(self, qty: str) -> None:
        """Programmatically select the displayed quantity."""
        self._map_view.set_quantity(qty)

    def clear(self) -> None:
        """Remove all data and reset the map."""
        self._map_view.clear()
        self._chip_export.set_status("Export --", "neutral")

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve the embedded map view's cached theme pens (registers
        the same way every other panel does in ``tct_gui._toggle_theme``,
        should this window ever join that loop)."""
        self._map_view.refresh_theme(mode)

    # ------------------------------------------------------------------ #
    # Export                                                              #
    # ------------------------------------------------------------------ #

    def _export_png(self) -> None:
        if not _HAS_PG:
            return
        image_view = self._map_view.image_view()
        if image_view is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Map as PNG", "", "PNG (*.png)"
        )
        if not path:
            return
        try:
            exporter = pg.exporters.ImageExporter(image_view.imageItem)
            exporter.export(path)
            flash_button(self._btn_export_png, "good", "Exported")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Error", str(exc))

    def _export_csv(self) -> None:
        points = self._map_view.points()
        if not points:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Map as CSV", "", "CSV (*.csv)"
        )
        if not path:
            return
        qty = self._map_view.current_quantity()
        try:
            import csv
            with open(path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["x_mm", "y_mm", qty])
                for (x, y), values in sorted(points.items()):
                    val = values.get(qty, float("nan"))
                    writer.writerow([f"{x:.6f}", f"{y:.6f}", f"{val:.8g}"])
            flash_button(self._btn_export_csv, "good", "Exported")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Error", str(exc))
