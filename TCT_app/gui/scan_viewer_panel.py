"""Live scan monitor — the Scan Viewer (cockpit build-order step 5,
``docs/design/cockpit_style_overhaul.md`` Phase 2,
``docs/research/scan_viewer_design_review.md``).

``ScanViewerPanel`` replaces :class:`~gui.scan_panel.ScanPanel`'s *live/run-
control* role (that panel is retired in the next step, S2c). Locked design:
the Scan **Planner** is the only surface that configures/starts raster or
plan scans; this panel only **monitors** a run already started elsewhere and
offers live run control (pause/resume, abort). The one exception is Z-focus
— a live focal-point assist, not a ``ScanPlan`` — which this panel *does*
start, per ``scan_viewer_design_review.md`` §c Q5.

Built entirely on the cockpit kit (``gui/panel_kit.py``) and the shared
:class:`~gui.scan_map_view.ScanMapView` (never a second map renderer):

* **Live map** — the shared ``ScanMapView`` (itself a ``FigureCard``).
* **Run monitor** — a ``MetricGrid`` (progress, ETA, current point, elapsed).
* **Run control** — an ``ActionBar`` with Pause/Resume + a loud ``dangerBtn``
  Abort (rule 2), both disabled unless a run is active.
* **Z-focus** — a ``CollapsibleCard`` (collapsed by default, design system
  §7) holding the focus-scan form (lifted from ``gui/scan_panel.py``'s proven
  ``on_z_focus_point``/``on_z_focus_done`` logic) plus its live curve; the
  header keeps a Best-Z summary chip and the "Find focus" verb reachable
  while collapsed.
* **Empty placeholder** lives inside ``ScanMapView`` (so the map toolbar
  stays visible pre-run); once a run has painted the map, the map stays on
  screen — with a FINISHED/ABORTED banner carrying a first-class "Open in
  Analysis" — even after the run ends.

No hardware I/O in the constructor; thread-free (only consumes signals a
caller feeds into its slots — see ``docs/research/scan_viewer_design_review.md``
R3). Slot/signal names deliberately mirror ``gui/scan_coordinator.py`` so S2c
wiring is a straight ``connect()`` pass, not a rewrite.
"""
from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from controller.scan_controller import ScanResult, ZFocusScanConfig
from gui.panel_kit import (
    ActionBar, CollapsibleCard, FigureCard, MetricGrid, panel_header,
)
from gui.motion import flash_readout
from gui.scan_map_view import ScanMapView
from gui.status_widgets import StatusChip, set_button_icon
from gui.style import (
    FONT_BODY_PX, PLOT_OVERLAY, SPACE_SM, WEIGHT_BODY, axis_color, palette,
    repolish,
)


