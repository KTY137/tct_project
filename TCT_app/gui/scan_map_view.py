"""
Shared 2-D scan-map widget — the single map renderer behind the live
:class:`~gui.scan_viewer_panel.ScanViewerPanel` and the post-run
:class:`~gui.analysis_panel.AnalysisPanel` re-plot
(``docs/research/scan_viewer_design_review.md`` build order step 2).
Reconstructs a scattered ``(x_mm, y_mm, value)`` point cloud into a dense 2-D
image via the canonical :mod:`analysis.scan_grid` helper — this widget never
re-derives the grid/NaN logic inline (that duplication, across the retired
``scan_panel``/``scan_map_window`` and ``analysis_panel``, is exactly what
``analysis.scan_grid`` was built to retire).

Self-contained ``QWidget`` wrapping a ``gui.panel_kit.FigureCard`` (cockpit
kit, rule 3: no ``QGraphicsEffect`` on this hot-path plot). No hardware I/O —
safe to construct headless with simulated backends only.

Public API
----------
``update_point(result)``
    Live streaming: accumulate one ``controller.scan_controller.ScanResult``
    (keyed by rounded ``(x_mm, y_mm)``, last-write-wins) and re-render.
``set_points(mapping_or_iterable)``
    Batch load: replace all accumulated points at once, from either a
    ``{(x_mm, y_mm): ScanResult}`` mapping (this widget's own storage shape,
    for a fast bulk re-seed) or a flat iterable of ``ScanResult`` objects
    (each point's position read from ``result.point``).
``set_quantity(qty)`` / current quantity via the combo
    Switch the displayed quantity — re-renders from the same accumulated
    points, no re-streaming needed (every quantity is captured per point on
    arrival).
``refresh_theme(mode)``
    Re-applies the cached axis/canvas pens after a light/dark switch.

The toolbar also carries a PNG/CSV export pair and a "freeze levels" toggle
(this widget now owns the export controls that used to live only on the
retired standalone map window — see
``_write_png``/``_write_csv``/``_on_freeze_toggled`` below).
The export buttons open a ``QFileDialog`` on click; ``_write_png(path)`` /
``_write_csv(path)`` are the dialog-free write helpers underneath them, for
programmatic/tested use. "Freeze levels" (ratified 2026-07-10, was the
parked "Map colorbar levels" decision — ``docs/OVERNIGHT_LOG.md``) keeps the
colorbar min/max fixed at whatever it was when checked, instead of
``_redraw``'s default per-call nanmin/nanmax autoscale.
"""
from __future__ import annotations

import csv

import numpy as np
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

try:
    import pyqtgraph as pg
    import pyqtgraph.exporters  # noqa: F401 — pg.exporters is not auto-imported; PNG export needs it
    _HAS_PG = True
except ImportError:  # pragma: no cover - exercised only without pyqtgraph installed
    _HAS_PG = False

from analysis.scan_grid import ScanGridResult, grid_extent, points_to_grid
from gui.panel_kit import EmptyState, FigureCard
from gui.status_widgets import StatusChip, flash_button, set_button_icon
from gui.style import PLOT_BG, PLOT_FG, SPACE_SM

# Quantities available on a controller.scan_controller.ScanResult that make
# sense as a 2-D map — the set every prior map renderer offered.
QUANTITIES: list[str] = [
    "dut_charge_pC",
    "dut_charge_norm",
    "dut_amplitude_V",
    "ref_amplitude_V",
    "baseline_rms_V",
    "drift_time_s",
    "rise_time_s",
    "cfd_time_s",
]

# Physical unit per map quantity — bound to the colorbar axis label on every
# quantity switch (design system §4: "Colorbar always, with unit bound to the
# selected quantity"). ``dut_charge_norm`` is a dimensionless ratio.
QUANTITY_UNITS: dict[str, str] = {
    "dut_charge_pC": "pC",
    "dut_charge_norm": "",
    "dut_amplitude_V": "V",
    "ref_amplitude_V": "V",
    "baseline_rms_V": "V",
    "drift_time_s": "s",
    "rise_time_s": "s",
    "cfd_time_s": "s",
}


