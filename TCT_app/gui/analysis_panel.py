"""
Post-scan analysis panel.

Loads an existing HDF5 run file and provides:
  - 2-D map re-plotting with any stored quantity (via the shared
    :class:`~gui.scan_map_view.ScanMapView` — the single map renderer, so
    viridis / NaN-honesty / colorbar-unit rules apply here too)
  - CCE vs. bias voltage curve (from a bias scan HDF5 file), with the
    depletion-voltage estimate drawn as an annotated line (design system §4)
    plus a fit-quality tile row (V_dep / Quality / Flags / Ref σ, from
    ``analysis.efield_analysis.fit_depletion_voltage`` /
    ``compute_cce_with_uncertainty`` — see ``_update_cce_fit_tiles``)
  - Export analysis results to CSV

Cockpit v5 layout (design system §7 "Analysis"): the empty state is a
recent-runs list (newest first, click to load, plus a browse row); loading
swaps to a compact run-header bar over segmented 2D-map / CCE modes.

Round-03 glass kit migration (wave beat 11/12, mirrors ``ScopePanel``/
``CameraPanel``): the whole panel is now ONE ``GlassPane`` shelf
(``register=False`` — a CONTENT consequence, not a hazard stance; this is a
census NON-hazard panel). The shelf's body hosts, at some descendant depth,
three pyqtgraph ``FigureCard``\\ s (the line-cut profile, CCE-vs-bias and
survey-mosaic plots — Z3 instrument screens, refused outright by
``register_glass_pane``'s own hard exclusion) plus several ``MetricGrid``\\ s
of ``MetricTile`` readouts (Z4 — CCE fit-quality tiles, survey/pose
diagnostic tiles). Registering the shelf itself would put those Z3/Z4
surfaces behind a glass pane, exactly what the live-registry census in
``tests/test_panel_glass_rollout.py`` refuses.

This panel registers **nothing**: its only two plain ``Card`` instances
(besides the auto-excluded ``FigureCard``\\ s) are the compact run-header bar
(hosts the live ``_lbl_file`` filename label plus four live ``StatusChip``\\ s
— file/dataset/map/export status, all of which repaint on every load) and the
"Recent runs" empty-state card (hosts a ``QListWidget`` of run entries — a
data listing, the same Z4-adjacent "live data table" class
``gui/device_panel.py``'s bulk-actions precedent excludes its own
``QTableWidget`` card for). Neither is pure parameter/button chrome, so
neither registers — see ``_build_ui``'s inline comments for the per-card
reasoning. Matches the "expect to register little" default for a
plot/readout-heavy analysis panel (cockpit_style_overhaul.md §1 hard rule 3 /
docs/design/iterations/glasshell-cockpit/round-03/kit.md's Z-ladder).
"""
from __future__ import annotations

import csv
import json
import logging
import math
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton,
    QDoubleSpinBox, QSpinBox, QFileDialog, QStackedWidget,
    QSplitter, QToolButton, QCheckBox, QApplication,
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

from analysis.camera_calibration import AffineFit
from analysis.cce import cce_vs_reference
from analysis.efield_analysis import compute_cce_with_uncertainty, fit_depletion_voltage
from analysis.map_slice import (
    display_unit_scale, mm_to_index, slice_grid_at_mm, strip_unit_suffix,
)
from analysis.mosaic_stitch import canvas_geometry, place_tiles, plan_grid
from analysis.scan_grid import grid_extent
from gui.motion_kit import fade_swap
from gui.panel_kit import (
    Card, EmptyState, FigureCard, GlassPane, MetricGrid, MetricTile,
    SegmentedControl, panel_header,
)
from gui.scan_map_view import QUANTITIES, QUANTITY_UNITS, ScanMapView
from gui.status_widgets import StatusChip, flash_button, set_button_icon
from gui.style import DARK, PLOT_FG, PLOT_OVERLAY, SPACE_MD, SPACE_SM
from vision import sensor_align

# Survey mode's mosaic mode ("map"/"cce"/"survey" -> _modes stack index) —
# module-level so the segmented-control wiring and any future page reorder
# stay in one place instead of a positional 0/1/2 guess at each call site.
_SURVEY_MODE_INDEX = {"map": 0, "cce": 1, "survey": 2}

logger = logging.getLogger(__name__)

# How many recent .h5 files the empty-state list offers.
_RECENT_RUNS_MAX = 8

# Fit-quality tile banding (D3 — see AnalysisPanel._update_cce_fit_tiles).
# DepletionFitResult.quality is the 0-1 heuristic documented on that
# dataclass (bracket density + plateau flatness + monotonicity, unweighted
# mean — see analysis/efield_analysis.py). These two thresholds turn it
# into the Quality tile's 3-band read:
#   quality >= _QUALITY_OK_MIN    -> "ok"   trust v_dep at face value.
#   quality >= _QUALITY_WARN_MIN  -> "warn" usable but shaky (sparse
#                                    bracket and/or a noisy post-crossing
#                                    plateau) — worth a second look.
#   quality <  _QUALITY_WARN_MIN  -> "crit" do not trust v_dep without
#                                    checking the raw sweep by eye.
# "ok" renders as MetricTile's "normal" (quiet grey) state, deliberately
# NOT "good" (green): design law 1 ("quiet nominal" — the accent/green is
# spent sparingly and never means "good",
# docs/design/cockpit_design_system.md §1) — the same precedent
# gui/monitor_panel.py already sets, downgrading a nominal alarm reading
# from "good" to "normal".
_QUALITY_OK_MIN = 0.7
_QUALITY_WARN_MIN = 0.4


def _flags_tile_content(fit) -> tuple[str, str]:
    """Flags tile (value text, MetricTile state) from one
    ``DepletionFitResult`` — "clean" when unambiguous, otherwise a badge
    list built from the exact two sub-conditions ``fit.ambiguous`` itself
    is defined from (``n_crossings > 1``, ``not monotonic`` — see the
    dataclass docstring). A real charge reversal (non-monotonic) is a more
    serious data-quality signal than sweep noise alone re-crossing an
    already-flat threshold, so that alone earns "crit"; multiple crossings
    on an otherwise monotonic sweep is "warn"."""
    if not fit.ambiguous:
        return "clean", "normal"
    parts: list[str] = []
    if fit.n_crossings > 1:
        parts.append(f"AMBIGUOUS ({fit.n_crossings}×)")
    if not fit.monotonic:
        parts.append("NON-MONOTONIC")
    if not parts:
        # Defensive only: fit.ambiguous is defined as one of the two checks
        # above, so this is unreachable given today's DepletionFitResult —
        # kept so a future change to that contract degrades honestly
        # instead of showing a blank badge.
        parts.append("AMBIGUOUS")
    state = "crit" if not fit.monotonic else "warn"
    return ", ".join(parts), state


def _affine_from_stored(raw: "np.ndarray | None") -> AffineFit | None:
    """Reconstruct an :class:`~analysis.camera_calibration.AffineFit` from
    ``camera`` group attr ``affine`` (``data/hdf5_writer.py``'s
    ``set_camera_calibration`` — "stored as a flat float64 array attr ...
    the writer does not interpret its shape").

    The only convention actually exercised anywhere in this codebase today
    (``tests/test_data_writer.py::test_set_camera_calibration_attrs_round_trip``)
    is a ``(2, 3)`` array: columns ``0:2`` are ``matrix_px_per_mm`` (2x2),
    column ``2`` is ``offset_px`` (the classic 2x3 affine-matrix layout).
    Since ``set_camera_calibration``'s caller (the A4b camera/motor
    plumbing) has not landed yet, this is the reader-side half of that
    convention — documented here so both sides agree once a real writer
    call site exists. Any other shape (or ``None``) is honestly reported as
    unparseable rather than guessed at; the caller falls back to nominal
    (``affine=None``) placement — see Survey mode's calibration notice.

    Only ``matrix_px_per_mm``/``offset_px`` are real; the remaining
    dataclass fields (fit-quality diagnostics that were never persisted)
    are filled with honest "no data" placeholders — never used by
    :func:`~analysis.mosaic_stitch.place_tiles`'s placement math, which
    only reads ``predict``/``image_to_object`` (matrix + offset).
    """
    if raw is None:
        return None
    arr = np.asarray(raw, dtype=np.float64)
    if arr.shape != (2, 3):
        return None
    return AffineFit(
        matrix_px_per_mm=arr[:, :2].copy(),
        offset_px=arr[:, 2].copy(),
        residuals_px=np.zeros((0, 2), dtype=np.float64),
        rms_px=0.0,
        max_abs_px=0.0,
        rank=2,
    )


def _vision_unavailable_reason() -> str:
    """Best-effort capture of :class:`~vision.sensor_align.
    VisionUnavailableError`'s own install-hint message (E7c objective 1:
    "install hint from VisionUnavailableError when cv2 missing") — never
    hand-duplicated here, so it can't drift from that class's own text.

    Only called once ``sensor_align.is_available()`` has already returned
    ``False`` (see ``_update_pose_availability``), so
    ``generate_marker_image`` always hits ``sensor_align``'s own cv2-import
    gate immediately and never actually renders a marker image — safe to
    call unconditionally from the disabled-tooltip path."""
    try:
        sensor_align.generate_marker_image(0, 4)
    except sensor_align.VisionUnavailableError as exc:
        return str(exc)
    except Exception:
        pass
    return ""


