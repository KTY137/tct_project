"""
Post-scan analysis panel.

Loads an existing HDF5 run file and provides:
  - 2-D map re-plotting with any stored quantity
  - CCE vs. bias voltage curve (from a bias scan HDF5 file)
  - Re-analysis with adjustable thresholds
  - Export analysis results to CSV
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QPushButton, QComboBox,
    QDoubleSpinBox, QFileDialog, QTabWidget,
)

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

try:
    import h5py
    _HAS_H5 = True
except ImportError:
    _HAS_H5 = False


class AnalysisPanel(QWidget):
    """Load a completed run HDF5 file and re-analyse / re-plot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: dict = {}          # loaded HDF5 data arrays
        self._run_path: str = ""
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── File loader ───────────────────────────────────────────────
        file_row = QHBoxLayout()
        self._lbl_file = QLabel("No file loaded")
        self._lbl_file.setWordWrap(True)
        btn_open = QPushButton("📂 Open HDF5 Run")
        btn_open.clicked.connect(self._open_file)
        file_row.addWidget(btn_open)
        file_row.addWidget(self._lbl_file, stretch=1)
        root.addLayout(file_row)

        inner_tabs = QTabWidget()
        root.addWidget(inner_tabs)

        # ── Tab A: 2D map re-plot ─────────────────────────────────────
        map_tab = QWidget()
        map_layout = QVBoxLayout(map_tab)
        map_ctrl = QHBoxLayout()
        map_ctrl.addWidget(QLabel("Quantity:"))
        self._combo_qty = QComboBox()
        self._combo_qty.addItems([
            "dut_charge_pC", "dut_charge_norm", "dut_amplitude_V",
            "ref_amplitude_V", "baseline_rms_V",
            "drift_time_s", "rise_time_s", "cfd_time_s",
        ])
        self._combo_qty.currentTextChanged.connect(self._replot_map)
        map_ctrl.addWidget(self._combo_qty)
        btn_replot = QPushButton("Replot")
        btn_replot.clicked.connect(self._replot_map)
        map_ctrl.addWidget(btn_replot)
        btn_export_csv = QPushButton("💾 Export CSV")
        btn_export_csv.clicked.connect(self._export_csv)
        map_ctrl.addWidget(btn_export_csv)
        map_layout.addLayout(map_ctrl)

        if _HAS_PG:
            self._map_view = pg.ImageView()
            self._map_view.setMinimumHeight(300)
            # Disable ROI rotation — only axis-aligned resize makes sense
            _roi = self._map_view.roi
            _roi.rotatable = False
            for _h in list(_roi.handles):
                if _h["type"] == "r":
                    _roi.removeHandle(_h["item"])
            map_layout.addWidget(self._map_view)
        else:
            map_layout.addWidget(QLabel("(install pyqtgraph for map display)"))

        self._lbl_map_info = QLabel("")
        map_layout.addWidget(self._lbl_map_info)
        inner_tabs.addTab(map_tab, "2D Map")

        # ── Tab B: CCE vs. bias ───────────────────────────────────────
        cce_tab = QWidget()
        cce_layout = QVBoxLayout(cce_tab)
        cce_ctrl = QFormLayout()

        self._spin_ref_charge = QDoubleSpinBox()
        self._spin_ref_charge.setRange(0.001, 1000.0)
        self._spin_ref_charge.setDecimals(3)
        self._spin_ref_charge.setValue(1.0)
        self._spin_ref_charge.setSuffix(" pC")
        self._spin_ref_charge.setToolTip(
            "Reference charge at full depletion — CCE = Q / Q_ref"
        )
        cce_ctrl.addRow("Q_ref (full depletion):", self._spin_ref_charge)

        btn_plot_cce = QPushButton("Plot CCE vs. Bias")
        btn_plot_cce.clicked.connect(self._plot_cce)
        btn_export_cce = QPushButton("💾 Export CCE CSV")
        btn_export_cce.clicked.connect(self._export_cce_csv)
        cce_btn_row = QHBoxLayout()
        cce_btn_row.addWidget(btn_plot_cce)
        cce_btn_row.addWidget(btn_export_cce)

        cce_layout.addLayout(cce_ctrl)
        cce_layout.addLayout(cce_btn_row)

        if _HAS_PG:
            self._cce_plot = pg.PlotWidget(title="CCE / Q vs. Bias Voltage")
            self._cce_plot.setLabel("left",   "CCE / Norm. Charge")
            self._cce_plot.setLabel("bottom", "Bias Voltage", units="V")
            self._cce_plot.addLegend()
            self._cce_curve_cce = self._cce_plot.plot(
                pen=pg.mkPen("g", width=2), symbol="o", symbolSize=5,
                name="CCE",
            )
            self._cce_curve_iv = self._cce_plot.plot(
                pen=pg.mkPen("r", width=1), symbol="t", symbolSize=4,
                name="Leakage (µA, scaled)",
            )
            cce_layout.addWidget(self._cce_plot)

            # V_dep estimate label
            self._lbl_vdep = QLabel("V_dep estimate: —")
            cce_layout.addWidget(self._lbl_vdep)

        inner_tabs.addTab(cce_tab, "CCE vs. Bias")

    # ------------------------------------------------------------------ #
    # File I/O                                                             #
    # ------------------------------------------------------------------ #

    def _open_file(self) -> None:
        if not _HAS_H5:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Missing dependency",
                                "h5py is not installed.\nRun: pip install h5py")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Run HDF5", "runs/", "HDF5 (*.h5 *.hdf5)"
        )
        if not path:
            return
        try:
            self._load_h5(path)
            self._run_path = path
            self._lbl_file.setText(Path(path).name)
            self._replot_map()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Load Error", str(exc))

    def _load_h5(self, path: str) -> None:
        self._data = {}
        with h5py.File(path, "r") as f:
            if "points" in f:
                pts = f["points"]
                for key in pts:
                    self._data[key] = pts[key][:]
            if "analysis" in f:
                ana = f["analysis"]
                for key in ana:
                    self._data[key] = ana[key][:]

    # ------------------------------------------------------------------ #
    # 2D map                                                               #
    # ------------------------------------------------------------------ #

    def _replot_map(self) -> None:
        if not _HAS_PG or not self._data:
            return
        qty = self._combo_qty.currentText()
        if qty not in self._data:
            self._lbl_map_info.setText(f"'{qty}' not found in file")
            return

        x = self._data.get("x_mm")
        y = self._data.get("y_mm")
        z = self._data.get(qty)
        if x is None or y is None or z is None:
            self._lbl_map_info.setText("Missing x_mm / y_mm arrays in file")
            return

        xs = np.unique(x)
        ys = np.unique(y)
        arr = np.full((len(xs), len(ys)), np.nan)
        xi = {v: i for i, v in enumerate(xs)}
        yi = {v: i for i, v in enumerate(ys)}
        for xi_, yi_, val in zip(x, y, z):
            arr[xi[xi_], yi[yi_]] = val

        self._map_view.setImage(
            np.nan_to_num(arr),
            autoRange=True,
            autoLevels=True,
            # Map pixel coordinates → mm so the built-in ROI axes show mm
            pos=(float(xs[0]), float(ys[0])),
            scale=(
                float((xs[-1] - xs[0]) / max(len(xs) - 1, 1)),
                float((ys[-1] - ys[0]) / max(len(ys) - 1, 1)),
            ),
        )
        self._lbl_map_info.setText(
            f"{qty}  |  {len(xs)} × {len(ys)} points  "
            f"|  min={np.nanmin(z):.4g}  max={np.nanmax(z):.4g}  "
            f"|  X [{xs[0]:.3f}, {xs[-1]:.3f}] mm  Y [{ys[0]:.3f}, {ys[-1]:.3f}] mm"
        )

    # ------------------------------------------------------------------ #
    # CCE vs. bias                                                         #
    # ------------------------------------------------------------------ #

    def _plot_cce(self) -> None:
        if not _HAS_PG or not self._data:
            return

        # Try to find bias voltage — stored as "bias_V" or inferred from z-scan
        voltages = self._data.get("bias_V")
        charges  = self._data.get("dut_charge_pC")
        currents = self._data.get("leakage_A")

        if voltages is None or charges is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "No bias data",
                "No 'bias_V' or 'dut_charge_pC' arrays found.\n"
                "Load a file from a voltage scan."
            )
            return

        q_ref = self._spin_ref_charge.value()
        # TCT pulses are usually negative → raw charge_pC is signed.  CCE is a
        # ratio of collected-charge magnitudes, so compare |Q| against |Q_ref|.
        cce = np.abs(np.array(charges)) / max(abs(q_ref), 1e-12)

        self._cce_curve_cce.setData(voltages, cce)

        if currents is not None:
            # Scale leakage to CCE axis for overlay
            i_ua = np.array(currents) * 1e6
            i_scaled = i_ua / max(np.max(np.abs(i_ua)), 1e-12)
            self._cce_curve_iv.setData(voltages, i_scaled)

        # Estimate V_dep: voltage where CCE reaches 98% of plateau
        try:
            from analysis.efield_analysis import estimate_depletion_voltage
            v_dep = estimate_depletion_voltage(np.array(voltages), np.array(charges))
            if v_dep is not None:
                self._lbl_vdep.setText(f"V_dep estimate: {v_dep:.1f} V")
        except Exception:
            pass

    def _export_cce_csv(self) -> None:
        if not self._data:
            return
        voltages = self._data.get("bias_V")
        charges  = self._data.get("dut_charge_pC")
        if voltages is None or charges is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CCE", "", "CSV (*.csv)")
        if not path:
            return
        q_ref = max(abs(self._spin_ref_charge.value()), 1e-12)
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["bias_V", "dut_charge_pC", "CCE"])
            for v, q in zip(voltages, charges):
                w.writerow([f"{v:.2f}", f"{q:.6f}", f"{abs(q)/q_ref:.6f}"])

    def _export_csv(self) -> None:
        """Export all loaded analysis arrays as CSV."""
        if not self._data:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Analysis", "", "CSV (*.csv)")
        if not path:
            return
        keys = list(self._data.keys())
        n = len(next(iter(self._data.values())))
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(keys)
            for i in range(n):
                w.writerow([self._data[k][i] for k in keys])
