"""Scan configuration and live 2-D map panel."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QDoubleSpinBox, QSpinBox,
    QPushButton, QComboBox, QFileDialog,
)

from gui.scan_map_window import ScanMapWindow

try:
    import pyqtgraph as pg
    import numpy as np
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from controller.scan_controller import ScanConfig, ScanResult, ZFocusScanConfig, VoltageScanConfig


class ScanPanel(QWidget):
    """
    Scan parameter form + live 2-D map updated point-by-point.

    Emits start_requested(ScanConfig) and abort_requested() so the main
    window can connect these to the ScanController without any logic
    living in the GUI.
    """

    start_requested   = Signal(ScanConfig)
    abort_requested   = Signal()
    pause_requested   = Signal(bool)   # True = pause, False = resume
    z_focus_requested = Signal(ZFocusScanConfig)
    vscan_requested   = Signal(VoltageScanConfig)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._map_data: dict[tuple[float, float], float] = {}
        self._map_window: ScanMapWindow | None = None
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Scan parameters ───────────────────────────────────────────
        cfg_box = QGroupBox("Scan Parameters")
        form = QFormLayout(cfg_box)

        self._spin_x0  = self._make_spin(-1.0)
        self._spin_x1  = self._make_spin(1.0)
        self._spin_dx  = self._make_spin(0.1, lo=0.001, hi=10.0)
        self._spin_y0  = self._make_spin(-1.0)
        self._spin_y1  = self._make_spin(1.0)
        self._spin_dy  = self._make_spin(0.1, lo=0.001, hi=10.0)
        self._spin_z   = self._make_spin(0.0, lo=-10.0, hi=10.0)
        self._spin_nav = QSpinBox()
        self._spin_nav.setRange(1, 1000)
        self._spin_nav.setValue(1)
        self._spin_settle = self._make_spin(0.05, lo=0.0, hi=5.0)

        form.addRow("X start (mm):", self._spin_x0)
        form.addRow("X stop  (mm):", self._spin_x1)
        form.addRow("X step  (mm):", self._spin_dx)
        form.addRow("Y start (mm):", self._spin_y0)
        form.addRow("Y stop  (mm):", self._spin_y1)
        form.addRow("Y step  (mm):", self._spin_dy)
        form.addRow("Z (mm):",       self._spin_z)
        form.addRow("Averages:",     self._spin_nav)
        form.addRow("Settle (s):",   self._spin_settle)

        # Estimated time label
        self._lbl_eta = QLabel("Est. time: —")
        for sp in (self._spin_x0, self._spin_x1, self._spin_dx,
                   self._spin_y0, self._spin_y1, self._spin_dy,
                   self._spin_settle):
            sp.valueChanged.connect(self._update_eta)
        self._spin_nav.valueChanged.connect(self._update_eta)
        form.addRow(self._lbl_eta)

        # Save / load buttons
        io_row = QHBoxLayout()
        btn_save = QPushButton("💾 Save Params")
        btn_save.clicked.connect(self._save_params)
        btn_load = QPushButton("📂 Load Params")
        btn_load.clicked.connect(self._load_params)
        io_row.addWidget(btn_save)
        io_row.addWidget(btn_load)
        form.addRow(io_row)
        root.addWidget(cfg_box)

        # ── Map quantity selector ─────────────────────────────────────
        map_row = QHBoxLayout()
        map_row.addWidget(QLabel("Map:"))
        self._combo_map = QComboBox()
        self._combo_map.addItems([
            "dut_charge_pC", "dut_charge_norm",
            "dut_amplitude_V", "ref_amplitude_V", "baseline_rms_V",
            "drift_time_s", "rise_time_s", "cfd_time_s",
        ])
        self._combo_map.currentTextChanged.connect(self._redraw_map)
        map_row.addWidget(self._combo_map)
        btn_open_map = QPushButton("⊞ Open 2D Map Window")
        btn_open_map.setToolTip("Open the scan map in a separate, resizable window")
        btn_open_map.clicked.connect(self._open_map_window)
        map_row.addWidget(btn_open_map)
        root.addLayout(map_row)

        # ── Live map ──────────────────────────────────────────────────
        if _HAS_PG:
            self._img_view = pg.ImageView()
            self._img_view.setMinimumHeight(250)
            # Disable ROI rotation — only axis-aligned resizing is meaningful
            # for a rectangular scan area.  Remove the rotation handle that
            # pyqtgraph adds by default to the ImageView ROI.
            roi = self._img_view.roi
            roi.rotatable = False
            for h in list(roi.handles):
                if h["type"] == "r":
                    roi.removeHandle(h["item"])
            root.addWidget(self._img_view)
        else:
            root.addWidget(QLabel("(install pyqtgraph for live map)"))

        # ── Progress ──────────────────────────────────────────────────
        self._lbl_progress = QLabel("Ready")
        root.addWidget(self._lbl_progress)

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("▶ Start Scan")
        self._btn_start.clicked.connect(self._emit_start)
        self._btn_pause = QPushButton("⏸ Pause")
        self._btn_pause.setEnabled(False)
        self._btn_pause.setCheckable(True)
        self._btn_pause.toggled.connect(self._on_pause_toggled)
        self._btn_abort = QPushButton("⏹ Abort")
        self._btn_abort.clicked.connect(self.abort_requested.emit)
        self._btn_abort.setEnabled(False)
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_pause)
        btn_row.addWidget(self._btn_abort)
        root.addLayout(btn_row)

        # ── Z-focus (focal-point calibration) ──────────────────────────────
        zf_box = QGroupBox("Z-Focus (Focal-Point Calibration)")
        zf_box.setCheckable(True)
        zf_box.setChecked(False)   # collapsed by default
        zf_form = QFormLayout(zf_box)

        # Mode selector
        self._zf_mode = QComboBox()
        self._zf_mode.addItem("Edge scan — sharpness (recommended)", "edge_scan")
        self._zf_mode.addItem("Amplitude max (legacy)", "amplitude")
        self._zf_mode.currentIndexChanged.connect(self._on_zf_mode_changed)
        zf_form.addRow("Mode:", self._zf_mode)

        self._zf_y       = self._make_spin(0.0)
        self._zf_z0      = self._make_spin(-2.0, lo=-30.0, hi=30.0)
        self._zf_z1      = self._make_spin( 2.0, lo=-30.0, hi=30.0)
        self._zf_dz      = self._make_spin( 0.1, lo=0.001, hi=5.0)
        self._zf_nav     = QSpinBox(); self._zf_nav.setRange(1, 100); self._zf_nav.setValue(3)
        self._zf_settle  = self._make_spin(0.05, lo=0.0, hi=5.0)

        zf_form.addRow("Y (mm):",        self._zf_y)
        zf_form.addRow("Z start (mm):",  self._zf_z0)
        zf_form.addRow("Z stop  (mm):",  self._zf_z1)
        zf_form.addRow("Z step  (mm):",  self._zf_dz)
        zf_form.addRow("Averages:",       self._zf_nav)
        zf_form.addRow("Settle (s):",     self._zf_settle)

        # ── Edge-scan parameters (shown only in edge_scan mode) ───────
        from PySide6.QtWidgets import QFrame
        self._zf_edge_frame = QFrame()
        edge_form = QFormLayout(self._zf_edge_frame)
        edge_form.setContentsMargins(0, 0, 0, 0)

        self._zf_edge_center = self._make_spin(0.0)
        self._zf_edge_range  = self._make_spin(0.1, lo=0.001, hi=10.0)
        self._zf_edge_step   = self._make_spin(0.005, lo=0.001, hi=1.0)

        edge_form.addRow("Edge X centre (mm):", self._zf_edge_center)
        edge_form.addRow("Edge X range  (mm):", self._zf_edge_range)
        edge_form.addRow("Edge X step   (mm):", self._zf_edge_step)

        zf_form.addRow(self._zf_edge_frame)

        # ── Amplitude mode: fixed X ────────────────────────────────────
        self._zf_amp_frame = QFrame()
        amp_form = QFormLayout(self._zf_amp_frame)
        amp_form.setContentsMargins(0, 0, 0, 0)
        self._zf_x = self._make_spin(0.0)
        amp_form.addRow("X (mm):", self._zf_x)
        self._zf_amp_frame.setVisible(False)
        zf_form.addRow(self._zf_amp_frame)

        self._lbl_best_z = QLabel("Best Z: —")
        zf_form.addRow(self._lbl_best_z)

        # Plot: sharpness (edge mode) or amplitude (amplitude mode) vs Z
        if _HAS_PG:
            self._zf_plot  = pg.PlotWidget(title="Edge sharpness vs Z")
            self._zf_plot.setLabel("left",   "Sharpness (pC/mm)")
            self._zf_plot.setLabel("bottom", "Z", units="mm")
            self._zf_plot.setMaximumHeight(150)
            self._zf_curve = self._zf_plot.plot(pen=pg.mkPen("g", width=2))
            self._zf_marker = pg.InfiniteLine(angle=90, movable=False,
                                              pen=pg.mkPen("r", width=2))
            self._zf_marker.setVisible(False)
            self._zf_plot.addItem(self._zf_marker)
            zf_form.addRow(self._zf_plot)
            self._zf_z_data: list[float] = []
            self._zf_a_data: list[float] = []

        self._btn_zf_start = QPushButton("▶ Find Focus")
        self._btn_zf_start.clicked.connect(self._emit_z_focus)
        zf_form.addRow(self._btn_zf_start)

        root.addWidget(zf_box)

    # ------------------------------------------------------------------ #
    # Public API called by ScanController callbacks                       #
    # ------------------------------------------------------------------ #

    def on_point_done(self, result: ScanResult) -> None:
        key = (round(result.point.x_mm, 6), round(result.point.y_mm, 6))
        qty = self._combo_map.currentText()
        self._map_data[key] = getattr(result, qty, 0.0)
        self._redraw_map()
        # Forward to detached map window if open
        if self._map_window is not None and self._map_window.isVisible():
            self._map_window.update_point(result)

    def on_progress(self, done: int, total: int) -> None:
        self._lbl_progress.setText(f"Point {done} / {total}")

    def on_scan_started(self) -> None:
        self._btn_start.setEnabled(False)
        self._btn_abort.setEnabled(True)
        self._btn_pause.setEnabled(True)
        self._btn_pause.setChecked(False)

    def on_scan_finished(self) -> None:
        self._btn_start.setEnabled(True)
        self._btn_abort.setEnabled(False)
        self._btn_pause.setEnabled(False)
        self._btn_pause.setChecked(False)

    def _on_pause_toggled(self, paused: bool) -> None:
        self._btn_pause.setText("▶ Resume" if paused else "⏸ Pause")
        # Only forward user-initiated toggles while a scan is running (the
        # programmatic un-check in on_scan_started/finished must not resume).
        if self._btn_pause.isEnabled():
            self.pause_requested.emit(paused)

    def set_start_position(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        """Called by motor panel ‘Set as Scan Start’ button."""
        self._spin_x0.setValue(x_mm)
        self._spin_y0.setValue(y_mm)
        self._spin_z.setValue(z_mm)

    # ── Z-focus callbacks ────────────────────────────────────────────
    def on_z_focus_point(self, z_mm: float, amplitude_V: float) -> None:
        """Called by ScanController for each Z step during a focus scan."""
        if not _HAS_PG:
            return
        self._zf_z_data.append(z_mm)
        self._zf_a_data.append(amplitude_V)
        self._zf_curve.setData(self._zf_z_data, self._zf_a_data)

    def on_z_focus_done(self, best_z_mm: float) -> None:
        """Called when focus scan finishes with the optimal Z position."""
        mode = self._zf_mode.currentData()
        mode_label = "edge scan" if mode == "edge_scan" else "amplitude"
        self._lbl_best_z.setText(f"Best Z: {best_z_mm:.3f} mm  ({mode_label})")
        if _HAS_PG:
            self._zf_marker.setValue(best_z_mm)
            self._zf_marker.setVisible(True)
        self._spin_z.setValue(best_z_mm)

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    def _open_map_window(self) -> None:
        """Open (or raise) the detachable 2D scan map window."""
        if self._map_window is None:
            self._map_window = ScanMapWindow(parent=self.window())
        # Sync current quantity selection
        self._map_window.set_quantity(self._combo_map.currentText())
        # Pre-populate with any data already collected this session
        if self._map_data:
            self._map_window.clear()

            class _FakeResult:
                """Minimal shim so ScanMapWindow.update_point works."""
                def __init__(self, x, y, val, qty):
                    from controller.scan_controller import ScanPoint
                    self.point = ScanPoint(x_mm=x, y_mm=y, z_mm=0.0, index=0)
                    setattr(self, qty, val)

            qty = self._combo_map.currentText()
            for (x, y), val in self._map_data.items():
                self._map_window.update_point(_FakeResult(x, y, val, qty))

        self._map_window.show()
        self._map_window.raise_()
        self._map_window.activateWindow()

    def _on_zf_mode_changed(self) -> None:
        mode = self._zf_mode.currentData()
        is_edge = (mode == "edge_scan")
        self._zf_edge_frame.setVisible(is_edge)
        self._zf_amp_frame.setVisible(not is_edge)
        if _HAS_PG:
            if is_edge:
                self._zf_plot.setTitle("Edge sharpness vs Z")
                self._zf_plot.setLabel("left", "Sharpness (pC/mm)")
            else:
                self._zf_plot.setTitle("Amplitude vs Z")
                self._zf_plot.setLabel("left", "Amplitude", units="V")

    def _emit_z_focus(self) -> None:
        self._zf_z_data = []
        self._zf_a_data = []
        mode = self._zf_mode.currentData()
        cfg = ZFocusScanConfig(
            mode=mode,
            x_mm=self._zf_x.value() if mode == "amplitude" else self._zf_edge_center.value(),
            y_mm=self._zf_y.value(),
            z_start_mm=self._zf_z0.value(),
            z_stop_mm=self._zf_z1.value(),
            z_step_mm=self._zf_dz.value(),
            n_averages=self._zf_nav.value(),
            settle_time_s=self._zf_settle.value(),
            x_edge_center_mm=self._zf_edge_center.value(),
            x_edge_range_mm=self._zf_edge_range.value(),
            x_edge_step_mm=self._zf_edge_step.value(),
        )
        self.z_focus_requested.emit(cfg)

    def _update_eta(self) -> None:
        """Recompute and display estimated scan time."""
        import math
        nx = max(1, math.ceil(
            (self._spin_x1.value() - self._spin_x0.value()) / max(self._spin_dx.value(), 1e-9)
        ) + 1)
        ny = max(1, math.ceil(
            (self._spin_y1.value() - self._spin_y0.value()) / max(self._spin_dy.value(), 1e-9)
        ) + 1)
        n_pts = nx * ny
        # rough estimate: settle_time + ~0.2 s per average for waveform acquisition
        t_per_pt = self._spin_settle.value() + 0.2 * self._spin_nav.value()
        total_s = n_pts * t_per_pt
        if total_s < 60:
            eta_str = f"{total_s:.0f} s"
        elif total_s < 3600:
            eta_str = f"{total_s/60:.1f} min"
        else:
            eta_str = f"{total_s/3600:.1f} h"
        self._lbl_eta.setText(f"Est. time: {n_pts} pts × {t_per_pt:.2f} s ≈ {eta_str}")

    def _save_params(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Scan Parameters", "", "JSON (*.json)"
        )
        if not path:
            return
        params = {
            "x_start_mm": self._spin_x0.value(),
            "x_stop_mm":  self._spin_x1.value(),
            "x_step_mm":  self._spin_dx.value(),
            "y_start_mm": self._spin_y0.value(),
            "y_stop_mm":  self._spin_y1.value(),
            "y_step_mm":  self._spin_dy.value(),
            "z_mm":       self._spin_z.value(),
            "n_averages": self._spin_nav.value(),
            "settle_time_s": self._spin_settle.value(),
        }
        Path(path).write_text(json.dumps(params, indent=2))

    def _load_params(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Scan Parameters", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            params = json.loads(Path(path).read_text())
            self._spin_x0.setValue(params.get("x_start_mm", self._spin_x0.value()))
            self._spin_x1.setValue(params.get("x_stop_mm",  self._spin_x1.value()))
            self._spin_dx.setValue(params.get("x_step_mm",  self._spin_dx.value()))
            self._spin_y0.setValue(params.get("y_start_mm", self._spin_y0.value()))
            self._spin_y1.setValue(params.get("y_stop_mm",  self._spin_y1.value()))
            self._spin_dy.setValue(params.get("y_step_mm",  self._spin_dy.value()))
            self._spin_z.setValue( params.get("z_mm",        self._spin_z.value()))
            self._spin_nav.setValue(int(params.get("n_averages", self._spin_nav.value())))
            self._spin_settle.setValue(params.get("settle_time_s", self._spin_settle.value()))
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Load Error", str(exc))

    def _emit_start(self) -> None:
        cfg = ScanConfig(
            x_start_mm=self._spin_x0.value(),
            x_stop_mm=self._spin_x1.value(),
            x_step_mm=self._spin_dx.value(),
            y_start_mm=self._spin_y0.value(),
            y_stop_mm=self._spin_y1.value(),
            y_step_mm=self._spin_dy.value(),
            z_mm=self._spin_z.value(),
            n_averages=self._spin_nav.value(),
            settle_time_s=self._spin_settle.value(),
        )
        self.start_requested.emit(cfg)

    def _redraw_map(self) -> None:
        if not _HAS_PG or not self._map_data:
            return
        xs = sorted({k[0] for k in self._map_data})
        ys = sorted({k[1] for k in self._map_data})
        arr = np.zeros((len(xs), len(ys)))
        xi = {v: i for i, v in enumerate(xs)}
        yi = {v: i for i, v in enumerate(ys)}
        for (x, y), val in self._map_data.items():
            arr[xi[x], yi[y]] = val
        self._img_view.setImage(arr, autoRange=False, autoLevels=True)

    def _make_spin(
        self, default: float, lo: float = -100.0, hi: float = 100.0
    ) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(4)
        s.setValue(default)
        s.setSuffix(" mm" if hi > 1 else "")
        return s