class AnalysisPanel(QWidget):
    """Load a completed run HDF5 file and re-analyse / re-plot.

    *runs_dir* is where the recent-runs empty state looks for ``*.h5`` files
    (default matches ``output.data_dir``'s default in ``configs/devices.yaml``
    — run folders like ``runs/run_00001/waveforms.h5``). Purely a read-only
    listing; nothing is written there by this panel.
    """

    # E7c "Align scan grid" — HARD LAW: numbers only, never motion. Carries
    # the suggested correction as a plain dict (theta_deg/dx_mm/dy_mm/
    # baseline_px/estimated_precision_deg/meets_precision_target — see
    # _on_align_scan_grid). This class never imports controller/ and this
    # signal is the ONLY output of the "Align scan grid" button; the
    # eventual consumer (a later, danger-gated beat) decides whether/how to
    # apply it to a plan or motion.
    grid_alignment_suggested = Signal(dict)

    def __init__(self, parent: QWidget | None = None,
                 runs_dir: str | Path = "runs") -> None:
        super().__init__(parent)
        self._runs_dir = Path(runs_dir)
        self._data: dict = {}          # loaded HDF5 data arrays
        self._voltage_scan: dict = {}  # loaded 'voltage_scan/{voltage_V,charge_pC,current_A}'
        # Survey (mosaic) state — see _load_h5's 'camera'/'run_info' reads
        # and _build_survey_mode/_build_survey_mosaic. '_camera' holds the
        # loaded camera group (frames/frame_pos_mm/px_per_mm/affine_fit/
        # n_frames_omitted); '_survey_geom' is the safety['survey'] geometry
        # block parsed out of run_info/scan_config JSON (None when absent —
        # see SCAN_DATA_FORMAT.md's CAPTURE_PHOTO section), the position
        # fallback for a photo-only survey written before camera/
        # frame_pos_mm existed. '_survey_position_source' names which ladder
        # rung the most recent _collect_survey_tiles() call actually used
        # ("frame_pos_mm" / "geometry"); '_survey_n_pos_omitted' is that
        # call's honest count of written-but-unplaceable frames (NaN
        # position, or beyond the reconstructed grid).
        self._camera: dict = {}
        self._survey_geom: dict | None = None
        self._survey_position_source: str | None = None
        self._survey_n_pos_omitted: int = 0
        self._survey_theme_mode: str = "dark"
        # Sensor-pose alignment (E7c) — see _on_detect_sensor_pose/
        # _on_align_scan_grid. '_survey_pose' is the last
        # vision.sensor_align.PoseEstimate (None before any detect, or
        # after a new run load — see _reset_pose_state); '_survey_pose_items'/
        # '_survey_pose_bbox' are the pyqtgraph overlay items on the mosaic
        # plot, cleared/rebuilt on every detect (see _clear_pose_overlay).
        self._survey_pose: "sensor_align.PoseEstimate | None" = None
        self._survey_pose_items: list = []
        self._survey_pose_bbox = None
        self._run_path: str = ""
        # How the loaded run ended (HDF5Writer root attrs 'outcome' /
        # 'abort_reason' — SCAN_DATA_FORMAT.md "Root attributes"). None
        # before any load, or for a file written before this attr existed.
        # An analyst can read these directly; a dedicated UI treatment
        # (e.g. a status chip) is a follow-up, not done here.
        self._run_outcome: str | None = None
        self._run_abort_reason: str = ""
        self._build_ui()
        self._refresh_recent_runs()

    # ------------------------------------------------------------------ #
    # UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        root.setSpacing(SPACE_MD)

        # ── The one shelf (round-03 kit §2.1) ──────────────────────────
        # register=False is a CONTENT consequence, not a hazard stance (this
        # is a census NON-hazard panel): the shelf's body hosts, at some
        # descendant depth, three pyqtgraph FigureCards (line-cut profile /
        # CCE-vs-bias / survey mosaic — Z3 instrument screens) and several
        # MetricGrid rows of MetricTile readouts (Z4) — the live-registry
        # census in tests/test_panel_glass_rollout.py refuses glass on any
        # pane with a plot/readout descendant, hazard or not. See the module
        # docstring for the two plain Cards' own (both "no") register calls.
        shelf = GlassPane(register=False)
        self._shelf = shelf
        shelf.add_widget(panel_header("TCT Control · Analysis", "Run Analysis"))

        # ── Compact run-header bar (always visible) ───────────────────
        # File identity + load/export status chips + Browse in ONE row —
        # the §7 "compact run-header bar" that replaces the old full-height
        # file-loader card.
        # Never registered for glass: hosts the live _lbl_file filename
        # label plus four live StatusChips (file/dataset/map/export status),
        # all of which repaint on every load — live-value content, not pure
        # button/parameter chrome (the Browse button alone would qualify,
        # but this card is not just that button).
        header_card = Card(None, margins=(SPACE_SM + 2, SPACE_SM, SPACE_SM + 2, SPACE_SM))
        self._header_card = header_card
        bar = QHBoxLayout()
        bar.setSpacing(SPACE_SM)
        self._btn_open = QPushButton("Browse…")
        self._btn_open.setProperty("state", "ghost")
        set_button_icon(self._btn_open, "mdi.folder-open")
        self._btn_open.clicked.connect(self._open_file)
        bar.addWidget(self._btn_open)
        self._lbl_file = QLabel("No file loaded")
        self._lbl_file.setWordWrap(True)
        bar.addWidget(self._lbl_file, 1)
        self._chip_file = StatusChip("No file", "neutral")
        self._chip_dataset = StatusChip("No dataset", "neutral")
        self._chip_map = StatusChip("No map", "neutral")
        self._chip_export = StatusChip("No export", "neutral")
        for chip in (self._chip_file, self._chip_dataset, self._chip_map, self._chip_export):
            bar.addWidget(chip)
        header_card.add_layout(bar)
        shelf.body.addWidget(header_card)

        # ── Empty state (recent runs) <-> loaded analysis stack ──────
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_recent_runs_page())   # index 0
        self._stack.addWidget(self._build_loaded_page())        # index 1
        shelf.body.addWidget(self._stack, 1)

        root.addWidget(shelf, 1)

    def _build_recent_runs_page(self) -> QWidget:
        """The designed empty state: the last N run files, newest first —
        click to load — plus a browse row (§7)."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        # Never registered for glass: hosts a QListWidget of run entries — a
        # data listing, the same Z4-adjacent "live data table" class
        # gui/device_panel.py's own table card is excluded for (its own
        # bulk-actions Card registers instead; this panel has no such
        # separate pure-chrome sibling to register in its place).
        card = Card("Recent runs", str(self._runs_dir))
        self._recent_runs_card = card
        self._lbl_recent_hint = QLabel(
            "Click a run to load it, or browse for any HDF5 file.")
        self._lbl_recent_hint.setObjectName("cardSubtitle")
        self._lbl_recent_hint.setWordWrap(True)
        card.add_widget(self._lbl_recent_hint)
        self._list_recent = QListWidget()
        self._list_recent.itemClicked.connect(self._on_recent_clicked)
        card.add_widget(self._list_recent)
        browse_row = QHBoxLayout()
        self._btn_browse_empty = QPushButton("Browse for a run file…")
        self._btn_browse_empty.setProperty("state", "secondary")
        set_button_icon(self._btn_browse_empty, "mdi.folder-open")
        self._btn_browse_empty.clicked.connect(self._open_file)
        browse_row.addStretch(1)
        browse_row.addWidget(self._btn_browse_empty)
        card.add_layout(browse_row)
        lay.addWidget(card, 1)
        return page

    def _build_loaded_page(self) -> QWidget:
        """Segmented 2D-map / CCE modes (§7) over a mode stack."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE_SM)

        self._segmented = SegmentedControl(
            [("map", "2D map"), ("cce", "CCE vs bias"), ("survey", "Survey")],
            current="map")
        seg_row = QHBoxLayout()
        seg_row.addWidget(self._segmented)
        seg_row.addStretch(1)
        lay.addLayout(seg_row)

        self._modes = QStackedWidget()
        self._modes.addWidget(self._build_map_mode())      # index 0
        self._modes.addWidget(self._build_cce_mode())      # index 1
        self._modes.addWidget(self._build_survey_mode())   # index 2
        # A BOUND METHOD, never a lambda: PySide6 holds bound-method slots
        # weakly, so this connection does not keep the panel alive. A lambda
        # capturing ``self`` and connected to a CHILD's signal (as this once
        # was) forms panel -> child -> C++ connection -> closure -> panel — a
        # cycle with one hop inside Qt that Python's gc cannot traverse, so the
        # whole panel tree (~835 widgets) becomes immortal. See
        # tests/test_no_immortal_panels.py.
        self._segmented.selection_changed.connect(self._on_survey_mode_selected)
        lay.addWidget(self._modes, 1)
        return page

    def _on_survey_mode_selected(self, key: str) -> None:
        """Cross-fade the mode stack to the segment the user picked.

        fade_swap (gui/motion_kit.py): a static QPixmap snapshot cross-fade,
        never a QGraphicsEffect on this stack or its pages — 2/3 of them host a
        pyqtgraph plot (ScanMapView/CCE), which the hot-path law bans an effect
        on. See fade_swap's own docstring for the mechanism.
        """
        fade_swap(self._modes, _SURVEY_MODE_INDEX.get(key, 0))

    def _build_map_mode(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE_SM)

        # 1D slicer state — defined before any control below is built/wired
        # so a signal that could (in principle) fire during construction
        # never hits an undefined attribute.
        self._slice_active = False
        self._slice_syncing = False   # re-entrancy guard, spin <-> cut line

        # The SHARED map renderer (single source of viridis/NaN-honesty/
        # colorbar-unit truth) — its own toolbar provides quantity switch,
        # freeze-levels and PNG/per-quantity-CSV export.
        self._map_view = ScanMapView(
            empty_label="No map data",
            empty_hint="This file has no x/y map arrays for the selected quantity.",
        )
        # Back-compat hook: quantity selection now lives on the shared map
        # widget; existing callers/tests drive panel._combo_qty.
        self._combo_qty = self._map_view._combo_qty
        self._combo_qty.currentTextChanged.connect(self._update_map_info)
        # Slicer recompute wired DIRECTLY to the combo, not nested inside
        # _update_map_info's tail — _update_map_info early-returns as soon
        # as the newly selected quantity isn't stored in this file (honest
        # "Map missing" chip), and that must not also leave the profile
        # plot showing the PREVIOUS quantity's stale curve/label/unit
        # (Mary review, REQUEST-CHANGES on 9b91ed1). _update_slice_profile
        # already self-guards on _HAS_PG/_slice_active, so this is a no-op
        # whenever the slicer is off.
        self._combo_qty.currentTextChanged.connect(self._update_slice_profile)

        lay.addLayout(self._build_slice_row())

        # Map (top) + line-cut profile (bottom, hidden until "Slice" is
        # toggled on) — a splitter so a physicist can grow the profile once
        # it's the thing they're reading (design brief: "profile plot below
        # or beside the map, splitter").
        self._map_splitter = QSplitter(Qt.Orientation.Vertical)
        self._map_splitter.addWidget(self._map_view)
        if _HAS_PG:
            # Non-empty initial subtitle: Card only builds a subtitle QLabel
            # at all when constructed with truthy text (gui/panel_kit.py
            # Card/section_header) — an empty string here would leave
            # set_subtitle() a permanent, silent no-op for this card's whole
            # life. Matches ScanMapView's own "no data" convention.
            self._slice_figure = FigureCard("Line-cut profile", "no data")
            self._slice_curve = self._slice_figure.plot.plot(
                pen=pg.mkPen(PLOT_FG, width=2))
            self._slice_figure.setVisible(False)
            self._map_splitter.addWidget(self._slice_figure)
            self._map_splitter.setStretchFactor(0, 3)
            self._map_splitter.setStretchFactor(1, 2)
            self._build_slice_overlay()
        else:  # pragma: no cover - exercised only without pyqtgraph installed
            self._slice_figure = None
            self._slice_curve = None
        lay.addWidget(self._map_splitter, 1)

        info_row = QHBoxLayout()
        # objectName "cardSubtitle" reuses the shared muted/monospace QSS
        # hook (gui/style.py) — repaints on a live theme switch via the
        # app-wide stylesheet.
        self._lbl_map_info = QLabel("")
        self._lbl_map_info.setObjectName("cardSubtitle")
        self._lbl_map_info.setWordWrap(True)
        info_row.addWidget(self._lbl_map_info, 1)
        self._btn_export_csv = QPushButton("Export all arrays (CSV)")
        self._btn_export_csv.setProperty("state", "secondary")
        set_button_icon(self._btn_export_csv, "mdi.content-save")
        self._btn_export_csv.clicked.connect(self._export_csv)
        info_row.addWidget(self._btn_export_csv)
        lay.addLayout(info_row)
        return page

    def _build_slice_row(self) -> QHBoxLayout:
        """Toolbar for the 1D slicer: on/off toggle + X/Y orientation +
        position + averaging width + CSV export. The controls (everything
        but the toggle itself) stay hidden until "Slice" is checked."""
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)

        self._btn_slice = QToolButton()
        self._btn_slice.setCheckable(True)
        self._btn_slice.setText("Slice")
        self._btn_slice.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn_slice.setToolTip(
            "1D line-cut — drag a cut line across the map for a "
            "value-vs-position profile (the canonical edge-TCT depth plot)")
        set_button_icon(self._btn_slice, "mdi.chart-timeline-variant")
        self._btn_slice.toggled.connect(self._on_slice_toggled)
        row.addWidget(self._btn_slice)

        self._slice_seg = SegmentedControl([("x", "X"), ("y", "Y")], current="x")
        self._slice_seg.selection_changed.connect(self._on_slice_axis_changed)
        row.addWidget(self._slice_seg)

        self._lbl_slice_pos = QLabel("Position:")
        row.addWidget(self._lbl_slice_pos)
        self._spin_slice_pos = QDoubleSpinBox()
        self._spin_slice_pos.setDecimals(4)
        self._spin_slice_pos.setSuffix(" mm")
        self._spin_slice_pos.setRange(-1e6, 1e6)
        self._spin_slice_pos.valueChanged.connect(self._on_slice_pos_spin_changed)
        row.addWidget(self._spin_slice_pos)

        self._lbl_slice_width = QLabel("Avg width ±:")
        row.addWidget(self._lbl_slice_width)
        self._spin_slice_width = QSpinBox()
        self._spin_slice_width.setRange(0, 200)
        self._spin_slice_width.setSuffix(" pts")
        self._spin_slice_width.setToolTip(
            "Average ±N rows/cols across the cut (0 = single row/column, "
            "no averaging)")
        self._spin_slice_width.valueChanged.connect(self._on_slice_width_changed)
        row.addWidget(self._spin_slice_width)

        self._btn_slice_export = QPushButton("Export slice (CSV)")
        self._btn_slice_export.setProperty("state", "secondary")
        set_button_icon(self._btn_slice_export, "mdi.content-save")
        self._btn_slice_export.clicked.connect(self._export_slice_csv)
        row.addWidget(self._btn_slice_export)

        row.addStretch(1)

        self._slice_control_widgets = [
            self._slice_seg, self._lbl_slice_pos, self._spin_slice_pos,
            self._lbl_slice_width, self._spin_slice_width, self._btn_slice_export,
        ]
        for w in self._slice_control_widgets:
            w.setVisible(False)
        return row

    def _build_slice_overlay(self) -> None:
        """Draggable cut line + (non-movable) averaging-band region on the
        shared map's own PlotItem — built once, visibility toggled with the
        "Slice" control rather than added/removed per toggle."""
        plot_item = self._map_view.image_view().view
        self._slice_line = pg.InfiniteLine(
            angle=0, movable=True, pen=pg.mkPen(PLOT_FG, width=1))
        self._slice_line.setVisible(False)
        self._slice_line.sigPositionChanged.connect(self._on_slice_line_moved)
        plot_item.addItem(self._slice_line)

        # Outline-only — no translucent fill (Mary review ruling, overrules
        # the original alpha-40 fill call: §1a's translucency-over-hue-data
        # ban keys on the SUBSTRATE. The averaging band sits directly on
        # viridis image-data pixels — hue-encoded, hue IS the value — so the
        # scope_panel._int_region precedent (a flat PLOT_BG canvas, no hue
        # encoding) does not transfer here. brush=None keeps the pen-only
        # edges, which already show which rows/cols are averaged).
        band_pen = pg.mkPen(PLOT_OVERLAY, width=1)
        # Two pre-built regions (one per orientation) rather than mutating
        # one in place — pyqtgraph's LinearRegionItem has no public
        # setOrientation(), so switching X<->Y swaps which one is visible.
        self._slice_band_h = pg.LinearRegionItem(
            orientation="horizontal", movable=False, brush=None, pen=band_pen)
        self._slice_band_v = pg.LinearRegionItem(
            orientation="vertical", movable=False, brush=None, pen=band_pen)
        for band in (self._slice_band_h, self._slice_band_v):
            band.setVisible(False)
            plot_item.addItem(band)

    def _build_cce_mode(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE_SM)

        ctrl = QFormLayout()
        self._spin_ref_charge = QDoubleSpinBox()
        self._spin_ref_charge.setRange(0.001, 1000.0)
        self._spin_ref_charge.setDecimals(3)
        self._spin_ref_charge.setValue(1.0)
        self._spin_ref_charge.setSuffix(" pC")
        self._spin_ref_charge.setToolTip(
            "Reference charge at full depletion — CCE = Q / Q_ref"
        )
        ctrl.addRow("Q_ref (full depletion):", self._spin_ref_charge)
        lay.addLayout(ctrl)

        btn_row = QHBoxLayout()
        btn_plot_cce = QPushButton("Plot CCE vs bias")
        btn_plot_cce.setProperty("state", "secondary")
        set_button_icon(btn_plot_cce, "mdi.chart-line")
        btn_plot_cce.clicked.connect(self._plot_cce)
        self._btn_export_cce = QPushButton("Export CCE CSV")
        self._btn_export_cce.setProperty("state", "secondary")
        set_button_icon(self._btn_export_cce, "mdi.content-save")
        self._btn_export_cce.clicked.connect(self._export_cce_csv)
        btn_row.addWidget(btn_plot_cce)
        btn_row.addWidget(self._btn_export_cce)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        if _HAS_PG:
            # Data ink on the fixed-dark instrument canvas: colours resolve
            # once against the theme-invariant PLOT_BG, so no per-theme
            # refresh is needed (same idiom as the scope markers). CCE wears
            # the accent; the leakage overlay wears the (amber) overlay
            # token — deliberately NOT red, which is reserved for HV danger
            # (law 2 / §4 "warm end must not be confusable with HV red").
            self._cce_figure = FigureCard(
                "CCE vs bias", "CCE = |Q| / |Q_ref|")
            self._cce_plot = self._cce_figure.plot
            self._cce_plot.setLabel("left",   "CCE / norm. charge")
            self._cce_plot.setLabel("bottom", "Bias voltage", units="V")
            self._cce_plot.addLegend()
            self._cce_curve_cce = self._cce_plot.plot(
                pen=pg.mkPen(DARK["accent"], width=2), symbol="o", symbolSize=5,
                name="CCE",
            )
            self._cce_curve_iv = self._cce_plot.plot(
                pen=pg.mkPen(PLOT_OVERLAY, width=1), symbol="t", symbolSize=4,
                name="Leakage (µA, scaled)",
            )
            # Depletion-voltage estimate as an annotated line ON the curve
            # (§4), not just a text footnote.
            # Label states the sign convention explicitly (§4): the marker
            # sits at the SIGNED depletion voltage (same convention as the
            # x-axis data — see _plot_cce), but estimate_depletion_voltage()
            # itself only ever returns a magnitude, so the label spells out
            # "(|V|)" to avoid implying the number itself is unsigned.
            self._vdep_line = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen(PLOT_OVERLAY, width=1, style=Qt.PenStyle.DashLine),
                label="V_dep ≈ {value:+.0f} V (|V|)",
                labelOpts={"position": 0.9, "color": PLOT_OVERLAY},
            )
            self._vdep_line.setVisible(False)
            self._cce_plot.addItem(self._vdep_line)
            # cce ± sigma (compute_cce_with_uncertainty) — only ever shown
            # with real (nonzero) sigma content, see _update_cce_fit_tiles.
            self._cce_errorbar = pg.ErrorBarItem(pen=pg.mkPen(DARK["accent"], width=1))
            self._cce_errorbar.setVisible(False)
            self._cce_plot.addItem(self._cce_errorbar)
            # Depletion-fit bracket — the two |V| points straddling the
            # threshold crossing — as a light shaded band. Outline + light
            # fill is fine here (unlike the map slicer's averaging band):
            # this plot's canvas is flat PLOT_BG, not viridis hue-encoded
            # image data, so the "no translucency over hue data" ruling
            # (see _build_slice_overlay) doesn't apply — same reasoning as
            # scope_panel._int_region's shaded integration window.
            bracket_fill = QColor(PLOT_OVERLAY)
            bracket_fill.setAlpha(40)
            self._cce_bracket_region = pg.LinearRegionItem(
                movable=False, brush=pg.mkBrush(bracket_fill),
                pen=pg.mkPen(PLOT_OVERLAY, width=1),
            )
            self._cce_bracket_region.setVisible(False)
            self._cce_plot.addItem(self._cce_bracket_region)
            lay.addWidget(self._cce_figure, 1)

            # V_dep estimate + convention/Q_ref provenance (§4: "CCE plots
            # label the convention + Q_ref used").
            self._lbl_vdep = QLabel("V_dep estimate: —")
            self._lbl_vdep.setObjectName("cardSubtitle")
            lay.addWidget(self._lbl_vdep)

            # Fit-quality tile row (D3): V_dep / Quality / Flags / Ref σ,
            # from analysis.efield_analysis.fit_depletion_voltage /
            # compute_cce_with_uncertainty — see _update_cce_fit_tiles and
            # the _QUALITY_OK_MIN/_QUALITY_WARN_MIN module comment.
            # compact=True: a secondary detail row under the plot's hero
            # role (same idiom as gui/monitor_panel.py's dashboard tiles).
            self._cce_fit_tiles = MetricGrid(columns=4, compact=True)
            self._tile_vdep: MetricTile = self._cce_fit_tiles.add_tile(("V_dep", "—"))
            self._tile_quality: MetricTile = self._cce_fit_tiles.add_tile(("Quality", "—"))
            self._tile_flags: MetricTile = self._cce_fit_tiles.add_tile(("Flags", "—"))
            self._tile_ref_sigma: MetricTile = self._cce_fit_tiles.add_tile(("Ref σ", "—"))
            lay.addWidget(self._cce_fit_tiles)
            self._reset_cce_fit_tiles("no run loaded")
        return page

    def _build_survey_mode(self) -> QWidget:
        """Mosaic Survey view (E6b part 2): stitch the run's ``camera/``
        frames (via ``analysis.mosaic_stitch.place_tiles``) into one
        real-mm-axed image. Building is an explicit user action ("Build
        mosaic"), not automatic on load — this task's brief allows a
        synchronous compute with a busy cursor (no new threading primitive;
        a WorkerThread rework is a parallel beat) since ``place_tiles`` can
        be non-trivial work for a real mosaic."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACE_SM)

        ctrl = QHBoxLayout()
        self._chk_survey_refine = QCheckBox("Refine seams")
        self._chk_survey_refine.setToolTip(
            "analysis.mosaic_stitch.place_tiles(refine=True) — pairwise "
            "FFT seam correction. Off (default) matches place_tiles's own "
            "default: nominal calibrated placement only."
        )
        ctrl.addWidget(self._chk_survey_refine)
        self._btn_build_survey = QPushButton("Build mosaic")
        self._btn_build_survey.setProperty("state", "secondary")
        set_button_icon(self._btn_build_survey, "mdi.grid")
        self._btn_build_survey.clicked.connect(self._build_survey_mosaic)
        ctrl.addWidget(self._btn_build_survey)
        ctrl.addStretch(1)
        self._chip_survey_cal = StatusChip("No run loaded", "neutral")
        ctrl.addWidget(self._chip_survey_cal)
        lay.addLayout(ctrl)

        # Calibration/affine notice (§ requirement: "if affine is None or
        # absent, say so in the UI") — always visible text, never
        # tooltip-only, same "caption over tooltip" idiom as
        # _update_ref_sigma_tile's q_term_included caveat.
        self._lbl_survey_calib = QLabel("")
        self._lbl_survey_calib.setObjectName("cardSubtitle")
        self._lbl_survey_calib.setWordWrap(True)
        lay.addWidget(self._lbl_survey_calib)

        # ── Sensor-pose alignment (E7c) — numbers only, never motion ──
        # "Detect sensor pose" runs vision.sensor_align on this run's own
        # first/last camera frame (see _on_detect_sensor_pose's reference-
        # frame-choice docstring); "Align scan grid" only DISPLAYS/copies
        # the suggested correction and emits grid_alignment_suggested — it
        # never calls a controller or touches a scan plan/motion (see its
        # own docstring). Both buttons are plain QWidgets, built regardless
        # of pyqtgraph availability (matching _chk_survey_refine/
        # _btn_build_survey above); only the mosaic OVERLAY drawing needs
        # pyqtgraph (see _render_pose_overlay).
        pose_row = QHBoxLayout()
        self._btn_detect_pose = QPushButton("Detect sensor pose")
        self._btn_detect_pose.setProperty("state", "secondary")
        set_button_icon(self._btn_detect_pose, "mdi.crosshairs-gps")
        self._btn_detect_pose.setEnabled(False)
        self._btn_detect_pose.clicked.connect(self._on_detect_sensor_pose)
        pose_row.addWidget(self._btn_detect_pose)
        self._btn_align_grid = QPushButton("Align scan grid")
        self._btn_align_grid.setProperty("state", "secondary")
        set_button_icon(self._btn_align_grid, "mdi.compass-outline")
        self._btn_align_grid.setEnabled(False)
        self._btn_align_grid.clicked.connect(self._on_align_scan_grid)
        pose_row.addWidget(self._btn_align_grid)
        pose_row.addStretch(1)
        self._chip_pose_precision = StatusChip("No pose", "neutral")
        pose_row.addWidget(self._chip_pose_precision)
        lay.addLayout(pose_row)

        # Copyable suggested-correction numbers (also copied to the
        # clipboard on click — see _on_align_scan_grid); selectable text,
        # never tooltip-only, matching _lbl_survey_calib's own "caption
        # over tooltip" idiom above.
        self._lbl_align_grid_result = QLabel("")
        self._lbl_align_grid_result.setObjectName("cardSubtitle")
        self._lbl_align_grid_result.setWordWrap(True)
        self._lbl_align_grid_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_align_grid_result.setVisible(False)
        lay.addWidget(self._lbl_align_grid_result)

        self._survey_stack = QStackedWidget()
        if _HAS_PG:
            self._survey_figure = FigureCard("Survey mosaic", "no data")
            self._survey_plot = self._survey_figure.plot
            self._survey_plot.setLabel("bottom", "X", units="mm")
            self._survey_plot.setLabel("left", "Y", units="mm")
            self._survey_plot.setAspectLocked(True)
            self._survey_image_item = pg.ImageItem()
            self._survey_plot.addItem(self._survey_image_item)
            self._survey_empty = EmptyState(
                "fa5s.th-large", "No mosaic built",
                "Load a run with camera frames, then click "
                "“Build mosaic”.",
                theme_mode=self._survey_theme_mode,
            )
            self._survey_stack.addWidget(self._survey_empty)    # index 0
            self._survey_stack.addWidget(self._survey_figure)   # index 1
        else:  # pragma: no cover - exercised only without pyqtgraph installed
            self._survey_figure = None
            self._survey_plot = None
            self._survey_image_item = None
            self._survey_empty = None
            self._survey_stack.addWidget(QLabel(
                "pyqtgraph not installed — cannot display the mosaic.\n"
                "Run:  pip install pyqtgraph"
            ))
        lay.addWidget(self._survey_stack, 1)

        # E4 diagnostics readout row — n_clamped/mean_abs_offset_px from
        # place_tiles(return_diagnostics=True), plus this view's own
        # placement honesty counters (tiles placed / omitted at write time /
        # omitted for lack of a usable position).
        self._survey_tiles_grid = MetricGrid(columns=5, compact=True)
        self._tile_survey_placed: MetricTile = self._survey_tiles_grid.add_tile(
            ("Tiles placed", "—"))
        self._tile_survey_omitted_write: MetricTile = self._survey_tiles_grid.add_tile(
            ("Omitted (write)", "—"))
        self._tile_survey_omitted_pos: MetricTile = self._survey_tiles_grid.add_tile(
            ("Omitted (no pos)", "—"))
        self._tile_survey_clamped: MetricTile = self._survey_tiles_grid.add_tile(
            ("Seam clamps", "—"))
        self._tile_survey_offset: MetricTile = self._survey_tiles_grid.add_tile(
            ("Mean |offset|", "—"))
        # E7c pose numbers (objective 4) — extends the SAME diagnostics
        # grid rather than a parallel one (5 columns -> these 4 tiles wrap
        # onto a second row). Populated by _update_pose_tiles after a
        # successful "Detect sensor pose"; see _reset_pose_state for the
        # stale/no-pose default.
        self._tile_pose_theta: MetricTile = self._survey_tiles_grid.add_tile(
            ("Pose θ", "—"))
        self._tile_pose_translation: MetricTile = self._survey_tiles_grid.add_tile(
            ("Pose Δ", "—"))
        self._tile_pose_baseline: MetricTile = self._survey_tiles_grid.add_tile(
            ("Pose baseline", "—"))
        self._tile_pose_precision: MetricTile = self._survey_tiles_grid.add_tile(
            ("Pose precision", "—"))
        lay.addWidget(self._survey_tiles_grid)
        self._reset_survey_tiles("no run loaded")
        self._reset_pose_state()
        self._update_pose_availability()
        return page

    # ------------------------------------------------------------------ #
    # Recent runs (empty state)                                           #
    # ------------------------------------------------------------------ #

    def _refresh_recent_runs(self) -> None:
        """Re-scan *runs_dir* for the newest ``*.h5`` files (top level and
        one level of run folders — the ``runs/run_XXXXX/waveforms.h5``
        layout). Read-only; failures degrade to an honest hint line."""
        self._list_recent.clear()
        files: list[Path] = []
        try:
            if self._runs_dir.is_dir():
                for pattern in ("*.h5", "*.hdf5", "*/*.h5", "*/*.hdf5"):
                    files.extend(self._runs_dir.glob(pattern))
        except OSError:
            files = []

        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0

        files = sorted(set(files), key=_mtime, reverse=True)[:_RECENT_RUNS_MAX]
        for f in files:
            try:
                rel = f.relative_to(self._runs_dir)
            except ValueError:
                rel = f
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(_mtime(f)))
            item = QListWidgetItem(f"{rel}    ·    {stamp}")
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            item.setToolTip(str(f))
            self._list_recent.addItem(item)
        if files:
            self._lbl_recent_hint.setText(
                "Click a run to load it, or browse for any HDF5 file.")
        else:
            self._lbl_recent_hint.setText(
                f"No run files found in {self._runs_dir} — browse for one, "
                "or finish a scan first.")

    def _on_recent_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.load_run(str(path))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # Keep the empty-state list current whenever the panel resurfaces —
        # a cheap directory scan, never a file open.
        self._refresh_recent_runs()

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
            self, "Open run HDF5", str(self._runs_dir), "HDF5 (*.h5 *.hdf5)"
        )
        if not path:
            return
        if self.load_run(path):
            flash_button(self._btn_open, "good", "Loaded")
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Load error", self._chip_file.toolTip())

    def load_run(self, path: str | Path) -> bool:
        """Public load entry point for programmatic hand-off (e.g. the Scan
        Viewer's "Open in Analysis" button, passing
        ``ScanController.last_run_path`` once a scan finishes).

        Loads *path* through the same parser (``_load_h5``) and updates the
        same UI state (file header/chips/map/CCE) as the file-dialog flow
        (``_open_file``) — there is exactly one load path underneath both.

        Never raises: any failure (missing path, missing h5py, unreadable/
        malformed HDF5) is caught, surfaced via the existing file chip +
        tooltip, and reported by returning ``False``. Returns ``True`` on a
        successful load.
        """
        path = str(path)
        if not _HAS_H5:
            self._chip_file.set_status(
                "Load error", "crit", "h5py is not installed"
            )
            return False
        if not Path(path).exists():
            self._chip_file.set_status(
                "Load error", "crit", f"File not found: {path}"
            )
            return False
        try:
            self._load_h5(path)
            self._run_path = path
            self._lbl_file.setText(Path(path).name)
            tooltip = path
            # Outcome is surfaced in the tooltip (readable, not yet a
            # dedicated status treatment — see _run_outcome docstring); a
            # clean 'finished' run or an old file with no outcome attr at
            # all keeps the plain path tooltip, matching prior behaviour.
            if self._run_outcome and self._run_outcome != "finished":
                tooltip += f"\noutcome: {self._run_outcome}"
                if self._run_abort_reason:
                    tooltip += f"\nreason: {self._run_abort_reason}"
            self._lbl_file.setToolTip(tooltip)
            self._chip_file.set_status("File loaded", "good")
            n_arrays = len(self._data) + len(self._voltage_scan)
            self._chip_dataset.set_status(
                f"{n_arrays} arrays", "good" if n_arrays else "warn"
            )
            self._replot_map()
            # A new run's CCE tiles/label/line may not still apply to the
            # PREVIOUS run's fit — same "reset on load" reasoning as
            # _replot_map's own _reset_slice_state() call; recomputed fresh
            # the next time "Plot CCE vs bias" runs.
            self._reset_cce_fit_tiles("not yet plotted")
            # A new run's mosaic (if any was built) belongs to the PREVIOUS
            # file — same "reset on load" reasoning as _reset_cce_fit_tiles
            # above; the fresh run's own camera/geometry state was already
            # loaded into self._camera/_survey_geom by _load_h5 just above.
            self._reset_survey_state()
            self._stack.setCurrentIndex(1)
            return True
        except Exception as exc:
            self._chip_file.set_status("Load error", "crit", str(exc))
            return False

    def _load_h5(self, path: str) -> None:
        self._data = {}
        self._voltage_scan = {}
        self._camera = {}
        self._survey_geom = None
        with h5py.File(path, "r") as f:
            # Root attrs (SCAN_DATA_FORMAT.md): 'outcome' in
            # {finished, aborted, error, unknown} + free-text 'abort_reason'.
            # Absent on files written before this existed -> None/"", read
            # honestly as "we don't know" rather than assumed clean.
            self._run_outcome = f.attrs.get("outcome")
            self._run_abort_reason = f.attrs.get("abort_reason", "")
            if "points" in f:
                pts = f["points"]
                for key in pts:
                    self._data[key] = pts[key][:]
            if "analysis" in f:
                ana = f["analysis"]
                for key in ana:
                    self._data[key] = ana[key][:]
            # Real voltage (IV) scan group (data/hdf5_writer.py
            # ``save_voltage_point`` / SCAN_DATA_FORMAT.md: 'voltage_scan/
            # {voltage_V, charge_pC, current_A}'). Kept in its own dict
            # rather than merged into self._data: an XY-scan file's
            # 'analysis/dut_charge_pC' (N points) and a voltage-scan file's
            # 'voltage_scan/charge_pC' (K bias steps) can both be present
            # and are different-length arrays — merging them would corrupt
            # the 2D-map replot's length-mismatch guard.
            if "voltage_scan" in f:
                vs = f["voltage_scan"]
                for key in vs:
                    self._voltage_scan[key] = vs[key][:]
            self._load_camera_group(f)
            self._load_survey_geometry(f)

    def _load_camera_group(self, f: "h5py.File") -> None:
        """Survey mode's data source (E6b part 2): the ``camera`` group
        SCAN_DATA_FORMAT.md documents — ``frames``/``frame_pos_mm``
        (position source ladder rung 1) plus the calibration attrs
        ``set_camera_calibration`` writes. Absent group -> ``self._camera``
        stays ``{}`` (an honest "no camera data" for ``_collect_survey_tiles``
        to report), never a crash."""
        if "camera" not in f:
            return
        cam = f["camera"]
        if "frames" in cam:
            self._camera["frames"] = cam["frames"][:]
            self._camera["frame_shape"] = tuple(cam["frames"].shape[1:])
        # Present whenever the camera group has >= 1 written frame
        # (SCAN_DATA_FORMAT.md) — absent on an older file written before
        # E6b part 1 (guard exactly as that doc instructs).
        if "frame_pos_mm" in cam:
            self._camera["frame_pos_mm"] = cam["frame_pos_mm"][:]
        self._camera["n_frames_omitted"] = int(cam.attrs.get("n_frames_omitted", 0))
        px_per_mm = cam.attrs.get("px_per_mm")
        self._camera["px_per_mm"] = float(px_per_mm) if px_per_mm is not None else None
        self._camera["affine_fit"] = _affine_from_stored(cam.attrs.get("affine"))

    def _load_survey_geometry(self, f: "h5py.File") -> None:
        """Position source ladder rung 2 (older files, or a photo-only
        survey with no ``camera/frame_pos_mm`` at all): reconstruct tile
        geometry from ``run_info/scan_config``'s ``safety['survey']`` block
        (``controller/survey_plan.py``'s documented "KNOWN GAP" recovery
        path — SCAN_DATA_FORMAT.md's CAPTURE_PHOTO section). Absent/
        malformed JSON, a missing ``run_info`` group (``run_metadata``
        saving off), or a missing ``safety``/``survey`` key all leave
        ``self._survey_geom`` honestly ``None`` — never raises."""
        if "run_info" not in f:
            return
        raw = f["run_info"].attrs.get("scan_config")
        if not raw:
            return
        try:
            scan_cfg = json.loads(raw)
            survey = (scan_cfg.get("safety") or {}).get("survey")
        except (ValueError, TypeError, AttributeError):
            return
        if isinstance(survey, dict) and "origin_mm" in survey and "area_mm" in survey:
            self._survey_geom = survey

    # ------------------------------------------------------------------ #
    # 2D map                                                               #
    # ------------------------------------------------------------------ #

    def _replot_map(self) -> None:
        """Seed the shared map view from the loaded arrays. All rendering
        truth (viridis, NaN transparency, colorbar unit, missing/duplicate
        counts) lives in :class:`~gui.scan_map_view.ScanMapView`.

        ``_map_view`` is SHARED across loads — every early-return path below
        (no map data at all, missing x_mm/y_mm, a truncated-file length
        mismatch) MUST clear it via ``set_points({})`` before returning.
        Without this the PREVIOUS run's grid/points stayed accumulated in
        the widget after loading a map-less run, so re-enabling "Slice"
        would slice (and export) the OLD run's values under the NEW run's
        filename — self._run_path already names the new run while the
        slicer was still reading the old one (Mary review, REQUEST-CHANGES
        on 9b91ed1, reproduced end-to-end). ``set_points({})`` drives
        ``_redraw`` -> ``_grid_result = None`` + the empty-state page, so
        ``grid_result()`` honestly reports "nothing to slice" and this also
        fixes the pre-existing stale-map display bug on its own."""
        # A new run may have a completely different extent than whatever the
        # slicer's cut line/position/band referenced before — start clean
        # rather than risk an out-of-range or now-meaningless cut (design
        # brief: "slice state resets when a different run ... loads").
        self._reset_slice_state()
        if not _HAS_PG or not self._data:
            self._map_view.set_points({})
            return
        x = self._data.get("x_mm")
        y = self._data.get("y_mm")
        if x is None or y is None:
            self._map_view.set_points({})
            self._lbl_map_info.setText("Missing x_mm / y_mm arrays in file")
            self._chip_map.set_status("Map invalid", "crit")
            return

        # Guard against a truncated/partially-written HDF5 where x_mm, y_mm
        # and the quantity columns ended up different lengths — zip() would
        # silently truncate, so check explicitly (Mary review finding kept
        # from the pre-migration _replot_map).
        n = len(x)
        bad = [k for k in ("y_mm", *QUANTITIES)
               if k in self._data and len(self._data[k]) != n]
        if bad:
            self._map_view.set_points({})
            self._lbl_map_info.setText(
                f"Map invalid: array length mismatch vs x_mm ({', '.join(bad)})")
            self._chip_map.set_status("Map invalid", "crit")
            return

        mapping: dict[tuple[float, float], dict[str, float]] = {}
        for i in range(n):
            entry = {q: float(self._data[q][i])
                     for q in QUANTITIES if q in self._data}
            mapping[(float(x[i]), float(y[i]))] = entry
        self._map_view.set_points(mapping)
        self._update_map_info()

    def _update_map_info(self) -> None:
        """Summary line + chips for the currently selected quantity."""
        if not self._data:
            return
        qty = self._map_view.current_quantity()
        if qty not in self._data:
            self._lbl_map_info.setText(f"'{qty}' not stored in this file")
            self._chip_map.set_status("Map missing", "warn")
            return
        result = self._map_view.grid_result()
        if result is None:
            return
        z = self._data[qty]
        xs, ys = result.x_mm, result.y_mm
        self._lbl_map_info.setText(
            f"{qty}  |  {len(xs)} × {len(ys)} points  "
            f"|  min={np.nanmin(z):.4g}  max={np.nanmax(z):.4g}  "
            f"|  X [{xs[0]:.3f}, {xs[-1]:.3f}] mm  Y [{ys[0]:.3f}, {ys[-1]:.3f}] mm"
            f"  |  {result.n_missing} missing"
        )
        self._chip_map.set_status(f"Map {len(xs)}x{len(ys)}", "good")
        self._chip_export.set_status("Export ready", "good")
        # Slicer recompute on a quantity switch is wired directly to the
        # combo (see _build_map_mode) rather than nested here — this method
        # early-returns before this point whenever the quantity isn't
        # stored in the file, and the profile must recompute (to an honest
        # "0/N valid") in that case too.

    # ------------------------------------------------------------------ #
    # 1D map slicer                                                        #
    # ------------------------------------------------------------------ #

    def _reset_slice_state(self) -> None:
        """New run loaded — turn the slicer off and reset its controls to
        defaults rather than carry over a cut line/band that may no longer
        make sense against the new map's extent."""
        if not _HAS_PG or not hasattr(self, "_btn_slice"):
            return
        if self._btn_slice.isChecked():
            self._btn_slice.setChecked(False)   # fires _on_slice_toggled(False)
        self._slice_seg.set_current("x")
        self._spin_slice_width.setValue(0)

    def _slice_axis_pitch(self, axis_key: str, result) -> float:
        """Grid pitch (mm/step) along the FIXED axis for *axis_key* — "x"
        profiles walk X with Y fixed, so its pitch is dy (and vice versa)."""
        _, (dx, dy) = grid_extent(result)
        return dy if axis_key == "x" else dx

    def _on_slice_toggled(self, checked: bool) -> None:
        self._slice_active = bool(checked)
        for w in self._slice_control_widgets:
            w.setVisible(self._slice_active)
        if not _HAS_PG:
            return
        self._slice_line.setVisible(self._slice_active)
        axis_key = self._slice_seg.current_key() or "x"
        active_band = self._slice_band_h if axis_key == "x" else self._slice_band_v
        inactive_band = self._slice_band_v if axis_key == "x" else self._slice_band_h
        inactive_band.setVisible(False)
        active_band.setVisible(self._slice_active)
        self._slice_figure.setVisible(self._slice_active)
        if self._slice_active:
            self._init_slice_position()
            self._update_slice_profile()

    def _init_slice_position(self) -> None:
        """(Re)centre the position spin/cut line on the current grid extent
        for the selected orientation — called on slice-on and on an
        orientation (X/Y) switch, since the FIXED axis (and therefore what
        "position" even means) changes with it."""
        if not _HAS_PG:
            return
        axis_key = self._slice_seg.current_key() or "x"
        self._slice_line.setAngle(0 if axis_key == "x" else 90)
        result = self._map_view.grid_result()
        if result is None:
            return
        fixed = result.y_mm if axis_key == "x" else result.x_mm
        if len(fixed) == 0:
            return
        pitch = self._slice_axis_pitch(axis_key, result)
        step = abs(pitch) if pitch else 1.0
        lo, hi = float(fixed[0]), float(fixed[-1])
        if lo > hi:
            lo, hi = hi, lo
        mid = float(fixed[len(fixed) // 2])
        self._slice_syncing = True
        try:
            self._spin_slice_pos.setRange(lo - step, hi + step)
            self._spin_slice_pos.setSingleStep(max(step, 1e-6))
            self._spin_slice_pos.setValue(mid)
            self._slice_line.setValue(mid)
        finally:
            self._slice_syncing = False

    def _on_slice_axis_changed(self, key: str) -> None:
        if not (_HAS_PG and self._slice_active):
            return
        active_band = self._slice_band_h if key == "x" else self._slice_band_v
        inactive_band = self._slice_band_v if key == "x" else self._slice_band_h
        inactive_band.setVisible(False)
        active_band.setVisible(True)
        self._init_slice_position()
        self._update_slice_profile()

    def _on_slice_pos_spin_changed(self, _value: float) -> None:
        if self._slice_syncing or not self._slice_active:
            return
        self._slice_syncing = True
        try:
            self._update_slice_profile()
        finally:
            self._slice_syncing = False

    def _on_slice_width_changed(self, _value: int) -> None:
        if not self._slice_active:
            return
        self._update_slice_profile()

    def _on_slice_line_moved(self) -> None:
        """The draggable cut line moved — mirror it into the position spin
        (guarded against the spin's own valueChanged bouncing straight back,
        design brief: "guard against feedback loops when syncing spin<->line")
        and recompute the profile directly (grids here are small)."""
        if self._slice_syncing or not self._slice_active:
            return
        self._slice_syncing = True
        try:
            self._spin_slice_pos.setValue(float(self._slice_line.value()))
            self._update_slice_profile()
        finally:
            self._slice_syncing = False

    def _update_slice_profile(self) -> None:
        """Recompute (positions, values) via ``analysis.map_slice`` and push
        them into the profile curve + cut-line/band overlay. The only place
        that calls :func:`analysis.map_slice.slice_grid_at_mm` — GUI code
        never re-derives the slice math inline."""
        if not (_HAS_PG and self._slice_active):
            return
        result = self._map_view.grid_result()
        axis_key = self._slice_seg.current_key() or "x"
        if result is None:
            self._slice_curve.setData([], [])
            self._slice_figure.set_subtitle("no map data")
            return
        qty = self._map_view.current_quantity()
        position_mm = float(self._spin_slice_pos.value())
        width = int(self._spin_slice_width.value())
        positions, values = slice_grid_at_mm(
            result.grid, result.x_mm, result.y_mm, axis_key, position_mm, width)
        native_unit = QUANTITY_UNITS.get(qty, "")
        disp_unit, scale = display_unit_scale(qty, native_unit)
        base_label = strip_unit_suffix(qty, native_unit)
        self._slice_curve.setData(positions, values * scale)
        free_label = "X" if axis_key == "x" else "Y"
        self._slice_figure.plot.setLabel("bottom", free_label, units="mm")
        # base_label (native-unit suffix stripped) + units=disp_unit — never
        # qty itself, or pyqtgraph's "(units)" suffix doubles up against a
        # unit qty's own name already spells out (e.g. "dut_charge_pC (fC)").
        self._slice_figure.plot.setLabel("left", base_label, units=disp_unit)
        n_valid = int(np.count_nonzero(~np.isnan(values)))
        self._slice_figure.set_subtitle(
            f"{axis_key.upper()} @ {position_mm:.4f} mm  |  ±{width}  |  "
            f"{n_valid}/{len(values)} valid")
        self._update_slice_overlay(result, axis_key, position_mm, width)

    def _update_slice_overlay(
        self, result, axis_key: str, position_mm: float, width: int,
    ) -> None:
        """Move the cut line + resize the averaging-band region to match the
        just-computed slice (band bounds extend half a pixel pitch past the
        outermost included row/col, so the band visually covers the same
        pixel extent ``ScanMapView``'s own image rendering does)."""
        fixed = result.y_mm if axis_key == "x" else result.x_mm
        if len(fixed) == 0:
            return
        idx = mm_to_index(fixed, position_mm)
        n = len(fixed)
        lo_idx = max(0, idx - width)
        hi_idx = min(n - 1, idx + width)
        pitch = self._slice_axis_pitch(axis_key, result)
        half = abs(pitch) / 2.0 if pitch else 0.0
        lo_mm = float(fixed[lo_idx]) - half
        hi_mm = float(fixed[hi_idx]) + half

        self._slice_line.setAngle(0 if axis_key == "x" else 90)
        if float(self._slice_line.value()) != position_mm:
            self._slice_line.setValue(position_mm)

        active_band = self._slice_band_h if axis_key == "x" else self._slice_band_v
        active_band.setRegion((lo_mm, hi_mm))

    def _default_slice_csv_name(self) -> str:
        axis_key = self._slice_seg.current_key() or "x"
        pos = float(self._spin_slice_pos.value())
        if self._run_path:
            p = Path(self._run_path)
            # Every run writes 'waveforms.h5' (SCAN_DATA_FORMAT.md) — the
            # meaningful name is the run FOLDER, not the fixed filename.
            run_name = p.parent.name if p.stem.lower() == "waveforms" else p.stem
        else:
            run_name = "run"
        return f"{run_name}_slice_{axis_key}_{pos:.4f}mm.csv"

    def _export_slice_csv(self) -> None:
        if not (_HAS_PG and self._slice_active):
            return
        result = self._map_view.grid_result()
        if result is None:
            return
        qty = self._map_view.current_quantity()
        axis_key = self._slice_seg.current_key() or "x"
        position_mm = float(self._spin_slice_pos.value())
        width = int(self._spin_slice_width.value())
        positions, values = slice_grid_at_mm(
            result.grid, result.x_mm, result.y_mm, axis_key, position_mm, width)
        native_unit = QUANTITY_UNITS.get(qty, "")
        disp_unit, scale = display_unit_scale(qty, native_unit)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export slice", self._default_slice_csv_name(), "CSV (*.csv)")
        if not path:
            return
        pos_col = "x_mm" if axis_key == "x" else "y_mm"
        base_label = strip_unit_suffix(qty, native_unit)
        value_col = f"{base_label}_{disp_unit}" if disp_unit else base_label
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([pos_col, value_col])
            for p_, v_ in zip(positions, values * scale):
                w.writerow([f"{p_:.6f}", f"{v_:.8g}"])
        flash_button(self._btn_slice_export, "good", "Exported")

    # ------------------------------------------------------------------ #
    # CCE vs. bias                                                         #
    # ------------------------------------------------------------------ #

    def _cce_source_arrays(self):
        """Bias voltage / collected charge / leakage current arrays for the
        CCE plot and its CSV export.

        Prefers the real ``voltage_scan/{voltage_V,charge_pC,current_A}``
        group (data/hdf5_writer.py ``save_voltage_point``,
        SCAN_DATA_FORMAT.md) — the group every current voltage-scan run
        actually writes — and falls back to the legacy flat ``bias_V`` /
        ``dut_charge_pC`` / ``leakage_A`` keys for any older/hand-built file
        that used that naming directly under ``points``/``analysis``.
        """
        voltages = self._voltage_scan.get("voltage_V")
        if voltages is None:
            voltages = self._data.get("bias_V")
        charges = self._voltage_scan.get("charge_pC")
        if charges is None:
            charges = self._data.get("dut_charge_pC")
        currents = self._voltage_scan.get("current_A")
        if currents is None:
            currents = self._data.get("leakage_A")
        return voltages, charges, currents

    def _reset_cce_fit_tiles(self, reason: str) -> None:
        """Put the 4 fit-quality tiles — and the pre-existing V_dep label/
        line, which show the exact same computed quantity — into an honest
        "nothing current to say" state. Called on every new run load (see
        ``load_run``, mirroring ``_reset_slice_state``'s "a previous run's
        state may not still apply" reasoning) and whenever ``_plot_cce``
        cannot produce a usable fit, so a stale run's numbers are never left
        on screen (law 4 / the stale-run provenance fix, 7892a26). A no-op
        before the tiles exist (no pyqtgraph) or are built."""
        if not (_HAS_PG and hasattr(self, "_tile_vdep")):
            return
        for tile in (self._tile_vdep, self._tile_quality, self._tile_flags,
                     self._tile_ref_sigma):
            tile.set_value("—")
            tile.set_state("normal")
            tile.set_stale(True, reason)
            tile.setToolTip("")
        self._vdep_line.setVisible(False)
        self._lbl_vdep.setText("V_dep estimate: —")
        self._cce_errorbar.setVisible(False)
        self._cce_bracket_region.setVisible(False)

    def _plot_cce(self) -> None:
        if not _HAS_PG or (not self._data and not self._voltage_scan):
            return

        voltages, charges, currents = self._cce_source_arrays()

        if voltages is None or charges is None:
            from PySide6.QtWidgets import QMessageBox
            self._chip_dataset.set_status("No bias data", "warn")
            self._reset_cce_fit_tiles("no bias data")
            QMessageBox.warning(
                self, "No bias data",
                "No 'voltage_scan/voltage_V' + 'voltage_scan/charge_pC' "
                "(or legacy 'bias_V'/'dut_charge_pC') arrays found.\n"
                "Load a file from a voltage scan."
            )
            return

        # CCE(i) = |Q(i)| / |Q_ref| — see analysis.cce for the sign/guard
        # rationale (TCT pulses are usually negative → raw charge_pC is
        # signed; CCE compares magnitudes).
        q_ref = self._spin_ref_charge.value()
        cce = cce_vs_reference(charges, q_ref)

        self._cce_curve_cce.setData(voltages, cce)
        # Convention + Q_ref provenance next to the data (§4).
        self._cce_figure.set_subtitle(f"CCE = |Q| / |Q_ref| · Q_ref = {q_ref:.3g} pC")

        if currents is not None:
            # Scale leakage to CCE axis for overlay
            i_ua = np.array(currents) * 1e6
            i_scaled = i_ua / max(np.max(np.abs(i_ua)), 1e-12)
            self._cce_curve_iv.setData(voltages, i_scaled)

        # Depletion-voltage fit + CCE uncertainty -> the V_dep/Quality/
        # Flags/Ref σ tiles (D3) and the pre-existing V_dep label/line
        # (unchanged behaviour: a line only ever appears when v_dep is not
        # None). Both analysis.efield_analysis functions are documented to
        # never raise on bad/degenerate input (they feed a GUI tile) — the
        # try/except below is a defensive backstop for a genuinely
        # unexpected failure, not the normal path for "sweep too short to
        # fit"; that normal, structured case is read honestly off
        # DepletionFitResult.v_dep == None inside _update_cce_fit_tiles,
        # with its own narrower warning log. This replaces a bare
        # "except Exception: pass" that used to swallow real failures
        # silently and leave whatever the tiles/line last showed on screen.
        try:
            v_arr = np.asarray(voltages, dtype=float)
            q_arr = np.asarray(charges, dtype=float)
            fit = fit_depletion_voltage(v_arr, q_arr)
            cce_result = compute_cce_with_uncertainty(q_arr, q_ref)
            self._update_cce_fit_tiles(fit, cce_result, v_arr)
        except Exception as exc:
            logger.warning(
                "CCE fit-quality tiles failed for run %r: %s",
                self._run_path, exc)
            self._reset_cce_fit_tiles("fit unavailable")

    def _update_cce_fit_tiles(self, fit, cce_result, v_arr: np.ndarray) -> None:
        """Populate the V_dep / Quality / Flags / Ref σ tiles (+ the
        pre-existing V_dep label/line) from one ``DepletionFitResult`` and
        one ``CCEResult`` — the only place either dataclass's fields become
        pixels. V_dep/Quality/Flags are treated as one unit (all derived
        from the SAME ``fit``): a degenerate fit (``fit.v_dep is None`` —
        an under-sampled or all-NaN sweep) takes the whole tile row back to
        the honest "nothing to say" state via ``_reset_cce_fit_tiles``
        rather than showing a fake-precise quality=0.00/AMBIGUOUS badge
        computed from zero real points."""
        if fit.v_dep is None:
            logger.warning(
                "Depletion-voltage fit unavailable for run %r: %s",
                self._run_path, fit.notes or "no usable data")
            self._reset_cce_fit_tiles(fit.notes or "fit unavailable")
            return

        # fit_depletion_voltage() only ever returns a positive |V|
        # magnitude — re-apply the bias sign convention read from the DATA
        # itself (never guessed) so the marker/tile land on the same side /
        # within the range of the plotted points.
        finite_v = v_arr[np.isfinite(v_arr)]
        negative_bias = finite_v.size > 0 and float(np.nanmedian(finite_v)) < 0
        v_dep_signed = -fit.v_dep if negative_bias else fit.v_dep

        self._lbl_vdep.setText(
            f"V_dep estimate: {v_dep_signed:+.1f} V (|V| convention)")
        self._vdep_line.setValue(float(v_dep_signed))
        self._vdep_line.setVisible(True)
        self._chip_dataset.set_status(f"Vdep {v_dep_signed:+.1f} V", "info")

        self._tile_vdep.set_value(f"{v_dep_signed:+.1f} ± {fit.v_dep_sigma:.1f} V")
        self._tile_vdep.set_state("normal")
        self._tile_vdep.set_stale(False, "")
        self._tile_vdep.setToolTip(
            f"method={fit.method}, threshold_frac={fit.threshold_frac:.3g}, "
            f"n_points={fit.n_points}, bracket="
            + (f"[{fit.bracket[0]:.3g}, {fit.bracket[1]:.3g}] V" if fit.bracket
               else "None (crossing at the lowest sampled |V|)"))

        # Quality banding — see the _QUALITY_OK_MIN/_QUALITY_WARN_MIN
        # module comment for the thresholds and their rationale.
        if fit.quality >= _QUALITY_OK_MIN:
            q_state = "normal"   # "ok" — quiet nominal (design law 1)
        elif fit.quality >= _QUALITY_WARN_MIN:
            q_state = "warn"
        else:
            q_state = "crit"
        self._tile_quality.set_value(f"{fit.quality:.2f}")
        self._tile_quality.set_state(q_state)
        self._tile_quality.set_stale(False, "")
        self._tile_quality.setToolTip(
            fit.notes or "bracket density + plateau flatness + monotonicity "
                         "(see DepletionFitResult docstring)")

        flags_text, flags_state = _flags_tile_content(fit)
        self._tile_flags.set_value(flags_text)
        self._tile_flags.set_state(flags_state)
        self._tile_flags.set_stale(False, "")
        self._tile_flags.setToolTip(fit.notes or "no ambiguity flags")

        self._update_ref_sigma_tile(cce_result)

        # cce ± sigma overlay — only when there is real (nonzero, finite)
        # sigma content: with today's single-Q_ref data model (the manual
        # spin box, no repeated reference-channel readings) sigma is
        # normally all-zero — see CCEResult's own honesty notes.
        finite = (np.isfinite(cce_result.sigma) & np.isfinite(cce_result.cce)
                  & np.isfinite(v_arr))
        if finite.any() and np.any(cce_result.sigma[finite] != 0):
            self._cce_errorbar.setData(
                x=v_arr[finite], y=cce_result.cce[finite],
                height=2.0 * cce_result.sigma[finite],
            )
            self._cce_errorbar.setVisible(True)
        else:
            self._cce_errorbar.setVisible(False)

        # Depletion-fit bracket — the two |V| points straddling the
        # threshold crossing — converted to the SAME signed convention as
        # the plotted x-axis (fit.bracket itself is always a |V| pair).
        if fit.bracket is not None:
            lo, hi = fit.bracket
            region = (-hi, -lo) if negative_bias else (lo, hi)
            self._cce_bracket_region.setRegion(region)
            self._cce_bracket_region.setVisible(True)
        else:
            self._cce_bracket_region.setVisible(False)

    def _update_ref_sigma_tile(self, cce_result) -> None:
        """Ref σ tile: the CCE-uncertainty reference term
        (``ref_std``/``ref_mean``, as a relative percentage) plus the
        ``q_term_included`` honesty caveat from ``CCEResult`` — kept
        VISIBLE as the tile's own caption (never tooltip-only) per the D3
        brief, since it explains what the ± sigma on the plot does and does
        not include."""
        ref_mean, ref_std = cce_result.ref_mean, cce_result.ref_std
        if not (np.isfinite(ref_mean) and ref_mean != 0 and np.isfinite(ref_std)):
            self._tile_ref_sigma.set_value("—")
            self._tile_ref_sigma.set_state("normal")
            self._tile_ref_sigma.set_stale(True, "reference undefined")
            self._tile_ref_sigma.setToolTip(cce_result.notes)
            return
        rel_pct = 100.0 * ref_std / ref_mean
        self._tile_ref_sigma.set_value(f"{rel_pct:.1f}%")
        self._tile_ref_sigma.set_state("normal")
        self._tile_ref_sigma.set_stale(False)
        # q_term_included is False whenever charge_sigma_pC was left at its
        # 0 default (today's only call site, _plot_cce) — the caveat this
        # tile exists to surface, visible as the caption, not buried in a
        # tooltip a reader has to think to hover for.
        caption = ("ref-scatter only, no charge-noise term"
                   if not cce_result.q_term_included else
                   "includes charge-noise term")
        self._tile_ref_sigma.set_caption(caption)
        self._tile_ref_sigma.setToolTip(
            f"ref_std={ref_std:.4g} pC, ref_mean={ref_mean:.4g} pC "
            f"(n_ref={cce_result.n_ref}) — {cce_result.notes}")

    def _export_cce_csv(self) -> None:
        if not self._data and not self._voltage_scan:
            return
        voltages, charges, _ = self._cce_source_arrays()
        if voltages is None or charges is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CCE", "", "CSV (*.csv)")
        if not path:
            return
        cce = cce_vs_reference(charges, self._spin_ref_charge.value())
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["bias_V", "dut_charge_pC", "CCE"])
            for v, q, c in zip(voltages, charges, cce):
                w.writerow([f"{v:.2f}", f"{q:.6f}", f"{c:.6f}"])
        flash_button(self._btn_export_cce, "good", "Exported")

    def _export_csv(self) -> None:
        """Export all loaded analysis arrays as CSV."""
        if not self._data:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export analysis", "", "CSV (*.csv)")
        if not path:
            return
        keys = list(self._data.keys())
        n = len(next(iter(self._data.values())))
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(keys)
            for i in range(n):
                w.writerow([self._data[k][i] for k in keys])
        flash_button(self._btn_export_csv, "good", "Exported")

    # ------------------------------------------------------------------ #
    # Survey (mosaic) mode — E6b part 2                                    #
    # ------------------------------------------------------------------ #

    def _reset_survey_state(self) -> None:
        """New run loaded — a previously built mosaic belongs to a
        different file's camera data; drop it back to the empty state
        rather than leave a stale image on screen (same "a previous run's
        state may not still apply" reasoning as ``_reset_slice_state``/
        ``_reset_cce_fit_tiles``). Does NOT auto-rebuild — building is an
        explicit action (see ``_build_survey_mode``).

        Pose reset/gating (E7c) runs UNCONDITIONALLY, ahead of the
        pyqtgraph-only guard below: ``_update_pose_availability`` must
        reflect the newly loaded run's own ``camera/frames`` every time,
        not just once at construction — otherwise loading a second run
        without pyqtgraph installed would leave "Detect sensor pose" gated
        on the PREVIOUS run's frames."""
        self._reset_pose_state()
        self._update_pose_availability()
        if not (_HAS_PG and hasattr(self, "_survey_stack")):
            return
        self._survey_empty.set_label("No mosaic built")
        self._survey_empty.set_hint(
            "Load a run with camera frames, then click “Build mosaic”.")
        self._survey_stack.setCurrentIndex(0)
        self._lbl_survey_calib.setText("")
        self._chip_survey_cal.set_status("No mosaic yet", "neutral")
        self._reset_survey_tiles("no mosaic built")

    def _reset_survey_tiles(self, reason: str) -> None:
        if not hasattr(self, "_tile_survey_placed"):
            return
        for tile in (
            self._tile_survey_placed, self._tile_survey_omitted_write,
            self._tile_survey_omitted_pos, self._tile_survey_clamped,
            self._tile_survey_offset,
        ):
            tile.set_value("—")
            tile.set_state("normal")
            tile.set_stale(True, reason)

    def _show_survey_empty(self, label: str, hint: str) -> None:
        """Route every "cannot build a mosaic" path (missing frames, no
        position source, no pixel scale, a placement failure) through the
        same honest EmptyState — no crash, no silent blank canvas."""
        if not (_HAS_PG and hasattr(self, "_survey_stack")):
            return
        self._survey_empty.set_label(label)
        self._survey_empty.set_hint(hint)
        self._survey_stack.setCurrentIndex(0)
        self._chip_survey_cal.set_status(label, "warn")
        self._reset_survey_tiles(label)

    @staticmethod
    def _as_grayscale(frame: np.ndarray) -> np.ndarray:
        """``place_tiles`` requires a 2-D tile image; a stored frame is
        grayscale ``(H, W)`` for every camera backend this app ships
        (``devices/camera_blackfly.py``), but a defensive ``(H, W, C)``
        color frame is averaged over channels rather than rejected."""
        arr = np.asarray(frame, dtype=np.float64)
        if arr.ndim == 3:
            arr = arr.mean(axis=-1)
        return arr

    def _survey_rect(self, geom: dict) -> tuple[float, float, float, float]:
        """``safety['survey']``'s own ``(origin_mm, area_mm)`` as the
        ``(x0, y0, x1, y1)`` rectangle :func:`~analysis.mosaic_stitch.
        canvas_geometry`/:func:`~analysis.mosaic_stitch.plan_grid` expect —
        see ``controller/survey_plan.py``'s schema docstring."""
        x0, y0 = geom["origin_mm"]
        w, h = geom["area_mm"]
        return (float(x0), float(y0), float(x0) + float(w), float(y0) + float(h))

    def _collect_survey_tiles(
        self,
    ) -> tuple[list[tuple[np.ndarray, tuple[float, float]]] | None, str]:
        """Position source ladder (E6b brief): prefer ``camera/
        frame_pos_mm`` (rung 1 — may contain NaN rows, each one an honest
        gap, counted in ``self._survey_n_pos_omitted`` and never placed);
        else reconstruct tile centres from ``safety['survey']`` geometry
        (rung 2, older/photo-only-survey files); else an EmptyState
        explaining there is no way to place these frames at all (rung 3).

        Returns ``(tiles, source)`` — ``tiles`` is ``None`` once an
        EmptyState has already been shown (nothing left to build); *source*
        is ``"frame_pos_mm"``/``"geometry"`` for the caller's calibration
        notice (unused on the ``None`` path).
        """
        frames = self._camera.get("frames")
        if frames is None or len(frames) == 0:
            self._show_survey_empty(
                "No camera frames in this run",
                "This run has no 'camera/frames' dataset (camera saving "
                "was off, or every grab failed) — nothing to stitch."
            )
            return None, ""

        n_frames = len(frames)
        pos_mm = self._camera.get("frame_pos_mm")
        n_pos_omitted = 0
        tiles: list[tuple[np.ndarray, tuple[float, float]]] = []

        if pos_mm is not None:
            self._survey_position_source = "frame_pos_mm"
            for k in range(n_frames):
                x, y = float(pos_mm[k][0]), float(pos_mm[k][1])
                if not (np.isfinite(x) and np.isfinite(y)):
                    n_pos_omitted += 1
                    continue
                tiles.append((self._as_grayscale(frames[k]), (x, y)))
        elif self._survey_geom is not None:
            self._survey_position_source = "geometry"
            try:
                centers, _rows_cols = plan_grid(
                    self._survey_rect(self._survey_geom),
                    tuple(self._survey_geom["fov_mm"]),
                    float(self._survey_geom["overlap_frac"]),
                )
            except (KeyError, ValueError, TypeError) as exc:
                self._show_survey_empty(
                    "Survey geometry unreadable",
                    f"'run_info/scan_config' safety['survey'] block is "
                    f"malformed: {exc}"
                )
                return None, ""
            for k in range(n_frames):
                if k >= len(centers):
                    n_pos_omitted += 1
                    continue
                tiles.append((self._as_grayscale(frames[k]), centers[k]))
        else:
            self._show_survey_empty(
                "No frame positions available",
                "This run has no 'camera/frame_pos_mm' dataset and no "
                "safety['survey'] geometry in run_info/scan_config — "
                "there is no way to place these frames in mm space."
            )
            return None, ""

        self._survey_n_pos_omitted = n_pos_omitted
        if not tiles:
            self._show_survey_empty(
                "Every frame is unplaceable",
                f"All {n_frames} written frame(s) have an unknown/NaN "
                "position — nothing to stitch."
            )
            return None, ""
        return tiles, self._survey_position_source

    def _resolve_px_per_mm(self) -> tuple[float | None, str]:
        """Pixel scale for placement, in priority order: the recorded
        calibration's scalar ``px_per_mm`` attr; else the recorded affine's
        own ``mean_px_per_mm``; else — for an uncalibrated photo-only
        survey — inferred from the known tile pixel shape vs. the survey
        plan's ``fov_mm`` (still "nominal", same honesty caveat as the
        affine-absent case). ``None`` when nothing above yields a usable
        (positive) scale at all."""
        px = self._camera.get("px_per_mm")
        if px is not None and px > 0:
            return float(px), "calibration"
        affine = self._camera.get("affine_fit")
        if affine is not None:
            try:
                v = float(affine.mean_px_per_mm)
                if v > 0:
                    return v, "calibration"
            except (ValueError, ZeroDivisionError):
                pass
        geom = self._survey_geom
        frame_shape = self._camera.get("frame_shape")
        if geom is not None and frame_shape is not None and len(frame_shape) == 2:
            fov_w, fov_h = geom.get("fov_mm", (0.0, 0.0))
            h_px, w_px = frame_shape
            scales = [
                float(w_px) / float(fov_w) if fov_w else 0.0,
                float(h_px) / float(fov_h) if fov_h else 0.0,
            ]
            scales = [s for s in scales if s > 0]
            if scales:
                return float(np.mean(scales)), "survey_fov"
        return None, "none"

    def _survey_area_mm(
        self, xs: list[float], ys: list[float], half_w_mm: float, half_h_mm: float,
    ) -> tuple[float, float, float, float]:
        """Bounding rectangle for :func:`~analysis.mosaic_stitch.
        canvas_geometry`. The geometry ladder rung already covers the whole
        planned raster exactly (``safety['survey']``'s own area); the
        frame_pos_mm rung has no such rectangle, so it pads the raw tile
        centres' bounding box by half a tile footprint per side — matching
        how ``plan_grid`` itself sizes a raster so every tile's own edge
        lands inside the canvas."""
        if self._survey_position_source == "geometry" and self._survey_geom is not None:
            return self._survey_rect(self._survey_geom)
        x0, x1 = min(xs) - half_w_mm, max(xs) + half_w_mm
        y0, y1 = min(ys) - half_h_mm, max(ys) + half_h_mm
        return (x0, y0, x1, y1)

    def _build_survey_mosaic(self) -> None:
        if not _HAS_PG:
            return
        tiles, _source = self._collect_survey_tiles()
        if tiles is None:
            return   # _collect_survey_tiles already showed an EmptyState

        px_per_mm, px_source = self._resolve_px_per_mm()
        if px_per_mm is None:
            self._show_survey_empty(
                "No pixel scale available",
                "No camera calibration (set_camera_calibration) and no "
                "survey geometry to infer one from — cannot place tiles "
                "in real mm coordinates."
            )
            return

        affine = self._camera.get("affine_fit")
        frame_h, frame_w = tiles[0][0].shape
        half_w_mm = (frame_w / 2.0) / px_per_mm
        half_h_mm = (frame_h / 2.0) / px_per_mm
        xs = [c[0] for _img, c in tiles]
        ys = [c[1] for _img, c in tiles]
        area_mm = self._survey_area_mm(xs, ys, half_w_mm, half_h_mm)

        try:
            shape_px, origin_mm = canvas_geometry(area_mm, px_per_mm, affine=affine)
        except ValueError as exc:
            self._show_survey_empty("Mosaic build failed", str(exc))
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            canvas, _weight, diag = place_tiles(
                shape_px, tiles, px_per_mm, origin_mm, affine=affine,
                refine=self._chk_survey_refine.isChecked(),
                return_diagnostics=True,
            )
        except ValueError as exc:
            self._show_survey_empty("Mosaic build failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self._render_survey_canvas(canvas, origin_mm, shape_px, px_per_mm)
        self._update_survey_calibration_notice(px_source, affine is not None)
        self._update_survey_diagnostics(len(tiles), diag)

    def _render_survey_canvas(
        self, canvas: np.ndarray, origin_mm: tuple[float, float],
        shape_px: tuple[int, int], px_per_mm: float,
    ) -> None:
        """Push *canvas* (mosaic_stitch's ``(row=Y, col=X)`` array — see its
        module docstring "Canvas axis convention") onto the mm-axed
        ``pg.ImageItem``. pyqtgraph's default ``imageAxisOrder`` is
        'col-major' (``image[x_index, y_index]``, verified against this
        venv's pyqtgraph 0.14) — the TRANSPOSE of mosaic_stitch's row-major
        ``(Y, X)`` convention — so the array is transposed before display;
        ``setRect`` then maps it onto the exact mm extent so axes read in
        real millimetres, the same ``pos``/``scale`` contract
        ``gui/scan_map_view.py`` uses via ``analysis.scan_grid.grid_extent``.
        NaN gaps (an omitted/never-placed tile) render as the transparent
        dark canvas showing through — pyqtgraph maps non-finite pixels to
        alpha 0 (same NaN-honesty as ``ScanMapView._redraw``) — never
        interpolated over.
        """
        h_px, w_px = shape_px
        display = np.asarray(canvas).T
        finite = canvas[~np.isnan(canvas)]
        if finite.size:
            vmin, vmax = float(np.nanmin(canvas)), float(np.nanmax(canvas))
            if vmin == vmax:
                vmax = vmin + 1e-9
        else:
            vmin, vmax = 0.0, 1.0
        self._survey_image_item.setImage(display, autoLevels=False, levels=(vmin, vmax))
        width_mm = w_px / px_per_mm
        height_mm = h_px / px_per_mm
        self._survey_image_item.setRect(
            QRectF(origin_mm[0], origin_mm[1], width_mm, height_mm))
        self._survey_plot.getPlotItem().autoRange()
        self._survey_stack.setCurrentIndex(1)
        self._survey_figure.set_subtitle(
            f"{w_px}x{h_px} px  |  {px_per_mm:.4g} px/mm  |  "
            f"origin ({origin_mm[0]:.3f}, {origin_mm[1]:.3f}) mm"
        )

    def _update_survey_calibration_notice(self, px_source: str, has_affine: bool) -> None:
        """Always-visible calibration/affine notice — never tooltip-only
        (E6b brief: "if affine is None or absent, say so in the UI")."""
        if has_affine:
            self._lbl_survey_calib.setText(
                "Calibrated placement — rotation/shear-aware affine "
                "(camera/affine) applied.")
            self._chip_survey_cal.set_status("Calibrated", "good")
        elif px_source == "calibration":
            self._lbl_survey_calib.setText(
                "Uncalibrated — nominal placement (place_tiles(affine=None)): "
                "recorded scalar px/mm used, but this run has no rotation/"
                "shear affine (camera/affine).")
            self._chip_survey_cal.set_status("Uncalibrated", "warn")
        else:
            self._lbl_survey_calib.setText(
                "Uncalibrated — nominal placement (place_tiles(affine=None)): "
                "this run recorded no camera calibration at all; pixel scale "
                "inferred from the survey FOV geometry instead.")
            self._chip_survey_cal.set_status("Uncalibrated", "warn")

    def _update_survey_diagnostics(self, n_placed: int, diag: dict) -> None:
        """E4 diagnostics readout (``place_tiles(return_diagnostics=True)``)
        plus this view's own placement-honesty counters."""
        self._tile_survey_placed.set_value(str(n_placed))
        self._tile_survey_placed.set_state("normal")
        self._tile_survey_placed.set_stale(False, "")

        n_write = int(self._camera.get("n_frames_omitted") or 0)
        self._tile_survey_omitted_write.set_value(str(n_write))
        self._tile_survey_omitted_write.set_state("warn" if n_write else "normal")
        self._tile_survey_omitted_write.set_stale(False, "")
        self._tile_survey_omitted_write.setToolTip(
            "Frames dropped at WRITE time (grab failure / shape mismatch) — "
            "camera group attr n_frames_omitted.")

        n_pos = self._survey_n_pos_omitted
        self._tile_survey_omitted_pos.set_value(str(n_pos))
        self._tile_survey_omitted_pos.set_state("warn" if n_pos else "normal")
        self._tile_survey_omitted_pos.set_stale(False, "")
        self._tile_survey_omitted_pos.setToolTip(
            "Written frames that could not be PLACED (NaN/unknown position, "
            "or beyond the reconstructed survey grid) — shown as gaps.")

        n_clamped = int(diag.get("n_clamped", 0))
        self._tile_survey_clamped.set_value(str(n_clamped))
        self._tile_survey_clamped.set_state("warn" if n_clamped else "normal")
        self._tile_survey_clamped.set_stale(False, "")
        self._tile_survey_clamped.setToolTip(
            "Overlapping tile pairs whose seam-refinement correction hit "
            "the ±25% clamp (0 when 'Refine seams' is off).")

        mean_off = float(diag.get("mean_abs_offset_px", 0.0))
        self._tile_survey_offset.set_value(f"{mean_off:.3f} px")
        self._tile_survey_offset.set_state("normal")
        self._tile_survey_offset.set_stale(False, "")
        self._tile_survey_offset.setToolTip(
            "Mean |applied seam-refinement offset| over placed tiles "
            "(0 when 'Refine seams' is off).")

    # ------------------------------------------------------------------ #
    # Sensor-pose alignment — E7c ("numbers only, never motion")          #
    # ------------------------------------------------------------------ #

    def _update_pose_availability(self) -> None:
        """Gate "Detect sensor pose" on ``sensor_align.is_available()`` AND
        loaded camera frames (E7c objective 1) — a mosaic does not need to
        be BUILT yet, only ``camera/frames`` loaded (``_load_camera_group``
        already ran by the time this is called from ``_reset_survey_state``).
        Always sets a tooltip explaining a disabled state (never a bare
        greyed-out button): the exact cv2 install hint when OpenCV is
        missing/too old, or "load a run" when frames are absent."""
        if not hasattr(self, "_btn_detect_pose"):
            return
        frames = self._camera.get("frames")
        has_frames = frames is not None and len(frames) > 0
        available = sensor_align.is_available()
        self._btn_detect_pose.setEnabled(bool(available and has_frames))
        if not available:
            reason = _vision_unavailable_reason() or (
                "OpenCV (opencv-python-headless) is not installed, or "
                "lacks the modern cv2.aruco.ArucoDetector API — "
                "sensor-pose detection is unavailable."
            )
            self._btn_detect_pose.setToolTip(reason)
        elif not has_frames:
            self._btn_detect_pose.setToolTip(
                "Load a run with camera frames first — no 'camera/frames' "
                "dataset loaded.")
        else:
            self._btn_detect_pose.setToolTip(
                "Detect ArUco fiducial markers in this run's first and "
                "last captured frame and estimate the sensor's pose drift "
                "between them (vision.sensor_align — numbers only, "
                "commands nothing).")

    def _reset_pose_state(self) -> None:
        """New run loaded (or panel just built) — a previously detected
        pose belongs to a different file's camera frames; drop back to the
        honest "no pose" state (same "a previous run's state may not still
        apply" reasoning as ``_reset_cce_fit_tiles``/``_reset_survey_state``).
        Works with or without pyqtgraph (only ``_clear_pose_overlay``
        itself is pg-gated) so the tiles/buttons/chip always reflect
        reality even on the "pyqtgraph not installed" degraded page."""
        self._survey_pose = None
        self._clear_pose_overlay()
        if not hasattr(self, "_tile_pose_theta"):
            return
        for tile in (
            self._tile_pose_theta, self._tile_pose_translation,
            self._tile_pose_baseline, self._tile_pose_precision,
        ):
            tile.set_value("—")
            tile.set_state("normal")
            tile.set_stale(True, "no pose detected")
            tile.setToolTip("")
        self._chip_pose_precision.set_status("No pose", "neutral", "")
        self._btn_align_grid.setEnabled(False)
        self._btn_align_grid.setToolTip(
            "Run “Detect sensor pose” first — applies nothing — copies "
            "the suggested correction (numbers only; no plan/motion "
            "change).")
        self._lbl_align_grid_result.setVisible(False)
        self._lbl_align_grid_result.setText("")

    def _clear_pose_overlay(self) -> None:
        """Remove any pose-overlay pyqtgraph items from the mosaic plot —
        called before every new detect (and on reset) so a stale overlay
        never lingers alongside a fresh one. A no-op without pyqtgraph or
        before the survey plot exists."""
        if _HAS_PG and getattr(self, "_survey_plot", None) is not None:
            for item in self._survey_pose_items:
                self._survey_plot.removeItem(item)
            if self._survey_pose_bbox is not None:
                self._survey_plot.removeItem(self._survey_pose_bbox)
        self._survey_pose_items = []
        self._survey_pose_bbox = None

    def _last_frame_center_mm(self) -> tuple[float, float] | None:
        """mm centre of the LAST loaded camera frame (index -1) — the
        "current" detection's tile position, used only to place the pose
        overlay on the mosaic canvas (rung 1 of the position-source ladder,
        ``camera/frame_pos_mm``, only — unlike ``_collect_survey_tiles``
        this does NOT fall back to ``safety['survey']`` geometry, since the
        overlay is a bonus visual and calling ``_collect_survey_tiles``
        here would have the side effect of switching the Survey stack to
        an EmptyState on a position-source miss, clobbering whatever the
        page currently shows). The pose NUMBERS (``_update_pose_tiles``)
        never depend on this — only the optional overlay does. Returns
        ``None`` (skip the overlay) when unavailable."""
        pos_mm = self._camera.get("frame_pos_mm")
        if pos_mm is None or len(pos_mm) == 0:
            return None
        x, y = float(pos_mm[-1][0]), float(pos_mm[-1][1])
        if not (np.isfinite(x) and np.isfinite(y)):
            return None
        return x, y

    def _on_detect_sensor_pose(self) -> None:
        """"Detect sensor pose" (E7c objectives 1-2): estimate the ArUco
        pose delta between the FIRST and LAST captured frame of this run.

        Reference-frame choice: frame index 0 is treated as this run's own
        nominal/plan orientation (the earliest capture — the assumed
        baseline an operator wants to check for drift against, before any
        of the run's own stage motion could have disturbed the mount), and
        frame index -1 (the most recently captured frame) is "current".
        This is a WITHIN-RUN drift check, not a comparison against a
        separately stored reference image: ``vision.sensor_align``'s own
        contract (``estimate_relative_pose``'s docstring) only requires two
        ``DetectionResult``s with overlapping marker IDs and does not
        prescribe which frames those come from. A future beat could let an
        operator pick an explicit reference frame instead.
        """
        frames = self._camera.get("frames")
        if frames is None or len(frames) == 0 or not sensor_align.is_available():
            return   # defensive — the button is gated on both already
        try:
            reference = sensor_align.detect_markers(frames[0])
            current = sensor_align.detect_markers(frames[-1])
            pose = sensor_align.estimate_relative_pose(reference, current)
        except sensor_align.VisionError as exc:
            self._show_pose_failure(str(exc))
            return

        self._survey_pose = pose
        self._update_pose_tiles(pose)
        self._render_pose_overlay(current, pose)
        self._btn_align_grid.setEnabled(True)
        self._btn_align_grid.setToolTip(
            "Copy the suggested scan-grid correction — applies nothing "
            "(numbers only; no plan/motion change).")
        flash_button(self._btn_detect_pose, "good", "Pose detected")

    def _show_pose_failure(self, msg: str) -> None:
        """Detection/pose failure (e.g. no markers in either frame, or no
        marker ID common to both) — an honest reset with the real reason,
        never a crash or a stale previous pose left on screen."""
        logger.warning(
            "Sensor-pose detection failed for run %r: %s", self._run_path, msg)
        self._survey_pose = None
        self._clear_pose_overlay()
        self._btn_align_grid.setEnabled(False)
        self._lbl_align_grid_result.setVisible(False)
        reason = msg[:160]
        for tile in (
            self._tile_pose_theta, self._tile_pose_translation,
            self._tile_pose_baseline, self._tile_pose_precision,
        ):
            tile.set_value("—")
            tile.set_state("normal")
            tile.set_stale(True, reason)
        self._chip_pose_precision.set_status("Detection failed", "warn", msg)

    def _update_pose_tiles(self, pose) -> None:
        """Populate the θ/translation/baseline/precision tiles + the
        ``meets_precision_target`` chip from one ``PoseEstimate`` (E7c
        objective 4) — quality is always shown, never hidden:
        ``meets_precision_target`` drives both the precision tile's state
        AND a dedicated ``StatusChip``, matching this file's own
        ``_QUALITY_OK_MIN``/``_QUALITY_WARN_MIN`` banding precedent."""
        self._tile_pose_theta.set_value(f"{pose.theta_deg:+.3f}°")
        self._tile_pose_theta.set_state("normal")
        self._tile_pose_theta.set_stale(False, "")
        self._tile_pose_theta.setToolTip(
            f"scale={pose.scale:.4f}, n_points={pose.n_points}, "
            f"n_inliers={pose.n_inliers}")

        px_per_mm, _px_src = self._resolve_px_per_mm()
        tx_px, ty_px = float(pose.translation_px[0]), float(pose.translation_px[1])
        if px_per_mm:
            tx_um = tx_px / px_per_mm * 1000.0
            ty_um = ty_px / px_per_mm * 1000.0
            mag_um = math.hypot(tx_um, ty_um)
            self._tile_pose_translation.set_value(f"{mag_um:.2f} µm")
            self._tile_pose_translation.setToolTip(
                f"dx={tx_um:+.2f} µm, dy={ty_um:+.2f} µm "
                f"(dx={tx_px:+.2f} px, dy={ty_px:+.2f} px)")
        else:
            self._tile_pose_translation.set_value(
                f"{math.hypot(tx_px, ty_px):.2f} px")
            self._tile_pose_translation.setToolTip(
                "no pixel scale on file — showing raw pixels, not µm")
        self._tile_pose_translation.set_state("normal")
        self._tile_pose_translation.set_stale(False, "")

        self._tile_pose_baseline.set_value(f"{pose.baseline_px:.1f} px")
        self._tile_pose_baseline.set_state("normal")
        self._tile_pose_baseline.set_stale(False, "")
        self._tile_pose_baseline.setToolTip(
            "recommended minimum: "
            f"{sensor_align.RECOMMENDED_MIN_BASELINE_PX:.0f} px "
            "(docs/research/sensor_alignment_cv.md sec. 4)")

        precision_state = "good" if pose.meets_precision_target else "warn"
        self._tile_pose_precision.set_value(f"{pose.estimated_precision_deg:.4f}°")
        self._tile_pose_precision.set_state(precision_state)
        self._tile_pose_precision.set_stale(False, "")
        self._tile_pose_precision.set_caption(
            "meets target" if pose.meets_precision_target
            else "below target — widen marker spread")

        if pose.meets_precision_target:
            self._chip_pose_precision.set_status("Meets target", "good")
        else:
            self._chip_pose_precision.set_status("Below target", "warn")
        self._chip_pose_precision.setToolTip(
            f"estimated_precision_deg={pose.estimated_precision_deg:.4f}, "
            f"baseline_px={pose.baseline_px:.1f}, target="
            f"{sensor_align.TARGET_ANGLE_PRECISION_DEG:.2f}°")

    def _render_pose_overlay(self, current, pose) -> None:
        """Pose overlay (E7c objective 3): the "current" (last-frame)
        detection's marker corner outlines + a rotated bounding-box
        indicator, in mm, on the Survey mosaic — pyqtgraph items, theme-
        token colours only (``DARK["accent"]``/``DARK["sim"]`` — never
        danger red), matching the CCE plot's own "fixed-dark canvas,
        theme-invariant pens" convention (``_build_cce_mode``).

        Placement uses the SAME nominal (isotropic ``px_per_mm``, no
        rotation) scale this page already uses for an uncalibrated run's
        tile footprint (``half_w_mm``/``half_h_mm`` in
        ``_build_survey_mosaic``) — even when a rotation/shear affine is on
        file, since this is a diagnostic overlay, not the load-bearing pose
        NUMBERS (which come untouched from ``vision.sensor_align`` and are
        never approximated). Silently clears any stale overlay and no-ops
        when the last frame's mm position/pixel scale cannot be resolved —
        the numbers above already stand on their own regardless.
        """
        self._clear_pose_overlay()
        if not (_HAS_PG and getattr(self, "_survey_plot", None) is not None):
            return
        if current.n_detected == 0:
            return
        center_mm = self._last_frame_center_mm()
        px_per_mm, _px_src = self._resolve_px_per_mm()
        frames = self._camera.get("frames")
        if center_mm is None or px_per_mm is None or frames is None or len(frames) == 0:
            return
        frame_h, frame_w = self._as_grayscale(frames[-1]).shape

        def _to_mm(u: float, v: float) -> tuple[float, float]:
            return (
                center_mm[0] + (float(u) - frame_w / 2.0) / px_per_mm,
                center_mm[1] + (float(v) - frame_h / 2.0) / px_per_mm,
            )

        for marker in current.markers:
            pts_mm = [_to_mm(u, v) for u, v in marker.corners_px]
            pts_mm.append(pts_mm[0])
            curve = pg.PlotCurveItem(
                [p[0] for p in pts_mm], [p[1] for p in pts_mm],
                pen=pg.mkPen(DARK["accent"], width=2))
            self._survey_plot.addItem(curve)
            self._survey_pose_items.append(curve)

        half_w_mm = (frame_w / 2.0) / px_per_mm
        half_h_mm = (frame_h / 2.0) / px_per_mm
        theta = math.radians(pose.theta_deg)
        c, s = math.cos(theta), math.sin(theta)
        corners_local = (
            (-half_w_mm, -half_h_mm), (half_w_mm, -half_h_mm),
            (half_w_mm, half_h_mm), (-half_w_mm, half_h_mm),
        )
        xs = [center_mm[0] + lx * c - ly * s for lx, ly in corners_local]
        ys = [center_mm[1] + lx * s + ly * c for lx, ly in corners_local]
        xs.append(xs[0])
        ys.append(ys[0])
        self._survey_pose_bbox = pg.PlotCurveItem(
            xs, ys,
            pen=pg.mkPen(DARK["sim"], width=2, style=Qt.PenStyle.DashLine))
        self._survey_plot.addItem(self._survey_pose_bbox)

    def _on_align_scan_grid(self) -> None:
        """"Align scan grid" (E7c objective 5) — HARD LAW: numbers only,
        never motion. Computes and DISPLAYS the suggested grid correction
        (also copied to the clipboard) and emits ``grid_alignment_suggested``
        with the same numbers. This method never imports/calls a
        controller, never mutates a scan plan, and never commands a
        device — the eventual consumer of the emitted numbers (applying
        them to a plan/motion) is a later, danger-gated beat."""
        pose = self._survey_pose
        if pose is None:
            return   # defensive — the button is gated on a successful detect
        px_per_mm, _px_src = self._resolve_px_per_mm()
        tx_px, ty_px = float(pose.translation_px[0]), float(pose.translation_px[1])
        dx_mm = tx_px / px_per_mm if px_per_mm else None
        dy_mm = ty_px / px_per_mm if px_per_mm else None
        payload = {
            "theta_deg": pose.theta_deg,
            "dx_mm": dx_mm,
            "dy_mm": dy_mm,
            "baseline_px": pose.baseline_px,
            "estimated_precision_deg": pose.estimated_precision_deg,
            "meets_precision_target": pose.meets_precision_target,
        }
        text = (
            f"theta_deg={payload['theta_deg']:+.4f}  "
            f"dx_mm={'n/a' if dx_mm is None else f'{dx_mm:+.5f}'}  "
            f"dy_mm={'n/a' if dy_mm is None else f'{dy_mm:+.5f}'}  "
            f"baseline_px={payload['baseline_px']:.2f}  "
            f"meets_precision_target={payload['meets_precision_target']}"
        )
        try:
            QApplication.clipboard().setText(text)
        except Exception:
            pass   # clipboard is a convenience only — the visible label is load-bearing
        self._lbl_align_grid_result.setText(text)
        self._lbl_align_grid_result.setVisible(True)
        self.grid_alignment_suggested.emit(payload)
        flash_button(self._btn_align_grid, "good", "Copied")

    # ------------------------------------------------------------------ #
    # Theme                                                               #
    # ------------------------------------------------------------------ #

    def refresh_theme(self, mode: str | None = None) -> None:
        """Delegate to the embedded shared map view (its own empty-state
        icon tint re-resolves; the map canvas itself is fixed-dark in both
        themes). CCE pens are theme-invariant by design — see
        ``_build_cce_mode``. Survey mode's own cached pens/EmptyState follow
        the same "fixed-dark canvas, re-resolve axis text + EmptyState
        tint" idiom as ``ScanMapView.refresh_theme``."""
        if _HAS_PG and hasattr(self, "_map_view"):
            self._map_view.refresh_theme(mode)
        if mode:
            self._survey_theme_mode = str(mode)
        if _HAS_PG and hasattr(self, "_survey_plot") and self._survey_plot is not None:
            text_pen = pg.mkPen(PLOT_FG)
            plot_item = self._survey_plot.getPlotItem()
            for axis_name in ("bottom", "left"):
                axis = plot_item.getAxis(axis_name)
                axis.setPen(text_pen)
                axis.setTextPen(text_pen)
            if self._survey_empty is not None:
                self._survey_empty.refresh_theme(self._survey_theme_mode)