class ScanViewerPanel(QWidget):
    """Live scan monitor + Z-focus live assist.

    Signals OUT
    ------------
    pause_requested(bool)              — Pause/Resume toggle (True=pause).
    abort_requested()                  — Abort button (loudest control, rule 2).
    z_focus_requested(ZFocusScanConfig) — Z-focus "Find Focus" button.
    open_in_analysis_requested(str)    — "Open in Analysis" with the run path.
    best_z_apply_requested(float)      — "Apply to Planner" button next to the
        Best Z readout; carries the last ``on_z_focus_done`` value. Staging
        only — never moves the motor and never touches a running plan, see
        ``gui/planner_panel.py.set_focus_z`` (the sole intended receiver).

    Slots IN (match ``gui/scan_coordinator.py`` signal names 1:1)
    ---------------------------------------------------------------
    on_scan_started(), on_scan_finished(), on_point_done(result),
    on_progress(done, total), on_z_focus_pt(z_mm, amp_V),
    on_z_focus_done(best_z_mm), on_manual_pause(msg),
    set_current_position(x, y, z) — optional live motor-position feed.

    ``set_last_run_path(path)`` — the coordinator/controller has no signal
    that carries the just-written HDF5 path today (only
    ``ScanController.last_run_path``); S2c calls this setter (e.g. from its
    own ``scan_finished`` handler) so "Open in Analysis" has something to
    hand off. Safe to call before or after :meth:`on_scan_finished` — the
    button only enables once both "a path is known" and "no run is active"
    are true.
    """

    pause_requested = Signal(bool)
    abort_requested = Signal()
    z_focus_requested = Signal(ZFocusScanConfig)
    open_in_analysis_requested = Signal(str)
    best_z_apply_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_mode = "light"
        self._run_active = False
        self._abort_pending = False
        self._last_run_path: str | None = None
        self._start_time: float | None = None
        self._zf_z_data: list[float] = []
        self._zf_a_data: list[float] = []
        self._last_best_z: float | None = None
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(SPACE_SM)

        self._chip_run = StatusChip("No run", "neutral", min_width=140)
        root.addWidget(panel_header(
            "TCT Control", "Scan Viewer",
            trailing=[self._chip_run],
            theme_mode=self._theme_mode,
        ))

        # ── Live map (the hero) ───────────────────────────────────────
        # The empty placeholder now lives INSIDE ScanMapView, so its
        # quantity/freeze/export toolbar stays visible even before the first
        # run (design system §7) — no panel-level stacked swap anymore.
        self._map_view = ScanMapView(
            empty_label="No run in progress",
            empty_hint="Configure and start a routine in the Scan Planner.",
        )
        root.addWidget(self._map_view, 1)

        # ── Finished banner — terminal state as design (§5) ──────────
        root.addWidget(self._build_finished_banner())

        # ── Run monitor ───────────────────────────────────────────────
        # Compact tiles: a position triple / h-scale ETA never fits the
        # 26 px hero face 4-across. Stale-captioned per law 4 until a run
        # actually feeds them.
        self._metrics = MetricGrid(columns=4, compact=True)
        self._metric_progress = self._metrics.add_tile(("Progress", "0/0"))
        self._metric_eta = self._metrics.add_tile(("ETA", "--"))
        self._metric_point = self._metrics.add_tile(("Point", "x=-- y=-- z=--"))
        self._metric_elapsed = self._metrics.add_tile(("Elapsed", "--"))
        for tile in self._metrics.tiles():
            tile.set_stale(True, "no run yet")
        root.addWidget(self._metrics)

        # ── Run control ───────────────────────────────────────────────
        self._btn_pause = QPushButton("Pause")
        set_button_icon(self._btn_pause, "mdi.pause")
        self._btn_pause.setCheckable(True)
        self._btn_pause.setEnabled(False)
        self._btn_pause.toggled.connect(self._on_pause_toggled)

        self._btn_abort = QPushButton("Abort")
        set_button_icon(self._btn_abort, "mdi.stop", color="white")
        self._btn_abort.setEnabled(False)
        self._btn_abort.clicked.connect(self._on_abort_clicked)

        self._action_bar = ActionBar(secondary=self._btn_pause, danger=self._btn_abort)
        root.addWidget(self._action_bar)

        # ── Z-focus live assist ──────────────────────────────────────
        root.addWidget(self._build_z_focus_card())

    def _build_finished_banner(self) -> QFrame:
        """The FINISHED terminal state as a designed banner (design system
        §5: "FINISHED (good; banner + first-class 'Open in Analysis' + map
        retained stale)"). Hidden until a run ends; also carries the ABORTED
        variant (neutral-critical text, fail-safe caption) — the panel knows
        locally whether its own Abort was pressed before the finish arrived."""
        banner = QFrame()
        banner.setObjectName("cardPane")
        banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(banner)
        row.setContentsMargins(SPACE_SM + 4, SPACE_SM, SPACE_SM + 4, SPACE_SM)
        row.setSpacing(SPACE_SM)
        self._chip_finished = StatusChip("Finished", "good")
        row.addWidget(self._chip_finished)
        p = palette(self._theme_mode)
        self._lbl_finished = QLabel("Scan finished — map retained.")
        self._lbl_finished.setObjectName("finishedBannerText")
        self._lbl_finished.setStyleSheet(
            f"#finishedBannerText {{ color: {p['muted']}; "
            f"font-size: {FONT_BODY_PX}px; font-weight: {WEIGHT_BODY}; }}")
        row.addWidget(self._lbl_finished, 1)
        self._btn_open_analysis = QPushButton("Open in Analysis")
        set_button_icon(self._btn_open_analysis, "mdi.chart-box-outline")
        self._btn_open_analysis.setProperty("state", "primary")
        repolish(self._btn_open_analysis)
        self._btn_open_analysis.setEnabled(False)
        self._btn_open_analysis.clicked.connect(self._emit_open_in_analysis)
        row.addWidget(self._btn_open_analysis)
        banner.setVisible(False)
        self._finished_banner = banner
        return banner

    def _build_z_focus_card(self) -> CollapsibleCard:
        # Collapsed by default (design system §7): the header keeps a live
        # summary chip + the primary "Find focus" verb reachable at all
        # times; the form/curve expand on demand.
        card = CollapsibleCard(
            "Z focus",
            "focal-point assist — not a planner routine",
            expanded=False,
        )
        self._zf_card = card
        self._chip_best_z = StatusChip("No focus result", "neutral")
        card.add_header_widget(self._chip_best_z)

        self._zf_mode = QComboBox()
        self._zf_mode.addItem("Edge scan — sharpness (recommended)", "edge_scan")
        self._zf_mode.addItem("Amplitude max (legacy)", "amplitude")
        self._zf_mode.currentIndexChanged.connect(self._on_zf_mode_changed)

        form = QFormLayout()
        form.addRow("Mode:", self._zf_mode)

        self._zf_y = self._make_spin(0.0)
        self._zf_z0 = self._make_spin(-2.0, lo=-30.0, hi=30.0)
        self._zf_z1 = self._make_spin(2.0, lo=-30.0, hi=30.0)
        self._zf_dz = self._make_spin(0.1, lo=0.001, hi=5.0)
        self._zf_nav = QSpinBox()
        self._zf_nav.setRange(1, 100)
        self._zf_nav.setValue(3)
        self._zf_settle = self._make_spin(0.05, lo=0.0, hi=5.0, suffix=" s")

        form.addRow("Y (mm):", self._zf_y)
        form.addRow("Z start (mm):", self._zf_z0)
        form.addRow("Z stop  (mm):", self._zf_z1)
        form.addRow("Z step  (mm):", self._zf_dz)
        form.addRow("Averages:", self._zf_nav)
        form.addRow("Settle (s):", self._zf_settle)

        # Edge-scan parameters (shown only in edge_scan mode)
        self._zf_edge_frame = QFrame()
        edge_form = QFormLayout(self._zf_edge_frame)
        edge_form.setContentsMargins(0, 0, 0, 0)
        self._zf_edge_center = self._make_spin(0.0)
        self._zf_edge_range = self._make_spin(0.1, lo=0.001, hi=10.0)
        self._zf_edge_step = self._make_spin(0.005, lo=0.001, hi=1.0)
        edge_form.addRow("Edge X centre (mm):", self._zf_edge_center)
        edge_form.addRow("Edge X range  (mm):", self._zf_edge_range)
        edge_form.addRow("Edge X step   (mm):", self._zf_edge_step)
        form.addRow(self._zf_edge_frame)

        # Amplitude mode: fixed X
        self._zf_amp_frame = QFrame()
        amp_form = QFormLayout(self._zf_amp_frame)
        amp_form.setContentsMargins(0, 0, 0, 0)
        self._zf_x = self._make_spin(0.0)
        amp_form.addRow("X (mm):", self._zf_x)
        self._zf_amp_frame.setVisible(False)
        form.addRow(self._zf_amp_frame)

        self._lbl_best_z = QLabel("Best Z: --")
        self._btn_apply_best_z = QPushButton("Apply to Planner")
        set_button_icon(self._btn_apply_best_z, "mdi.arrow-right-bold-box-outline")
        self._btn_apply_best_z.setToolTip(
            "Stage the last Z-focus result as the selected Z loop's start "
            "in the Scan Planner (never moves the motor, never touches a "
            "running plan)"
        )
        self._btn_apply_best_z.setEnabled(False)
        self._btn_apply_best_z.clicked.connect(self._on_apply_best_z_clicked)
        best_z_row = QHBoxLayout()
        best_z_row.setContentsMargins(0, 0, 0, 0)
        best_z_row.addWidget(self._lbl_best_z)
        best_z_row.addStretch(1)
        best_z_row.addWidget(self._btn_apply_best_z)
        best_z_row_widget = QWidget()
        best_z_row_widget.setLayout(best_z_row)
        form.addRow(best_z_row_widget)
        card.add_layout(form)

        # Live Z-vs-amplitude curve — FigureCard (rule 3: no QGraphicsEffect).
        self._zf_figure = FigureCard("Edge sharpness vs Z", "z-focus live curve")
        self._zf_figure.plot.setLabel("left", "Sharpness (pC/mm)")
        self._zf_figure.plot.setLabel("bottom", "Z", units="mm")
        self._zf_figure.plot.setMaximumHeight(160)
        self._zf_curve = self._zf_figure.plot.plot(
            pen=pg.mkPen(axis_color("z", self._theme_mode), width=2))
        self._zf_marker = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen(PLOT_OVERLAY, width=2))
        self._zf_marker.setVisible(False)
        self._zf_figure.plot.addItem(self._zf_marker)
        card.add_widget(self._zf_figure)

        # "Find focus" lives in the HEADER (not the collapsible body) so the
        # card's primary verb stays one click away while collapsed.
        self._btn_zf_start = QPushButton("Find focus")
        set_button_icon(self._btn_zf_start, "mdi.crosshairs-gps")
        self._btn_zf_start.setProperty("state", "primary")
        repolish(self._btn_zf_start)
        self._btn_zf_start.clicked.connect(self._emit_z_focus)
        card.add_header_widget(self._btn_zf_start)

        return card

    def _make_spin(self, default: float, lo: float = -100.0, hi: float = 100.0,
                   suffix: str = " mm") -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(4)
        s.setValue(default)
        s.setSuffix(suffix)
        return s

    # ------------------------------------------------------------------ #
    # Slots IN — run monitor (mirrors gui/scan_coordinator.py signals)    #
    # ------------------------------------------------------------------ #

    def on_scan_started(self) -> None:
        self._run_active = True
        self._abort_pending = False
        # Invalidate the previous run's handoff path — without this, a run
        # that never publishes a fresh path (e.g. aborted before the writer
        # opened) would re-offer the *prior* run's file on finish.
        self._last_run_path = None
        self._start_time = time.monotonic()
        self._map_view.clear()
        self._map_view.set_empty_state_text(
            "Run starting", "Waiting for the first point.")
        self._btn_pause.setEnabled(True)
        self._btn_pause.setChecked(False)
        self._btn_pause.setText("Pause")
        self._btn_abort.setEnabled(True)
        self._btn_open_analysis.setEnabled(False)
        self._finished_banner.setVisible(False)
        self._chip_run.set_status("Running", "busy")
        self._metric_progress.set_value("0/0")
        self._metric_progress.set_stale(False, "")
        self._metric_eta.set_value("--")
        self._metric_eta.set_stale(True, "estimating")
        self._metric_point.set_value("x=-- y=-- z=--")
        self._metric_point.set_stale(True, "no point yet")
        self._metric_elapsed.set_value("0 s")
        self._metric_elapsed.set_stale(False, "")

    def on_scan_finished(self) -> None:
        self._run_active = False
        self._btn_pause.setEnabled(False)
        self._btn_pause.setChecked(False)
        self._btn_abort.setEnabled(False)
        # Terminal states differ (design system §5): FINISHED reads good;
        # an abort the user requested from THIS panel reads as the neutral-
        # critical ABORTED variant with a fail-safe caption. (A trip/FAULT
        # variant needs an error signal the coordinator does not carry yet.)
        if self._abort_pending:
            self._chip_run.set_status("Aborted", "warn")
            self._chip_finished.set_status("Aborted", "warn")
            self._lbl_finished.setText(
                "Scan aborted — hardware left safe, partial map retained.")
        else:
            self._chip_run.set_status("Finished", "good")
            self._chip_finished.set_status("Finished", "good")
            self._lbl_finished.setText("Scan finished — map retained.")
        self._abort_pending = False
        self._finished_banner.setVisible(True)
        # Law 4: the tiles stop updating now — say so instead of freezing
        # silently. Values stay readable (final numbers), ink goes stale.
        for tile in self._metrics.tiles():
            tile.set_stale(True, "final — run ended")
        if self._last_run_path:
            self._btn_open_analysis.setEnabled(True)

    def on_point_done(self, result: ScanResult) -> None:
        self._map_view.update_point(result)
        p = result.point
        self._metric_point.set_value(f"x={p.x_mm:.3f} y={p.y_mm:.3f} z={p.z_mm:.3f}")
        if self._run_active:
            self._metric_point.set_stale(False, "")

    def on_progress(self, done: int, total: int) -> None:
        self._metric_progress.set_value(f"{done}/{total}")
        eta = self._compute_eta(done, total)
        self._metric_eta.set_value(eta)
        if eta != "--":
            self._metric_eta.set_stale(False, "")
        self._metric_elapsed.set_value(self._format_duration(self._elapsed_s()))
        flash_readout(self._metric_progress, "accent", timeout_ms=450)

    def on_manual_pause(self, msg: str) -> None:
        self._chip_run.set_status(f"Manual pause: {msg}"[:60], "warn")

    def set_current_position(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        self._metric_point.set_value(f"x={x_mm:.3f} y={y_mm:.3f} z={z_mm:.3f}")
        if self._run_active:
            self._metric_point.set_stale(False, "")

    def set_last_run_path(self, path: str | None) -> None:
        """Learn the just-written run's HDF5 path (see class docstring)."""
        self._last_run_path = path
        if not self._run_active:
            self._btn_open_analysis.setEnabled(bool(path))

    # ------------------------------------------------------------------ #
    # Slots IN — Z-focus                                                  #
    # ------------------------------------------------------------------ #

    def on_z_focus_pt(self, z_mm: float, amplitude_V: float) -> None:
        self._zf_z_data.append(z_mm)
        self._zf_a_data.append(amplitude_V)
        self._zf_curve.setData(self._zf_z_data, self._zf_a_data)

    def on_z_focus_done(self, best_z_mm: float) -> None:
        mode = self._zf_mode.currentData()
        mode_label = "edge scan" if mode == "edge_scan" else "amplitude"
        self._lbl_best_z.setText(f"Best Z: {best_z_mm:.3f} mm  ({mode_label})")
        # Header chip: the collapsed card's live summary (§7 "header chip").
        self._chip_best_z.set_status(
            f"Best Z {best_z_mm:.3f} mm", "neutral",
            f"from {mode_label} — Apply to Planner stages it, never moves the motor")
        self._zf_marker.setValue(best_z_mm)
        self._zf_marker.setVisible(True)
        self._last_best_z = float(best_z_mm)
        self._btn_apply_best_z.setEnabled(True)

    # ------------------------------------------------------------------ #
    # Internal — run control                                              #
    # ------------------------------------------------------------------ #

    def _on_pause_toggled(self, paused: bool) -> None:
        self._btn_pause.setText("Resume" if paused else "Pause")
        self._chip_run.set_status("Paused" if paused else "Running",
                                   "warn" if paused else "busy")
        # Only forward user-initiated toggles while a run is active — the
        # programmatic un-check in on_scan_started/finished must not resume.
        if self._btn_pause.isEnabled():
            self.pause_requested.emit(paused)

    def _on_abort_clicked(self) -> None:
        self._abort_pending = True
        self._chip_run.set_status("Aborting", "warn")
        self.abort_requested.emit()

    def _elapsed_s(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    def _compute_eta(self, done: int, total: int) -> str:
        if done <= 0 or total <= 0:
            return "--"
        elapsed = self._elapsed_s()
        if elapsed <= 0:
            return "--"
        rate = done / elapsed
        if rate <= 0:
            return "--"
        remaining = max(0, total - done)
        return self._format_duration(remaining / rate)

    @staticmethod
    def _format_duration(seconds: float | None) -> str:
        if seconds is None:
            return "--"
        seconds = max(0.0, float(seconds))
        if seconds < 60:
            return f"{seconds:.0f} s"
        if seconds < 3600:
            return f"{seconds / 60:.1f} min"
        return f"{seconds / 3600:.1f} h"

    # ------------------------------------------------------------------ #
    # Internal — Z-focus                                                  #
    # ------------------------------------------------------------------ #

    def _on_zf_mode_changed(self) -> None:
        mode = self._zf_mode.currentData()
        is_edge = (mode == "edge_scan")
        self._zf_edge_frame.setVisible(is_edge)
        self._zf_amp_frame.setVisible(not is_edge)
        if is_edge:
            self._zf_figure.set_title("Edge sharpness vs Z")
            self._zf_figure.plot.setLabel("left", "Sharpness (pC/mm)")
        else:
            self._zf_figure.set_title("Amplitude vs Z")
            self._zf_figure.plot.setLabel("left", "Amplitude", units="V")

    def _emit_z_focus(self) -> None:
        self._zf_z_data = []
        self._zf_a_data = []
        self._zf_curve.setData([], [])
        self._zf_marker.setVisible(False)
        self._lbl_best_z.setText("Best Z: --")
        self._chip_best_z.set_status("Focus scan running", "busy")
        self._last_best_z = None
        self._btn_apply_best_z.setEnabled(False)
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

    def _emit_open_in_analysis(self) -> None:
        if self._last_run_path:
            self.open_in_analysis_requested.emit(self._last_run_path)

    def _on_apply_best_z_clicked(self) -> None:
        """Stage the last Z-focus result in the Planner (G4). Emits only —
        this panel never touches the Planner's plan or the motor directly."""
        if self._last_best_z is not None:
            self.best_z_apply_requested.emit(self._last_best_z)

    # ------------------------------------------------------------------ #
    # Theme                                                               #
    # ------------------------------------------------------------------ #

    def refresh_theme(self, mode: str | None = None) -> None:
        if mode:
            self._theme_mode = str(mode)
        self._map_view.refresh_theme(self._theme_mode)
        # Banner prose colour is baked at construction — re-resolve it.
        p = palette(self._theme_mode)
        self._lbl_finished.setStyleSheet(
            f"#finishedBannerText {{ color: {p['muted']}; "
            f"font-size: {FONT_BODY_PX}px; font-weight: {WEIGHT_BODY}; }}")
        self._zf_curve.setPen(pg.mkPen(axis_color("z", self._theme_mode), width=2))
        self._zf_marker.setPen(pg.mkPen(PLOT_OVERLAY, width=2))
