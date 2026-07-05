"""
Camera panel — FLIR Blackfly BFLY-U3-23S6M-C.

Layout
------
Left column  : live image with beam overlay (crosshair + 2-σ ellipse)
Right column : acquisition controls (exposure, gain, gamma, format, binning,
               FPS, trigger)
Bottom row   : histogram (pyqtgraph), beam statistics, frame metadata,
               action buttons (save, background, ROI dialog)
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from devices.camera_blackfly import BlackflyCamera, FrameMeta

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# ROI dialog
# ──────────────────────────────────────────────────────────────────────────────

class _ROIDialog(QDialog):
    """Simple modal dialog to enter ROI offsets and dimensions."""

    def __init__(self, ox: int, oy: int, w: int, h: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Region of Interest")
        form = QFormLayout(self)

        self._ox = QSpinBox(); self._ox.setRange(0, 1919); self._ox.setValue(ox)
        self._oy = QSpinBox(); self._oy.setRange(0, 1199); self._oy.setValue(oy)
        self._w  = QSpinBox(); self._w.setRange(0, 1920);  self._w.setValue(w)
        self._h  = QSpinBox(); self._h.setRange(0, 1200);  self._h.setValue(h)

        form.addRow("Offset X (px):", self._ox)
        form.addRow("Offset Y (px):", self._oy)
        form.addRow("Width (px, 0=full):", self._w)
        form.addRow("Height (px, 0=full):", self._h)

        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def values(self) -> tuple[int, int, int, int]:
        return (
            self._ox.value(),
            self._oy.value(),
            self._w.value(),
            self._h.value(),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Main panel
# ──────────────────────────────────────────────────────────────────────────────

class CameraPanel(QWidget):
    """Live camera view with full acquisition controls and beam diagnostics."""

    _HIST_BINS = 256   # histogram resolution

    def __init__(
        self,
        camera: BlackflyCamera,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._camera        = camera
        self._last_frame    : Optional[np.ndarray]  = None
        self._last_meta     : Optional[FrameMeta]   = None
        self._show_crosshair = True
        self._show_overlay   = True   # beam centroid + 2-σ ellipse

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(100)   # 10 fps display rate

    # ──────────────────────────────────────────────────────────────────── #
    # UI construction                                                      #
    # ──────────────────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        # ── Left: image + histogram + stats ───────────────────────────
        left = QVBoxLayout()
        root.addLayout(left, stretch=3)

        # Live image
        self._img_label = QLabel("No image")
        self._img_label.setAlignment(Qt.AlignCenter)
        self._img_label.setMinimumSize(480, 320)
        self._img_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img_label.setStyleSheet("background: #111;")
        left.addWidget(self._img_label, stretch=3)

        # Histogram
        hist_box = QGroupBox("Histogram")
        hist_lay = QVBoxLayout(hist_box)
        self._hist_plot = pg.PlotWidget(background="#1a1a1a")
        self._hist_plot.setMinimumHeight(90)
        self._hist_plot.setMaximumHeight(130)
        self._hist_plot.getAxis("left").setStyle(tickFont=None)
        self._hist_plot.showGrid(x=False, y=True, alpha=0.3)
        self._hist_bar = pg.BarGraphItem(
            x=np.arange(self._HIST_BINS),
            height=np.zeros(self._HIST_BINS),
            width=1.0,
            brush=pg.mkBrush(80, 180, 255, 180),
        )
        self._hist_plot.addItem(self._hist_bar)
        hist_lay.addWidget(self._hist_plot)
        left.addWidget(hist_box)

        # Beam stats
        stats_box = QGroupBox("Beam Statistics")
        stats_lay = QHBoxLayout(stats_box)
        self._lbl_cx    = self._stat_label("Cx")
        self._lbl_cy    = self._stat_label("Cy")
        self._lbl_sx    = self._stat_label("σx")
        self._lbl_sy    = self._stat_label("σy")
        self._lbl_peak  = self._stat_label("Peak")
        self._lbl_mean  = self._stat_label("Mean")
        self._lbl_std   = self._stat_label("Std")
        for w in (self._lbl_cx, self._lbl_cy, self._lbl_sx, self._lbl_sy,
                  self._lbl_peak, self._lbl_mean, self._lbl_std):
            stats_lay.addWidget(w)
        left.addWidget(stats_box)

        # Frame metadata
        meta_box = QGroupBox("Frame Info")
        meta_lay = QHBoxLayout(meta_box)
        self._lbl_frame_id   = self._stat_label("Frame")
        self._lbl_ts         = self._stat_label("Time")
        self._lbl_act_exp    = self._stat_label("Exp")
        self._lbl_act_gain   = self._stat_label("Gain")
        self._lbl_temp       = self._stat_label("Temp")
        self._lbl_fps        = self._stat_label("FPS")
        for w in (self._lbl_frame_id, self._lbl_ts, self._lbl_act_exp,
                  self._lbl_act_gain, self._lbl_temp, self._lbl_fps):
            meta_lay.addWidget(w)
        left.addWidget(meta_box)

        # Action buttons
        btn_row = QHBoxLayout()
        self._chk_crosshair = QCheckBox("Crosshair")
        self._chk_crosshair.setChecked(True)
        self._chk_crosshair.toggled.connect(lambda v: setattr(self, "_show_crosshair", v))
        btn_row.addWidget(self._chk_crosshair)

        self._chk_overlay = QCheckBox("Beam overlay")
        self._chk_overlay.setChecked(True)
        self._chk_overlay.toggled.connect(lambda v: setattr(self, "_show_overlay", v))
        btn_row.addWidget(self._chk_overlay)

        btn_save = QPushButton("Save Frame…")
        btn_save.clicked.connect(self._save_frame)
        btn_row.addWidget(btn_save)

        btn_bg = QPushButton("Capture BG")
        btn_bg.clicked.connect(self._capture_background)
        btn_row.addWidget(btn_bg)

        btn_clr = QPushButton("Clear BG")
        btn_clr.clicked.connect(self._camera.clear_background)
        btn_row.addWidget(btn_clr)

        btn_roi = QPushButton("Set ROI…")
        btn_roi.clicked.connect(self._open_roi_dialog)
        btn_row.addWidget(btn_roi)

        left.addLayout(btn_row)

        # ── Right: acquisition controls ───────────────────────────────
        right = QVBoxLayout()
        root.addLayout(right, stretch=1)

        # ── Exposure ──────────────────────────────────────────────────
        acq_box = QGroupBox("Acquisition")
        acq_form = QFormLayout(acq_box)

        self._spin_exp = QDoubleSpinBox()
        self._spin_exp.setRange(10, 100_000)
        self._spin_exp.setDecimals(0)
        self._spin_exp.setSuffix(" µs")
        self._spin_exp.setValue(5000)
        exp_row = QHBoxLayout()
        exp_row.addWidget(self._spin_exp)
        btn_exp = QPushButton("Set")
        btn_exp.clicked.connect(self._apply_exposure)
        exp_row.addWidget(btn_exp)
        acq_form.addRow("Exposure:", exp_row)

        self._chk_auto_exp = QCheckBox("Auto exposure")
        self._chk_auto_exp.toggled.connect(self._apply_exposure)
        acq_form.addRow("", self._chk_auto_exp)

        # ── Gain ──────────────────────────────────────────────────────
        self._spin_gain = QDoubleSpinBox()
        self._spin_gain.setRange(0, 47.99)
        self._spin_gain.setDecimals(2)
        self._spin_gain.setSuffix(" dB")
        self._spin_gain.setValue(0.0)
        gain_row = QHBoxLayout()
        gain_row.addWidget(self._spin_gain)
        btn_gain = QPushButton("Set")
        btn_gain.clicked.connect(self._apply_gain)
        gain_row.addWidget(btn_gain)
        acq_form.addRow("Gain:", gain_row)

        self._chk_auto_gain = QCheckBox("Auto gain")
        self._chk_auto_gain.toggled.connect(self._apply_gain)
        acq_form.addRow("", self._chk_auto_gain)

        # ── Pixel format ──────────────────────────────────────────────
        self._combo_fmt = QComboBox()
        self._combo_fmt.addItems(["Mono8", "Mono16"])
        self._combo_fmt.currentTextChanged.connect(
            lambda t: self._camera.set_pixel_format(t)
        )
        acq_form.addRow("Pixel format:", self._combo_fmt)

        # ── Binning ───────────────────────────────────────────────────
        self._combo_bin = QComboBox()
        self._combo_bin.addItems(["1", "2", "4"])
        self._combo_bin.currentTextChanged.connect(
            lambda t: self._camera.set_binning(int(t))
        )
        acq_form.addRow("Binning:", self._combo_bin)

        # ── Frame rate ────────────────────────────────────────────────
        self._spin_fps = QDoubleSpinBox()
        self._spin_fps.setRange(1, 164)
        self._spin_fps.setDecimals(1)
        self._spin_fps.setSuffix(" fps")
        self._spin_fps.setValue(10.0)
        fps_row = QHBoxLayout()
        fps_row.addWidget(self._spin_fps)
        btn_fps = QPushButton("Set")
        btn_fps.clicked.connect(
            lambda: self._camera.set_frame_rate(self._spin_fps.value())
        )
        fps_row.addWidget(btn_fps)
        acq_form.addRow("Frame rate:", fps_row)

        right.addWidget(acq_box)

        # ── Image processing ──────────────────────────────────────────
        img_box = QGroupBox("Image Processing")
        img_form = QFormLayout(img_box)

        self._chk_gamma = QCheckBox("Enable")
        self._chk_gamma.setChecked(True)
        self._chk_gamma.toggled.connect(self._apply_gamma)
        img_form.addRow("Gamma:", self._chk_gamma)

        self._spin_gamma = QDoubleSpinBox()
        self._spin_gamma.setRange(0.25, 4.0)
        self._spin_gamma.setSingleStep(0.05)
        self._spin_gamma.setDecimals(2)
        self._spin_gamma.setValue(1.0)
        self._spin_gamma.valueChanged.connect(self._apply_gamma)
        img_form.addRow("γ value:", self._spin_gamma)

        right.addWidget(img_box)

        # ── Trigger ───────────────────────────────────────────────────
        trig_box = QGroupBox("Trigger")
        trig_form = QFormLayout(trig_box)
        self._chk_trigger = QCheckBox("Hardware trigger (Line0 ↓)")
        self._chk_trigger.toggled.connect(
            lambda v: self._camera.set_trigger(v)
        )
        trig_form.addRow(self._chk_trigger)
        right.addWidget(trig_box)

        # ── Camera info ───────────────────────────────────────────────
        info_box = QGroupBox("Camera Info")
        info_lay = QVBoxLayout(info_box)
        self._lbl_info = QLabel("–")
        self._lbl_info.setWordWrap(True)
        self._lbl_info.setStyleSheet("font-size: 10px; color: #aaa;")
        info_lay.addWidget(self._lbl_info)
        right.addWidget(info_box)
        right.addStretch()

        # Populate info once connected
        QTimer.singleShot(500, self._update_camera_info)

    # ──────────────────────────────────────────────────────────────────── #
    # Timer callback                                                       #
    # ──────────────────────────────────────────────────────────────────── #

    def _refresh(self) -> None:
        if not self._camera.connected:
            return
        try:
            frame, meta = self._camera.get_frame_with_meta()
        except Exception as exc:
            logger.debug("camera frame grab failed: %s", exc)
            return

        self._last_frame = frame
        self._last_meta  = meta
        self._display(frame, meta)
        self._update_histogram(frame)
        self._update_stats(meta)

    # ──────────────────────────────────────────────────────────────────── #
    # Display helpers                                                      #
    # ──────────────────────────────────────────────────────────────────── #

    def _display(self, frame: np.ndarray, meta: FrameMeta) -> None:
        # Normalise to 8-bit for display
        if frame.dtype == np.uint16:
            disp = (frame >> 4).astype(np.uint8)   # 12-bit effective range
        else:
            disp = frame

        h, w = disp.shape
        qimg = QImage(disp.data, w, h, w, QImage.Format_Grayscale8)

        lw = self._img_label.width()
        lh = self._img_label.height()
        px = QPixmap.fromImage(qimg).scaled(
            lw, lh, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        # Scale factors from sensor → display
        scale_x = px.width()  / w
        scale_y = px.height() / h

        if self._show_crosshair or self._show_overlay:
            painter = QPainter(px)
            painter.setRenderHint(QPainter.Antialiasing)

            if self._show_crosshair:
                # Red centre-of-image cross
                pen = QPen(QColor(255, 60, 60), 1, Qt.DashLine)
                painter.setPen(pen)
                cx0 = px.width()  // 2
                cy0 = px.height() // 2
                painter.drawLine(cx0 - 12, cy0, cx0 + 12, cy0)
                painter.drawLine(cx0, cy0 - 12, cx0, cy0 + 12)

            if self._show_overlay and meta.pix_max > 0:
                # Green centroid crosshair
                pen = QPen(QColor(0, 255, 80), 1)
                painter.setPen(pen)
                bcx = int(meta.centroid_x * scale_x)
                bcy = int(meta.centroid_y * scale_y)
                arm = 14
                painter.drawLine(bcx - arm, bcy, bcx + arm, bcy)
                painter.drawLine(bcx, bcy - arm, bcx, bcy + arm)

                # Cyan 2-σ ellipse
                if meta.sigma_x > 0 and meta.sigma_y > 0:
                    pen2 = QPen(QColor(0, 200, 255), 1)
                    painter.setPen(pen2)
                    rx = int(2 * meta.sigma_x * scale_x)
                    ry = int(2 * meta.sigma_y * scale_y)
                    painter.drawEllipse(bcx - rx, bcy - ry, 2 * rx, 2 * ry)

            painter.end()

        self._img_label.setPixmap(px)

    def _update_histogram(self, frame: np.ndarray) -> None:
        if frame.dtype == np.uint16:
            counts, edges = np.histogram(frame.ravel(), bins=self._HIST_BINS, range=(0, 65535))
        else:
            counts, edges = np.histogram(frame.ravel(), bins=self._HIST_BINS, range=(0, 255))

        self._hist_bar.setOpts(
            x=edges[:-1],
            height=counts.astype(float),
            width=(edges[1] - edges[0]) * 0.9,
        )

    def _update_stats(self, meta: FrameMeta) -> None:
        self._lbl_cx.setText(   f"Cx\n{meta.centroid_x:.1f} px")
        self._lbl_cy.setText(   f"Cy\n{meta.centroid_y:.1f} px")
        self._lbl_sx.setText(   f"σx\n{meta.sigma_x:.1f} px")
        self._lbl_sy.setText(   f"σy\n{meta.sigma_y:.1f} px")
        self._lbl_peak.setText( f"Peak\n{meta.pix_max:.0f}")
        self._lbl_mean.setText( f"Mean\n{meta.pix_mean:.1f}")
        self._lbl_std.setText(  f"Std\n{meta.pix_std:.1f}")

        self._lbl_frame_id.setText( f"Frame\n{meta.frame_id}")
        ts_ms = meta.timestamp_ns / 1e6
        self._lbl_ts.setText(       f"T (ms)\n{ts_ms:.1f}")
        self._lbl_act_exp.setText(  f"Exp (µs)\n{meta.exposure_us:.0f}")
        self._lbl_act_gain.setText( f"Gain (dB)\n{meta.gain_db:.2f}")

        temp = self._camera.get_temperature()
        if math.isnan(temp):
            self._lbl_temp.setText("Temp\n–")
            self._lbl_temp.setStyleSheet("")
        elif temp >= 65.0:
            self._lbl_temp.setText(f"Temp\n{temp:.1f} °C ⚠")
            self._lbl_temp.setStyleSheet("color: #ff4444; font-weight: bold;")
        elif temp >= 55.0:
            self._lbl_temp.setText(f"Temp\n{temp:.1f} °C")
            self._lbl_temp.setStyleSheet("color: #ffaa00; font-weight: bold;")
        else:
            self._lbl_temp.setText(f"Temp\n{temp:.1f} °C")
            self._lbl_temp.setStyleSheet("")

        fps = self._camera.get_fps_actual()
        if math.isnan(fps):
            self._lbl_fps.setText("FPS\n–")
        else:
            self._lbl_fps.setText(f"FPS\n{fps:.1f}")

    # ──────────────────────────────────────────────────────────────────── #
    # Control callbacks                                                    #
    # ──────────────────────────────────────────────────────────────────── #

    def _apply_exposure(self) -> None:
        self._camera.set_exposure(
            self._spin_exp.value(),
            auto=self._chk_auto_exp.isChecked(),
        )

    def _apply_gain(self) -> None:
        self._camera.set_gain(
            self._spin_gain.value(),
            auto=self._chk_auto_gain.isChecked(),
        )

    def _apply_gamma(self) -> None:
        self._camera.set_gamma(
            self._chk_gamma.isChecked(),
            self._spin_gamma.value(),
        )

    def _update_camera_info(self) -> None:
        if not self._camera.connected:
            QTimer.singleShot(1000, self._update_camera_info)
            return
        info = self._camera.get_camera_info()
        if info:
            lines = [
                f"Model:  {info.get('model', '–')}",
                f"Serial: {info.get('serial', '–')}",
                f"FW:     {info.get('firmware', '–')}",
                f"Sensor: {info.get('sensor_w')}×{info.get('sensor_h')} px",
                f"Pixel:  {info.get('pixel_size_um', '–')} µm",
            ]
            self._lbl_info.setText("\n".join(lines))

    # ──────────────────────────────────────────────────────────────────── #
    # Actions                                                              #
    # ──────────────────────────────────────────────────────────────────── #

    def _save_frame(self) -> None:
        if self._last_frame is None:
            QMessageBox.warning(self, "No Frame", "No frame captured yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Frame", "", "TIFF (*.tiff);;PNG (*.png);;NumPy (*.npy)"
        )
        if not path:
            return
        try:
            p = Path(path)
            frame = self._last_frame
            meta  = self._last_meta
            if p.suffix.lower() == ".npy":
                np.save(p, frame)
            else:
                import PIL.Image
                import PIL.TiffImagePlugin
                img = PIL.Image.fromarray(frame)
                tiff_meta: dict = {}
                if meta is not None:
                    tiff_meta = {
                        "frame_id":     str(meta.frame_id),
                        "timestamp_ns": str(meta.timestamp_ns),
                        "exposure_us":  str(meta.exposure_us),
                        "gain_db":      str(meta.gain_db),
                        "centroid_x":   str(meta.centroid_x),
                        "centroid_y":   str(meta.centroid_y),
                        "sigma_x":      str(meta.sigma_x),
                        "sigma_y":      str(meta.sigma_y),
                    }
                if p.suffix.lower() in (".tiff", ".tif") and tiff_meta:
                    # Store metadata in TIFF ImageDescription tag
                    import json
                    img.save(
                        p,
                        tiffinfo={270: json.dumps(tiff_meta)},  # tag 270 = ImageDescription
                    )
                else:
                    img.save(p)
        except Exception as exc:
            QMessageBox.warning(self, "Save Error", str(exc))

    def _capture_background(self) -> None:
        try:
            self._camera.capture_background()
        except Exception as exc:
            QMessageBox.warning(self, "Background Error", str(exc))

    def _open_roi_dialog(self) -> None:
        ox, oy, w, h = self._camera.get_roi()
        dlg = _ROIDialog(ox, oy, w, h, self)
        if dlg.exec() == QDialog.Accepted:
            ox2, oy2, w2, h2 = dlg.values()
            self._camera.set_roi(ox2, oy2, w2, h2)

    # ──────────────────────────────────────────────────────────────────── #
    # Helper                                                               #
    # ──────────────────────────────────────────────────────────────────── #

    @staticmethod
    def _stat_label(title: str) -> QLabel:
        lbl = QLabel(f"{title}\n–")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "font-size: 10px; background: #222; border-radius: 3px; padding: 2px 4px;"
        )
        lbl.setMinimumWidth(58)
        return lbl
