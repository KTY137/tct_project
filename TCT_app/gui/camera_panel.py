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
from PySide6.QtCore import QObject, Qt, QSettings, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from devices.camera_blackfly import BlackflyCamera, FrameMeta
from gui.panel_kit import (
    ActionBar, Card, EmptyState, MetricGrid, MetricTile, panel_header,
    readout_cell,
)
from gui.status_widgets import StatusChip, flash_button, set_button_icon
from gui.style import DARK, LIGHT, PLOT_BG, SPACE_MD, SPACE_SM, WARN_AMBER, WARN_RED

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
# Frame-acquisition worker
# ──────────────────────────────────────────────────────────────────────────────

class _CameraWorker(QObject):
    """Grabs frames + camera stats in a dedicated QThread.

    PySpin's ``GetNextImage`` blocks up to ~2 s (its own timeout) and a pulled
    USB3 camera sits there the whole time; running it on the GUI thread (the
    old 100 ms ``QTimer`` → ``_refresh`` path) froze the window for that long
    every tick, and even a healthy 1 fps link left the event loop stuck inside
    PySpin most of the time.  This worker owns a ``QTimer`` that polls on its
    own thread and hands the finished frame + metadata + temperature/fps back
    to the panel through a queued signal, so the GUI thread only ever renders.
    Mirrors ``gui.motor_panel._PositionPoller`` / ``tct_gui._BiasPoller``.
    """
    # frame ndarray, FrameMeta, temperature °C, actual fps.  ``object`` params
    # carry the Python objects by reference across the queued connection; the
    # driver already returns a fresh ndarray per grab, so there is no buffer
    # aliased between the worker and the GUI thread.
    frame_ready = Signal(object, object, float, float)
    offline = Signal()
    info_ready = Signal(dict)

    def __init__(self, get_camera, interval_ms: int = 100) -> None:
        super().__init__()
        self._get_camera = get_camera
        self._info_sent = False
        # Parent the timer to self so moveToThread() carries it to the worker
        # thread (an unparented QTimer would stay on the GUI thread).
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll_once(self) -> None:
        """One single grab (the panel's "Single" command) — exactly one pass
        of the existing poll path, without (re)starting the live timer."""
        self._poll()

    def _poll(self) -> None:
        cam = self._get_camera()
        if cam is None or not getattr(cam, "connected", False):
            self.offline.emit()
            return
        # Static camera info once, off the GUI thread too — the node-map reads
        # are local but still device I/O, so they belong here, not on the loop.
        if not self._info_sent:
            try:
                info = cam.get_camera_info()
            except Exception:
                info = None
            if info:
                self._info_sent = True
                self.info_ready.emit(info)
        try:
            frame, meta = cam.get_frame_with_meta()
        except Exception as exc:
            # A transient grab failure keeps the last displayed frame — exactly
            # what the old _refresh did; do not tear the live view down.
            logger.debug("camera frame grab failed: %s", exc)
            return
        # Temperature / fps are best-effort: a failure must not drop the frame.
        try:
            temp = float(cam.get_temperature())
        except Exception:
            temp = float("nan")
        try:
            fps = float(cam.get_fps_actual())
        except Exception:
            fps = float("nan")
        self.frame_ready.emit(frame, meta, temp, fps)


# ──────────────────────────────────────────────────────────────────────────────
# Main panel
# ──────────────────────────────────────────────────────────────────────────────