def _extract_values(entry) -> dict[str, float]:
    """Pull every :data:`QUANTITIES` value out of *entry* (a ``ScanResult``,
    or a plain ``{quantity: value}`` dict for lightweight batch loading),
    defaulting anything missing/invalid to NaN so a later quantity switch
    always has a well-defined (if empty) cell rather than a ``KeyError``."""
    out: dict[str, float] = {}
    is_mapping = isinstance(entry, dict)
    for qty in QUANTITIES:
        v = entry.get(qty) if is_mapping else getattr(entry, qty, None)
        try:
            out[qty] = float(v) if v is not None else float("nan")
        except (TypeError, ValueError):
            out[qty] = float("nan")
    return out


class ScanMapView(QWidget):
    """Reusable 2-D scan-map widget: quantity selector + live map + colorbar
    + cursor readout, built once and embedded wherever a live or batch scan
    map is shown."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        empty_label: str = "No scan data",
        empty_hint: str = "Points appear here as they are acquired.",
    ) -> None:
        super().__init__(parent)
        self._empty_label_text = empty_label
        self._empty_hint_text = empty_hint
        self._points: dict[tuple[float, float], dict[str, float]] = {}
        self._grid_result: ScanGridResult | None = None
        self._pos: tuple[float, float] = (0.0, 0.0)
        self._scale: tuple[float, float] = (1.0, 1.0)
        self._theme_mode = "dark"
        # Colorbar "freeze levels" (ratified 2026-07-10, was the parked "Map
        # colorbar levels" decision — docs/OVERNIGHT_LOG.md): while frozen,
        # _redraw keeps _frozen_range fixed instead of recomputing
        # nanmin/nanmax every call. Re-armed (cleared to None) every time
        # freezing is turned off, so the *next* freeze captures a fresh range
        # rather than replaying a stale one.
        self._freeze_levels = False
        self._frozen_range: tuple[float, float] | None = None
        # Revisited-cell counter (design system §4: "Missing/duplicate counts
        # surfaced"). This widget stores points in a dict keyed by rounded
        # (x, y) — a revisit overwrites silently at the storage layer, so the
        # duplicate count must be tallied HERE, on arrival, before the
        # dedup; analysis.scan_grid's own n_duplicate_points can never see
        # them through this widget.
        self._n_duplicates = 0
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE_SM)

        # Map toolbar — deliberately OUTSIDE the empty/map stack below, so
        # quantity/freeze/export stay visible (if inert) even before the
        # first point arrives (design system §7: "map toolbar visible even
        # in empty state").
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Quantity:"))
        self._combo_qty = QComboBox()
        self._combo_qty.addItems(QUANTITIES)
        self._combo_qty.currentTextChanged.connect(self._redraw)
        toolbar.addWidget(self._combo_qty)
        self._chip_points = StatusChip("No data", "neutral")
        toolbar.addWidget(self._chip_points)
        toolbar.addStretch(1)

        # Compact trailing control cluster — freeze-levels toggle + PNG/CSV
        # export, icon-only so embedding this widget in a panel (e.g.
        # ScanViewerPanel) never grows the row. The export logic lives on this
        # shared widget so every embedder gets it for free (it used to sit on
        # the now-retired standalone map window).
        self._btn_freeze = QToolButton()
        self._btn_freeze.setCheckable(True)
        self._btn_freeze.setToolTip(
            "Freeze colorbar levels — keep the current min/max fixed as new "
            "points arrive (unchecked = live autoscale)")
        set_button_icon(self._btn_freeze, "mdi.snowflake")
        self._btn_freeze.toggled.connect(self._on_freeze_toggled)
        toolbar.addWidget(self._btn_freeze)

        self._btn_export_png = QToolButton()
        self._btn_export_png.setToolTip("Export map as PNG")
        set_button_icon(self._btn_export_png, "mdi.image")
        self._btn_export_png.clicked.connect(self._on_export_png_clicked)
        toolbar.addWidget(self._btn_export_png)

        self._btn_export_csv = QToolButton()
        self._btn_export_csv.setToolTip("Export points as CSV")
        set_button_icon(self._btn_export_csv, "mdi.content-save")
        self._btn_export_csv.clicked.connect(self._on_export_csv_clicked)
        toolbar.addWidget(self._btn_export_csv)

        root.addLayout(toolbar)

        if _HAS_PG:
            self._plot_item = pg.PlotItem()
            self._plot_item.setLabel("bottom", "X", units="mm")
            self._plot_item.setLabel("left", "Y", units="mm")
            self._image_view = pg.ImageView(view=self._plot_item)
            self._image_view.setMinimumHeight(240)
            # Viridis for all single-signed maps (design system §4 —
            # Jonathan's ruling; replaces pyqtgraph's default greyscale).
            self._image_view.setColorMap(pg.colormap.get("viridis"))
            # Colorbar unit binding: the histogram's axis IS the colorbar
            # scale; _redraw re-labels it with the selected quantity + unit.
            self._hist_axis = self._image_view.ui.histogram.axis
            # Disable ROI rotation — only axis-aligned resize makes sense on
            # a stage-position map (same guard as analysis_panel).
            _roi = self._image_view.roi
            _roi.rotatable = False
            for _h in list(_roi.handles):
                if _h["type"] == "r":
                    _roi.removeHandle(_h["item"])
            self._mouse_proxy = pg.SignalProxy(
                self._plot_item.scene().sigMouseMoved, rateLimit=30,
                slot=self._on_mouse_moved)

            self._figure_card = FigureCard("2D scan map", "no data",
                                           figure=self._image_view)
            self._figure_card.body.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)

            # Empty/map swap lives INSIDE this widget (below the toolbar) so
            # embedders never need their own stacked placeholder around it.
            self._empty_state = EmptyState(
                "fa5s.map", self._empty_label_text, self._empty_hint_text,
                theme_mode=self._theme_mode,
            )
            self._stack = QStackedWidget()
            self._stack.addWidget(self._empty_state)   # index 0
            self._stack.addWidget(self._figure_card)   # index 1
            root.addWidget(self._stack, 1)
        else:  # pragma: no cover - exercised only without pyqtgraph installed
            self._figure_card = None
            self._empty_state = None
            self._stack = None
            root.addWidget(QLabel(
                "pyqtgraph not installed — cannot display map.\n"
                "Run:  pip install pyqtgraph"
            ))

        self._lbl_cursor = QLabel("x: -- mm   y: -- mm   value: --")
        self._lbl_cursor.setObjectName("cardSubtitle")
        root.addWidget(self._lbl_cursor)

        self.refresh_theme(self._theme_mode)

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def update_point(self, result) -> None:
        """Accept one live ``controller.scan_controller.ScanResult`` and
        re-render — the incremental streaming path."""
        x = round(float(result.point.x_mm), 6)
        y = round(float(result.point.y_mm), 6)
        if (x, y) in self._points:
            self._n_duplicates += 1
        self._points[(x, y)] = _extract_values(result)
        self._redraw()

    def set_points(self, mapping_or_iterable) -> None:
        """Batch-load points, replacing any accumulated state.

        Accepts either a mapping of ``(x_mm, y_mm) -> ScanResult`` (or a
        plain ``{quantity: value}`` dict) — this widget's own storage shape,
        for a fast bulk replace — or a flat iterable of ``ScanResult``
        objects (each point's position read from ``result.point``).
        """
        self._points.clear()
        self._n_duplicates = 0
        if hasattr(mapping_or_iterable, "items"):
            for key, entry in mapping_or_iterable.items():
                x, y = key
                rounded_key = (round(float(x), 6), round(float(y), 6))
                # Two distinct raw keys can collide once rounded (same honest
                # counter as the iterable branch below) — never silently
                # absorbed (design system §4).
                if rounded_key in self._points:
                    self._n_duplicates += 1
                self._points[rounded_key] = _extract_values(entry)
        else:
            for entry in mapping_or_iterable:
                point = getattr(entry, "point", None)
                if point is None:
                    continue
                key = (round(float(point.x_mm), 6), round(float(point.y_mm), 6))
                if key in self._points:
                    self._n_duplicates += 1
                self._points[key] = _extract_values(entry)
        self._redraw()

    def set_quantity(self, qty: str) -> None:
        """Programmatically select the displayed quantity."""
        idx = self._combo_qty.findText(qty)
        if idx >= 0:
            self._combo_qty.setCurrentIndex(idx)

    def current_quantity(self) -> str:
        return self._combo_qty.currentText()

    def clear(self) -> None:
        """Remove all accumulated points and reset the map."""
        self._points.clear()
        self._n_duplicates = 0
        self._redraw()

    def point_count(self) -> int:
        return len(self._points)

    def duplicate_count(self) -> int:
        """How many arriving points revisited an already-sampled (rounded)
        cell since the last ``clear()``/``set_points()`` reset — surfaced,
        never silently absorbed (design system §4)."""
        return self._n_duplicates

    def points(self) -> dict[tuple[float, float], dict[str, float]]:
        """A shallow copy of the accumulated ``(x_mm, y_mm) -> {quantity:
        value}`` points — for a caller that needs the raw per-point data
        rather than the gridded image (e.g. this widget's own CSV export)."""
        return dict(self._points)

    def image_view(self):
        """The underlying ``pyqtgraph.ImageView`` (``None`` if pyqtgraph is
        not installed) — for a caller that needs the raw plot item rather than
        going through this widget's own API (e.g. this widget's own PNG
        export)."""
        return self._image_view if _HAS_PG else None

    def grid_result(self) -> ScanGridResult | None:
        """The most recent :class:`~analysis.scan_grid.ScanGridResult` (for
        the currently selected quantity), or ``None`` before any data."""
        return self._grid_result

    def set_empty_state_text(self, label: str, hint: str | None = None) -> None:
        """Customise the built-in empty placeholder (shown until the first
        point arrives) — e.g. the Scan Viewer points it at the Planner."""
        self._empty_label_text = label
        if hint is not None:
            self._empty_hint_text = hint
        if self._empty_state is not None:
            self._empty_state.set_label(label)
            if hint is not None:
                self._empty_state.set_hint(hint)

    def is_showing_map(self) -> bool:
        """True once the map page (vs the empty placeholder) is current."""
        return bool(self._stack is not None and self._stack.currentIndex() == 1)

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve the cached canvas/axis pens after a light/dark switch.

        The map canvas itself (``gui.style.PLOT_BG``/``PLOT_FG``) is a fixed
        dark instrument screen regardless of app theme (rule 3 — hot-path
        plots never re-theme their canvas), so this is idempotent by design;
        it exists so callers embedding this widget can register it in a
        panel-wide theme-switch loop without special-casing it.
        """
        if mode:
            self._theme_mode = str(mode)
        if self._empty_state is not None:
            self._empty_state.refresh_theme(self._theme_mode)
        if not _HAS_PG:
            return
        self._image_view.ui.graphicsView.setBackground(PLOT_BG)
        text_pen = pg.mkPen(PLOT_FG)
        for axis_name in ("bottom", "left"):
            axis = self._plot_item.getAxis(axis_name)
            axis.setPen(text_pen)
            axis.setTextPen(text_pen)

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    def _redraw(self) -> None:
        if not _HAS_PG:
            return
        qty = self._combo_qty.currentText()
        if not self._points:
            self._image_view.clear()
            self._grid_result = None
            # A stale frozen range from a prior dataset makes no sense once
            # every point is gone — re-arm so the next arriving point (with
            # freeze still checked) captures a fresh range instead.
            self._frozen_range = None
            self._chip_points.set_status("No data", "neutral")
            self._figure_card.set_subtitle("no data")
            self._lbl_cursor.setText("x: -- mm   y: -- mm   value: --")
            if self._stack is not None:
                self._stack.setCurrentIndex(0)
            return

        if self._stack is not None:
            self._stack.setCurrentIndex(1)

        xs = [k[0] for k in self._points]
        ys = [k[1] for k in self._points]
        vals = [v.get(qty, float("nan")) for v in self._points.values()]
        result = points_to_grid(xs, ys, vals)
        self._grid_result = result
        self._pos, self._scale = grid_extent(result)

        grid = result.grid
        finite = grid[~np.isnan(grid)]
        # autoHistogramRange defaults True on pg.ImageView.setImage() and, if
        # left on, pyqtgraph independently nanmin/nanmax's the RAW grid for
        # the histogram widget's own auto-range (ImageView.updateImage() ->
        # quickMinMax()) — a path entirely separate from the explicit
        # levels= kwarg below. For an all-NaN grid that recompute yields
        # NaN, which ViewBox.setRange then rejects with "Cannot set range
        # [nan, nan]", raising out of this Qt slot (Mary review finding,
        # reproduced: reachable by switching the map quantity to one absent
        # from the loaded file). Disabled for exactly that branch — the
        # explicit levels below still drive the actual colour mapping.
        auto_hist_range = True
        if finite.size:
            if self._freeze_levels:
                # Keep whatever range was captured when freezing began (or,
                # if freezing was toggled on before any data existed, the
                # very first grid seen while frozen) — new points, even ones
                # widening the true data range, never move the colorbar
                # until "freeze levels" is unchecked again.
                if self._frozen_range is None:
                    self._frozen_range = (float(np.nanmin(grid)), float(np.nanmax(grid)))
                vmin, vmax = self._frozen_range
            else:
                # Autoscale the colorbar from nanmin/nanmax over sampled cells
                # only — unsampled/NaN cells never skew the colour range.
                vmin, vmax = float(np.nanmin(grid)), float(np.nanmax(grid))
            if vmin == vmax:
                vmax = vmin + 1e-9
        else:
            # Points exist but every value is NaN (e.g. all per-point
            # analyses failed, or the selected quantity is absent from this
            # run's data) — arbitrary finite levels; every cell renders
            # transparent below, which is the honest picture.
            vmin, vmax = 0.0, 1.0
            auto_hist_range = False
        # NaN honesty (design system §4: "Unsampled cells are never
        # data-colored" — the NaN→vmin bug fix): the grid goes to the
        # ImageItem with its NaNs INTACT. pyqtgraph maps non-finite pixels
        # to alpha 0, so unsampled/invalid cells show the dark instrument
        # canvas through the map — visually distinct from every colormap
        # entry — instead of silently wearing the coldest data colour.
        self._image_view.setImage(
            grid, autoRange=True, autoLevels=False, levels=(vmin, vmax),
            pos=self._pos, scale=self._scale, autoHistogramRange=auto_hist_range,
        )

        # Colorbar unit bound to the selected quantity (§4).
        self._hist_axis.setLabel(qty, units=QUANTITY_UNITS.get(qty, ""))

        # Missing/duplicate counts surfaced (§4), quiet-nominal chip (law 1:
        # a complete map is routine, not a green light).
        n_total = int(grid.size)
        n_filled = n_total - result.n_missing
        n_dup = self._n_duplicates + result.n_duplicate_points
        self._chip_points.set_status(
            f"{n_filled}/{n_total} sampled", "neutral",
            f"{result.n_missing} cells not yet sampled · "
            f"{n_dup} duplicate points (last one wins) · "
            f"{result.n_nan_values} invalid values")
        self._figure_card.set_subtitle(
            f"{result.n_missing} unsampled · {n_dup} duplicate")
        self._update_cursor_readout()

    def _on_freeze_toggled(self, checked: bool) -> None:
        """Toolbar "freeze levels" toggle. Checking it fixes the colorbar at
        whatever range ``_redraw`` next resolves (immediately below, since
        this handler ends with a redraw); unchecking clears the captured
        range and resumes live nanmin/nanmax autoscale."""
        self._freeze_levels = bool(checked)
        if not self._freeze_levels:
            self._frozen_range = None
        self._redraw()

    def _on_export_png_clicked(self) -> None:
        if not _HAS_PG or self._image_view is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export map as PNG", "", "PNG (*.png)")
        if not path:
            return
        try:
            self._write_png(path)
            flash_button(self._btn_export_png, "good")
        except Exception as exc:
            QMessageBox.warning(self, "Export error", str(exc))

    def _on_export_csv_clicked(self) -> None:
        if not self._points:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export map as CSV", "", "CSV (*.csv)")
        if not path:
            return
        try:
            self._write_csv(path)
            flash_button(self._btn_export_csv, "good")
        except Exception as exc:
            QMessageBox.warning(self, "Export error", str(exc))

    def _write_png(self, path: str) -> None:
        """Write the current map image to *path* as PNG via pyqtgraph's
        ``ImageExporter`` — the write half of the toolbar PNG export button,
        split out so a caller (including a headless test) can drive it
        without a ``QFileDialog``."""
        if not _HAS_PG:
            raise RuntimeError("pyqtgraph is not installed — cannot export PNG")
        if self._image_view is None:
            raise RuntimeError("no map image to export")
        exporter = pg.exporters.ImageExporter(self._image_view.imageItem)
        exporter.export(path)

    def _write_csv(self, path: str) -> None:
        """Write the accumulated per-point data for the current quantity to
        *path* as CSV — the write half of the toolbar CSV export button,
        split out so a caller (including a headless test) can drive it
        without a ``QFileDialog``."""
        qty = self._combo_qty.currentText()
        with open(path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["x_mm", "y_mm", qty])
            for (x, y), values in sorted(self._points.items()):
                val = values.get(qty, float("nan"))
                writer.writerow([f"{x:.6f}", f"{y:.6f}", f"{val:.8g}"])

    def _update_cursor_readout(self, x_mm: float | None = None, y_mm: float | None = None) -> None:
        if x_mm is None or y_mm is None:
            self._lbl_cursor.setText("x: -- mm   y: -- mm   value: --")
            return
        value = self._value_at(x_mm, y_mm)
        qty = self._combo_qty.currentText()
        if value is None:
            self._lbl_cursor.setText(f"x: {x_mm:.4f} mm   y: {y_mm:.4f} mm   {qty}: --")
        else:
            self._lbl_cursor.setText(f"x: {x_mm:.4f} mm   y: {y_mm:.4f} mm   {qty}: {value:.6g}")

    def _value_at(self, x_mm: float, y_mm: float) -> float | None:
        if self._grid_result is None:
            return None
        grid = self._grid_result.grid
        nx, ny = grid.shape
        if nx == 0 or ny == 0:
            return None
        dx, dy = self._scale
        px, py = self._pos
        ix = int(round((x_mm - px) / dx)) if dx else 0
        iy = int(round((y_mm - py) / dy)) if dy else 0
        if not (0 <= ix < nx and 0 <= iy < ny):
            return None
        val = float(grid[ix, iy])
        return None if np.isnan(val) else val

    def _on_mouse_moved(self, evt) -> None:
        pos = evt[0]
        vb = self._plot_item.getViewBox()
        if vb is None or not vb.sceneBoundingRect().contains(pos):
            self._update_cursor_readout()
            return
        pt = vb.mapSceneToView(pos)
        self._update_cursor_readout(pt.x(), pt.y())
