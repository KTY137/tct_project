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
"""
from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton,
    QDoubleSpinBox, QSpinBox, QFileDialog, QStackedWidget,
    QSplitter, QToolButton,
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

from analysis.cce import cce_vs_reference
from analysis.efield_analysis import compute_cce_with_uncertainty, fit_depletion_voltage
from analysis.map_slice import (
    display_unit_scale, mm_to_index, slice_grid_at_mm, strip_unit_suffix,
)
from analysis.scan_grid import grid_extent
from gui.panel_kit import (
    Card, FigureCard, MetricGrid, MetricTile, SegmentedControl, panel_header,
)
from gui.scan_map_view import QUANTITIES, QUANTITY_UNITS, ScanMapView
from gui.status_widgets import StatusChip, flash_button, set_button_icon
from gui.style import DARK, PLOT_FG, PLOT_OVERLAY, SPACE_MD, SPACE_SM

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


class AnalysisPanel(QWidget):
    """Load a completed run HDF5 file and re-analyse / re-plot.

    *runs_dir* is where the recent-runs empty state looks for ``*.h5`` files
    (default matches ``output.data_dir``'s default in ``configs/devices.yaml``
    — run folders like ``runs/run_00001/waveforms.h5``). Purely a read-only
    listing; nothing is written there by this panel.
    """

    def __init__(self, parent: QWidget | None = None,
                 runs_dir: str | Path = "runs") -> None:
        super().__init__(parent)
        self._runs_dir = Path(runs_dir)
        self._data: dict = {}          # loaded HDF5 data arrays
        self._voltage_scan: dict = {}  # loaded 'voltage_scan/{voltage_V,charge_pC,current_A}'
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

        root.addWidget(panel_header("TCT Control · Analysis", "Run Analysis"))

        # ── Compact run-header bar (always visible) ───────────────────
        # File identity + load/export status chips + Browse in ONE row —
        # the §7 "compact run-header bar" that replaces the old full-height
        # file-loader card.
        header_card = Card(None, margins=(SPACE_SM + 2, SPACE_SM, SPACE_SM + 2, SPACE_SM))
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
        root.addWidget(header_card)

        # ── Empty state (recent runs) <-> loaded analysis stack ──────
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_recent_runs_page())   # index 0
        self._stack.addWidget(self._build_loaded_page())        # index 1
        root.addWidget(self._stack, 1)

    def _build_recent_runs_page(self) -> QWidget:
        """The designed empty state: the last N run files, newest first —
        click to load — plus a browse row (§7)."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        card = Card("Recent runs", str(self._runs_dir))
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
            [("map", "2D map"), ("cce", "CCE vs bias")], current="map")
        seg_row = QHBoxLayout()
        seg_row.addWidget(self._segmented)
        seg_row.addStretch(1)
        lay.addLayout(seg_row)

        self._modes = QStackedWidget()
        self._modes.addWidget(self._build_map_mode())   # index 0
        self._modes.addWidget(self._build_cce_mode())   # index 1
        self._segmented.selection_changed.connect(
            lambda key: self._modes.setCurrentIndex(0 if key == "map" else 1))
        lay.addWidget(self._modes, 1)
        return page

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
            self._stack.setCurrentIndex(1)
            return True
        except Exception as exc:
            self._chip_file.set_status("Load error", "crit", str(exc))
            return False

    def _load_h5(self, path: str) -> None:
        self._data = {}
        self._voltage_scan = {}
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
    # Theme                                                               #
    # ------------------------------------------------------------------ #

    def refresh_theme(self, mode: str | None = None) -> None:
        """Delegate to the embedded shared map view (its own empty-state
        icon tint re-resolves; the map canvas itself is fixed-dark in both
        themes). CCE pens are theme-invariant by design — see
        ``_build_cce_mode``."""
        if _HAS_PG and hasattr(self, "_map_view"):
            self._map_view.refresh_theme(mode)