class CameraPanel(QWidget):
    """Live camera view with full acquisition controls and beam diagnostics."""

    _HIST_BINS = 256   # histogram resolution
    _worker_stop_requested = Signal()    # GUI → worker: stop the poll timer
    _worker_start_requested = Signal()   # GUI → worker: (re)start the poll timer
    _worker_single_requested = Signal()  # GUI → worker: grab exactly one frame

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
        # Theme mode for the histogram bar's accent colour (gui.style tokens).
        # Read once from the same QSettings key main.py/tct_gui.py use,
        # mirroring MotorPanel/MonitorPanel; see refresh_theme() below.
        self._theme_mode = str(QSettings("TCT", "TCTSetup").value("theme", "light"))

        self._build_ui()

        # ── Frame-acquisition worker ──────────────────────────────────
        # All PySpin I/O (GetNextImage ~2 s on a pulled USB, plus temperature
        # and fps node reads) runs on this worker thread, never the GUI thread
        # — the old 100 ms QTimer → _refresh path did the grab inline and froze
        # the window.  The thread is parented to the long-lived QApplication
        # (NOT this panel): a soft config-reload deletes the panel tree via
        # setCentralWidget(), and a QThread destroyed as a child while still
        # running is a hard Qt6 abort (the MotorPanel crash class).  shutdown()
        # stops it with a bounded wait; it self-deletes on ``finished``.
        self._cam_thread: QThread | None = QThread(QApplication.instance())
        self._cam_worker = _CameraWorker(lambda: self._camera)
        self._cam_worker.moveToThread(self._cam_thread)
        self._cam_thread.started.connect(self._cam_worker.start)
        self._worker_stop_requested.connect(self._cam_worker.stop)
        self._worker_start_requested.connect(self._cam_worker.start)
        self._worker_single_requested.connect(self._cam_worker.poll_once)
        self._cam_thread.finished.connect(self._cam_worker.deleteLater)
        self._cam_thread.finished.connect(self._cam_thread.deleteLater)
        self._cam_worker.frame_ready.connect(self._on_frame)
        self._cam_worker.offline.connect(self._on_offline)
        self._cam_worker.info_ready.connect(self._on_camera_info)
        self._cam_thread.start()

    # ──────────────────────────────────────────────────────────────────── #
    # UI construction                                                      #
    # ──────────────────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        outer.setSpacing(SPACE_MD)
        outer.addWidget(panel_header("TCT Control · Instrument", "Camera"))

        content = QHBoxLayout()
        content.setSpacing(SPACE_MD)
        outer.addLayout(content, 1)

        # ── Left: image + histogram + stats ───────────────────────────
        left = QVBoxLayout()
        left.setSpacing(SPACE_MD)
        content.addLayout(left, stretch=3)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._chip_camera = StatusChip("Camera offline", "neutral")
        self._chip_fps = StatusChip("FPS --", "neutral")
        self._chip_temp = StatusChip("Temp --", "neutral")
        self._chip_sat = StatusChip("Saturation --", "neutral")
        self._chip_roi = StatusChip("ROI full", "neutral")
        self._chip_bg = StatusChip("BG empty", "neutral")
        for chip in (
            self._chip_camera, self._chip_fps, self._chip_temp,
            self._chip_sat, self._chip_roi, self._chip_bg,
        ):
            status_row.addWidget(chip)
        status_row.addStretch(1)
        left.addLayout(status_row)

        # Live image — a bare Card (no title) so the "instrument screen"
        # image sits level with every other card instead of floating
        # unframed; the dark canvas colour itself is the PLOT_BG token (the
        # same "dark instrument screen in both themes" idiom the plot canvas
        # uses everywhere else — see gui/style.py).  Hot-path widget: no
        # QGraphicsEffect/shadow/glow, ever — static border + surface only.
        # Designed empty states (design system §7 "Camera"): a stack swaps
        # between not-connected (error variant, §6 "failed connects are
        # designed error states"), not-streaming, and the live image.
        view_card = Card()
        view_card.body.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        self._img_label = QLabel("")
        self._img_label.setAlignment(Qt.AlignCenter)
        self._img_label.setMinimumSize(480, 320)
        self._img_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img_label.setStyleSheet(f"background: {PLOT_BG};")
        self._empty_offline = EmptyState(
            "mdi.camera-off", "Camera not connected",
            "Connect the camera from the top bar; streaming resumes on its own.",
            variant="error", theme_mode=self._theme_mode,
        )
        self._empty_stopped = EmptyState(
            "mdi.camera", "Not streaming",
            "Press Live for a continuous stream or Single for one frame.",
            theme_mode=self._theme_mode,
        )
        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._empty_offline)   # index 0
        self._view_stack.addWidget(self._empty_stopped)   # index 1
        self._view_stack.addWidget(self._img_label)       # index 2
        self._view_stack.setCurrentWidget(self._empty_offline)
        view_card.add_widget(self._view_stack)

        # Live / Single / Stop — the acquisition commands this panel never
        # had (the stream used to start silently with the worker thread and
        # was unstoppable from the UI).  They drive the EXISTING worker
        # QTimer via queued signals; no new acquisition path.
        self._btn_live = QPushButton("Live")
        set_button_icon(self._btn_live, "mdi.play")
        self._btn_live.setCheckable(True)
        self._btn_live.setChecked(True)   # streaming auto-starts (unchanged)
        self._btn_live.setToolTip("Continuously grab frames (worker-thread poll)")
        self._btn_live.toggled.connect(self._on_live_toggled)
        self._btn_single = QPushButton("Single")
        set_button_icon(self._btn_single, "mdi.camera")
        self._btn_single.setToolTip("Stop the stream and grab exactly one frame")
        self._btn_single.clicked.connect(self._on_single_clicked)
        self._btn_stop = QPushButton("Stop")
        set_button_icon(self._btn_stop, "mdi.stop")
        self._btn_stop.setToolTip("Stop grabbing frames (keeps the last image)")
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        view_card.add_widget(ActionBar(
            primary=self._btn_live,
            secondary=[self._btn_single, self._btn_stop],
        ))
        left.addWidget(view_card, stretch=3)

        # Histogram — hot-path plot: dark canvas via the PLOT_BG token only,
        # no drop-shadow/glow effects.
        hist_card = Card("Histogram")
        self._hist_plot = pg.PlotWidget(background=PLOT_BG)
        self._hist_plot.setMinimumHeight(90)
        self._hist_plot.setMaximumHeight(130)
        self._hist_plot.getAxis("left").setStyle(tickFont=None)
        self._hist_plot.showGrid(x=False, y=True, alpha=0.3)
        self._hist_bar = pg.BarGraphItem(
            x=np.arange(self._HIST_BINS),
            height=np.zeros(self._HIST_BINS),
            width=1.0,
            brush=self._hist_brush(),
        )
        self._hist_plot.addItem(self._hist_bar)
        hist_card.add_widget(self._hist_plot)
        left.addWidget(hist_card)

        # Beam stats — MetricTiles (design system §7: "beam stats as tiles",
        # px units on the values); stale-with-caption until the first frame
        # (law 4: never an unexplained bare dash).
        stats_card = Card("Beam statistics")
        stats_grid = MetricGrid(columns=7)
        self._ro_cx    = stats_grid.add_tile(MetricTile("Cx", "—", min_width=72))
        self._ro_cy    = stats_grid.add_tile(MetricTile("Cy", "—", min_width=72))
        self._ro_sx    = stats_grid.add_tile(MetricTile("σx", "—", min_width=72))
        self._ro_sy    = stats_grid.add_tile(MetricTile("σy", "—", min_width=72))
        self._ro_peak  = stats_grid.add_tile(MetricTile("Peak", "—", min_width=72))
        self._ro_mean  = stats_grid.add_tile(MetricTile("Mean", "—", min_width=72))
        self._ro_std   = stats_grid.add_tile(MetricTile("Std", "—", min_width=72))
        for tile in stats_grid.tiles():
            tile.set_stale(True, "no frame yet")
        self._stats_tiles = stats_grid.tiles()
        stats_card.add_widget(stats_grid)
        left.addWidget(stats_card)

        # Frame metadata — same readout-cell treatment; Temp is a hand-built
        # look-alike so its tri-state good/warn/crit colour swap has a hook
        # ReadoutCell itself doesn't expose (see _build_temp_readout()).
        meta_card = Card("Frame info")
        meta_lay = QHBoxLayout()
        self._ro_frame_id = readout_cell("Frame", min_width=64)
        self._ro_ts       = readout_cell("T (ms)", min_width=64)
        self._ro_act_exp  = readout_cell("Exp (µs)", min_width=64)
        self._ro_act_gain = readout_cell("Gain (dB)", min_width=64)
        self._temp_frame, self._lbl_temp = self._build_temp_readout()
        self._ro_fps       = readout_cell("FPS", min_width=64)
        for w in (self._ro_frame_id, self._ro_ts, self._ro_act_exp,
                  self._ro_act_gain, self._temp_frame, self._ro_fps):
            meta_lay.addWidget(w)
        meta_lay.addStretch(1)
        meta_card.add_layout(meta_lay)
        left.addWidget(meta_card)

        # Action buttons
        actions_card = Card("View & capture")
        btn_row = QHBoxLayout()
        self._chk_crosshair = QCheckBox("Crosshair")
        self._chk_crosshair.setChecked(True)
        self._chk_crosshair.toggled.connect(lambda v: setattr(self, "_show_crosshair", v))
        btn_row.addWidget(self._chk_crosshair)

        self._chk_overlay = QCheckBox("Beam overlay")
        self._chk_overlay.setChecked(True)
        self._chk_overlay.toggled.connect(lambda v: setattr(self, "_show_overlay", v))
        btn_row.addWidget(self._chk_overlay)

        self._btn_save = QPushButton("Save frame…")
        set_button_icon(self._btn_save, "mdi.content-save")
        self._btn_save.clicked.connect(self._save_frame)
        btn_row.addWidget(self._btn_save)

        self._btn_bg = QPushButton("Capture BG")
        set_button_icon(self._btn_bg, "mdi.image-filter-center-focus")
        self._btn_bg.clicked.connect(self._capture_background)
        btn_row.addWidget(self._btn_bg)

        self._btn_clr_bg = QPushButton("Clear BG")
        set_button_icon(self._btn_clr_bg, "mdi.close-circle-outline")
        self._btn_clr_bg.clicked.connect(self._clear_background)
        btn_row.addWidget(self._btn_clr_bg)

        self._btn_roi = QPushButton("Set ROI…")
        set_button_icon(self._btn_roi, "mdi.crop")
        self._btn_roi.clicked.connect(self._open_roi_dialog)
        btn_row.addWidget(self._btn_roi)

        actions_card.add_layout(btn_row)
        left.addWidget(actions_card)

        # ── Right: acquisition controls ───────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(SPACE_MD)
        content.addLayout(right, stretch=1)

        # ── Exposure ──────────────────────────────────────────────────
        acq_card = Card("Acquisition")
        acq_form = QFormLayout()

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

        acq_card.add_layout(acq_form)
        right.addWidget(acq_card)

        # ── Image processing ──────────────────────────────────────────
        img_card = Card("Image processing")
        img_form = QFormLayout()

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

        img_card.add_layout(img_form)
        right.addWidget(img_card)

        # ── Trigger ───────────────────────────────────────────────────
        trig_card = Card("Trigger")
        trig_form = QFormLayout()
        self._chk_trigger = QCheckBox("Hardware trigger (Line0 ↓)")
        self._chk_trigger.toggled.connect(
            lambda v: self._camera.set_trigger(v)
        )
        trig_form.addRow(self._chk_trigger)
        trig_card.add_layout(trig_form)
        right.addWidget(trig_card)

        # ── Camera info ───────────────────────────────────────────────
        # objectName "cardSubtitle" reuses the shared muted/monospace QSS
        # hook (gui/style.py) instead of a hand-rolled "color: #aaa" — it
        # repaints on a live theme switch automatically via the app-wide
        # stylesheet, so this label needs no entry in refresh_theme().
        info_card = Card("Camera info")
        self._lbl_info = QLabel("–")
        self._lbl_info.setObjectName("cardSubtitle")
        self._lbl_info.setWordWrap(True)
        info_card.add_widget(self._lbl_info)
        right.addWidget(info_card)
        right.addStretch()

        self._restyle_theme_tokens()
        # Camera info is fetched off-thread by _CameraWorker and delivered to
        # _on_camera_info() once the camera is connected (no GUI-thread I/O).

    @staticmethod
    def _build_temp_readout() -> tuple[QFrame, QLabel]:
        """A Temp readout that LOOKS like a ``readout_cell()`` (same
        ``readoutCell``/``readoutCellTitle``/``readoutCellValue`` QSS hooks —
        gui/style.py) but is hand-built instead of a ``ReadoutCell`` instance:
        the tri-state good/warn/crit colour swap in ``_update_stats`` needs a
        per-instance override on the value label, which ``ReadoutCell`` has
        no hook for.  Returns ``(frame, value_label)``."""
        frame = QFrame()
        frame.setObjectName("readoutCell")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 5, 10, 6)
        lay.setSpacing(1)
        title = QLabel("TEMP")
        title.setObjectName("readoutCellTitle")
        title.setAlignment(Qt.AlignCenter)
        value = QLabel("–")
        value.setObjectName("readoutCellValue")
        value.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(value)
        frame.setMinimumWidth(64)
        return frame, value

    # ──────────────────────────────────────────────────────────────────── #
    # Theme-token styling (gui.style) — re-run by refresh_theme()          #
    # ──────────────────────────────────────────────────────────────────── #

    def _hist_brush(self):
        """Histogram bar fill: the theme accent colour (replaces the old
        hardcoded ``pg.mkBrush(80, 180, 255, 180)``) — same idiom as
        MonitorPanel's history-curve accent (see its ``_history_accent``)."""
        accent = (DARK if self._theme_mode == "dark" else LIGHT)["accent"]
        color = pg.mkColor(accent)
        color.setAlpha(180)
        return pg.mkBrush(color)

    def _restyle_theme_tokens(self) -> None:
        """Re-resolve the histogram bar's accent colour, baked as a
        pyqtgraph brush at construction time (a theme switch does not
        otherwise touch it), plus the two EmptyState surfaces' icon/ink."""
        if hasattr(self, "_hist_bar"):
            self._hist_bar.setOpts(brush=self._hist_brush())
        for empty in (getattr(self, "_empty_offline", None),
                      getattr(self, "_empty_stopped", None)):
            if empty is not None:
                empty.refresh_theme(self._theme_mode)

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve theme-token colours after a light/dark switch (same
        pattern as ``MotorPanel.refresh_theme`` / ``MonitorPanel.refresh_theme``).
        Structural chrome (``cardPane``/``cardHeader``/``statusChip``/...)
        already repaints via the app-wide stylesheet
        ``gui.style.apply_theme()`` reapplies; only the histogram brush baked
        by ``_restyle_theme_tokens`` needs this explicit refresh."""
        if mode:
            self._theme_mode = str(mode)
        self._restyle_theme_tokens()

    # ──────────────────────────────────────────────────────────────────── #
    # Worker-delivered render slots (queued from _CameraWorker's thread)   #
    # ──────────────────────────────────────────────────────────────────── #

    @Slot(object, object, float, float)
    def _on_frame(self, frame: np.ndarray, meta: FrameMeta,
                  temp: float, fps: float) -> None:
        """Render a frame the worker grabbed off-thread.  Pure widget work —
        no device I/O here (that all happened on the worker thread).  Same
        body as the old _refresh, minus the grab and the temp/fps reads, which
        arrive as arguments."""
        self._last_frame = frame
        self._last_meta  = meta
        self._view_stack.setCurrentWidget(self._img_label)
        for tile in self._stats_tiles:
            if tile.is_stale():
                tile.set_stale(False, "")
        self._display(frame, meta)
        self._update_histogram(frame)
        self._update_stats(meta, temp, fps)
        self._update_status_chips(frame, meta)

    @Slot()
    def _on_offline(self) -> None:
        """Worker reports the camera is not connected — the same neutral chips
        the old _refresh painted on its not-connected branch, plus the
        designed not-connected surface when there is no last frame to keep."""
        self._chip_camera.set_status("Camera offline", "disconnected")
        self._chip_fps.set_status("FPS --", "neutral")
        if self._last_frame is None:
            self._view_stack.setCurrentWidget(self._empty_offline)

    # ── Live / Single / Stop (existing worker QTimer, exposed honestly) ──

    def _on_live_toggled(self, checked: bool) -> None:
        if checked:
            self._worker_start_requested.emit()
            self._chip_camera.set_status("Camera starting…", "busy")
        else:
            self._worker_stop_requested.emit()
            self._on_stream_stopped()

    def _on_single_clicked(self) -> None:
        # Single = stop the stream (if running), then exactly one grab.
        if self._btn_live.isChecked():
            self._btn_live.setChecked(False)   # emits the stop via toggled
        self._worker_single_requested.emit()

    def _on_stop_clicked(self) -> None:
        if self._btn_live.isChecked():
            self._btn_live.setChecked(False)   # emits the stop via toggled
        else:
            self._worker_stop_requested.emit() # idempotent explicit stop
            self._on_stream_stopped()

    def _on_stream_stopped(self) -> None:
        """Honest stopped state: the last frame (if any) is kept on screen;
        with none yet, the designed not-streaming placeholder shows."""
        connected = bool(getattr(self._camera, "connected", False))
        self._chip_camera.set_status(
            "Stream stopped" if connected else "Camera offline",
            "neutral" if connected else "disconnected")
        self._chip_fps.set_status("FPS --", "neutral")
        if self._last_frame is None:
            self._view_stack.setCurrentWidget(
                self._empty_stopped if connected else self._empty_offline)

    def _update_status_chips(self, frame: np.ndarray, meta: FrameMeta) -> None:
        self._chip_camera.set_status("Camera live", "busy")
        max_possible = 65535 if frame.dtype == np.uint16 else 255
        saturated = float(meta.pix_max) >= max_possible * 0.98
        self._chip_sat.set_status("Saturated" if saturated else "Saturation OK",
                                  "warn" if saturated else "good")

    # ──────────────────────────────────────────────────────────────────── #
    # Display helpers                                                      #
    # ──────────────────────────────────────────────────────────────────── #

    @staticmethod
    def _window_to_8bit(frame: np.ndarray) -> np.ndarray:
        """Map a >8-bit frame to 8-bit for display via a per-frame autoscale
        window (1st–99th percentile), replacing the old fixed
        ``(frame >> 4).astype(uint8)``.

        The old path assumed exactly 12-bit data and hard-truncated the low 8
        bits after the shift, so a smooth 12-bit gradient wrapped every 256
        counts (Kaya's "aliasing" bands) and any summed/binned frame pinned to
        white.  A percentile window is robust to the actual bit depth *and* to
        summed intensities: it stretches the frame's own 1..99 % range across
        0..255 so the background stays dark and only genuine highlights clip.
        Cheap enough for the render slot — two ``np.percentile`` reductions plus
        one vectorised rescale; the one extra allocation (the float rescale
        buffer) is unavoidable for the arithmetic.
        """
        lo, hi = (float(v) for v in np.percentile(frame, (1.0, 99.0)))
        if hi <= lo:
            # Degenerate window (near-flat frame): fall back to full min/max,
            # then to a black frame so a constant image is not a divide-by-zero.
            lo, hi = float(frame.min()), float(frame.max())
            if hi <= lo:
                return np.zeros(frame.shape, dtype=np.uint8)
        scaled = (frame.astype(np.float32) - lo) * (255.0 / (hi - lo))
        return np.clip(scaled, 0, 255).astype(np.uint8)

    @staticmethod
    def _to_display_8bit(frame: np.ndarray) -> np.ndarray:
        """Convert a raw camera frame to a contiguous 8-bit display buffer.

        Mono8 (uint8) passes straight through — its native range already *is*
        the display range (behaviour preserved).  Mono16 is autoscaled through
        ``_window_to_8bit`` (the old fixed ``>>4`` truncation is gone)."""
        if frame.dtype == np.uint16:
            return CameraPanel._window_to_8bit(frame)
        return frame   # Mono8 (or already-8-bit) — passthrough, unchanged

    def _display(self, frame: np.ndarray, meta: FrameMeta) -> None:
        # Normalise to 8-bit for display (autoscale window for 16-bit,
        # passthrough for 8-bit) — see _to_display_8bit / _window_to_8bit.
        disp = self._to_display_8bit(frame)

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

    def _update_stats(self, meta: FrameMeta, temp: float, fps: float) -> None:
        """Update beam/frame readouts.  ``temp`` (°C) and ``fps`` are supplied
        by the worker thread — this slot does no device I/O (the old version
        called ``camera.get_temperature()`` / ``get_fps_actual()`` inline on
        the GUI thread)."""
        self._ro_cx.set_value(   f"{meta.centroid_x:.1f} px")
        self._ro_cy.set_value(   f"{meta.centroid_y:.1f} px")
        self._ro_sx.set_value(   f"{meta.sigma_x:.1f} px")
        self._ro_sy.set_value(   f"{meta.sigma_y:.1f} px")
        self._ro_peak.set_value( f"{meta.pix_max:.0f}")
        self._ro_mean.set_value( f"{meta.pix_mean:.1f}")
        self._ro_std.set_value(  f"{meta.pix_std:.1f}")

        self._ro_frame_id.set_value(f"{meta.frame_id}")
        ts_ms = meta.timestamp_ns / 1e6
        self._ro_ts.set_value(      f"{ts_ms:.1f}")
        self._ro_act_exp.set_value( f"{meta.exposure_us:.0f}")
        self._ro_act_gain.set_value(f"{meta.gain_db:.2f}")

        if math.isnan(temp):
            self._lbl_temp.setText("–")
            self._lbl_temp.setStyleSheet("")
            self._chip_temp.set_status("Temp --", "neutral")
        elif temp >= 65.0:
            self._lbl_temp.setText(f"{temp:.1f} °C ⚠")
            self._lbl_temp.setStyleSheet(
                f"#readoutCellValue {{ color: {WARN_RED}; }}")
            self._chip_temp.set_status(f"Temp {temp:.1f} C", "crit")
        elif temp >= 55.0:
            self._lbl_temp.setText(f"{temp:.1f} °C")
            self._lbl_temp.setStyleSheet(
                f"#readoutCellValue {{ color: {WARN_AMBER}; }}")
            self._chip_temp.set_status(f"Temp {temp:.1f} C", "warn")
        else:
            self._lbl_temp.setText(f"{temp:.1f} °C")
            self._lbl_temp.setStyleSheet("")
            self._chip_temp.set_status(f"Temp {temp:.1f} C", "good")

        if math.isnan(fps):
            self._ro_fps.set_value("–")
            self._chip_fps.set_status("FPS --", "neutral")
        else:
            self._ro_fps.set_value(f"{fps:.1f}")
            self._chip_fps.set_status(f"FPS {fps:.1f}", "busy")

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

    @Slot(dict)
    def _on_camera_info(self, info: dict) -> None:
        """Populate the static camera-info card from data the worker fetched
        off-thread (was a GUI-thread ``get_camera_info()`` singleShot poll)."""
        if not info:
            return
        lines = [
            f"Model:  {info.get('model', '–')}",
            f"Serial: {info.get('serial', '–')}",
            f"FW:     {info.get('firmware', '–')}",
            f"Sensor: {info.get('sensor_w')}×{info.get('sensor_h')} px",
            f"Pixel:  {info.get('pixel_size_um', '–')} µm",
        ]
        self._lbl_info.setText("\n".join(lines))

    # ──────────────────────────────────────────────────────────────────── #
    # Teardown                                                             #
    # ──────────────────────────────────────────────────────────────────── #

    def shutdown(self) -> None:
        """Stop the frame worker before the panel is discarded.

        Called by ``tct_gui._teardown_panels`` on a soft config-reload / exit
        (setCentralWidget() then deletes the panel tree).  Bounded wait — a
        ``GetNextImage`` grab can sit ~2 s inside PySpin, so never wait
        unbounded on the GUI thread.  The worker thread is parented to
        QApplication and self-``deleteLater``s on ``finished``, so a grab still
        in flight when the 3 s bound elapses finishes and cleans itself up on
        its own rather than being destroyed as a child of this (soon-deleted)
        widget — the MotorPanel soft-reload crash class.  Idempotent.
        """
        self._worker_stop_requested.emit()   # queued → stops the worker QTimer
        thread = self._cam_thread
        self._cam_thread = None
        if thread is not None:
            thread.quit()
            thread.wait(3000)

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

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
            flash_button(self._btn_save, "good", "Saved")
        except Exception as exc:
            QMessageBox.warning(self, "Save Error", str(exc))

    def _capture_background(self) -> None:
        try:
            self._camera.capture_background()
            self._chip_bg.set_status("BG captured", "good")
            flash_button(self._btn_bg, "good", "Captured")
        except Exception as exc:
            QMessageBox.warning(self, "Background Error", str(exc))

    def _clear_background(self) -> None:
        try:
            self._camera.clear_background()
            self._chip_bg.set_status("BG empty", "neutral")
            flash_button(self._btn_clr_bg, "good", "Cleared")
        except Exception as exc:
            QMessageBox.warning(self, "Background Error", str(exc))

    def _open_roi_dialog(self) -> None:
        ox, oy, w, h = self._camera.get_roi()
        dlg = _ROIDialog(ox, oy, w, h, self)
        if dlg.exec() == QDialog.Accepted:
            ox2, oy2, w2, h2 = dlg.values()
            self._camera.set_roi(ox2, oy2, w2, h2)
            active = bool(w2 and h2)
            self._chip_roi.set_status("ROI active" if active else "ROI full",
                                      "info" if active else "neutral")
            flash_button(self._btn_roi, "good", "ROI set")
