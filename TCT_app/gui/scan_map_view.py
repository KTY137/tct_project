"""
Shared 2-D scan-map widget — the single map renderer behind both the
standalone :class:`~gui.scan_map_window.ScanMapWindow` and the future live
``ScanViewerPanel`` (``docs/research/scan_viewer_design_review.md`` build
order step 2). Reconstructs a scattered ``(x_mm, y_mm, value)`` point cloud
into a dense 2-D image via the canonical :mod:`analysis.scan_grid` helper —
this widget never re-derives the grid/NaN logic inline (that duplication,
across ``scan_panel``/``scan_map_window``/``analysis_panel``, is exactly what
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
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:  # pragma: no cover - exercised only without pyqtgraph installed
    _HAS_PG = False

from analysis.scan_grid import ScanGridResult, grid_extent, points_to_grid
from gui.panel_kit import FigureCard
from gui.status_widgets import StatusChip
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: dict[tuple[float, float], dict[str, float]] = {}
        self._grid_result: ScanGridResult | None = None
        self._pos: tuple[float, float] = (0.0, 0.0)
        self._scale: tuple[float, float] = (1.0, 1.0)
        self._theme_mode = "dark"
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE_SM)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Quantity:"))
        self._combo_qty = QComboBox()
        self._combo_qty.addItems(QUANTITIES)
        self._combo_qty.currentTextChanged.connect(self._redraw)
        toolbar.addWidget(self._combo_qty)
        self._chip_points = StatusChip("No data", "neutral")
        toolbar.addWidget(self._chip_points)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        if _HAS_PG:
            self._plot_item = pg.PlotItem()
            self._plot_item.setLabel("bottom", "X", units="mm")
            self._plot_item.setLabel("left", "Y", units="mm")
            self._image_view = pg.ImageView(view=self._plot_item)
            self._image_view.setMinimumHeight(240)
            # Disable ROI rotation — only axis-aligned resize makes sense on
            # a stage-position map (same guard as scan_map_window/analysis_panel).
            _roi = self._image_view.roi
            _roi.rotatable = False
            for _h in list(_roi.handles):
                if _h["type"] == "r":
                    _roi.removeHandle(_h["item"])
            self._mouse_proxy = pg.SignalProxy(
                self._plot_item.scene().sigMouseMoved, rateLimit=30,
                slot=self._on_mouse_moved)

            self._figure_card = FigureCard("2D Scan Map", figure=self._image_view)
            self._figure_card.body.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
            root.addWidget(self._figure_card, 1)
        else:  # pragma: no cover - exercised only without pyqtgraph installed
            self._figure_card = None
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
        if hasattr(mapping_or_iterable, "items"):
            for key, entry in mapping_or_iterable.items():
                x, y = key
                self._points[(round(float(x), 6), round(float(y), 6))] = _extract_values(entry)
        else:
            for entry in mapping_or_iterable:
                point = getattr(entry, "point", None)
                if point is None:
                    continue
                x, y = float(point.x_mm), float(point.y_mm)
                self._points[(round(x, 6), round(y, 6))] = _extract_values(entry)
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
        self._redraw()

    def point_count(self) -> int:
        return len(self._points)

    def points(self) -> dict[tuple[float, float], dict[str, float]]:
        """A shallow copy of the accumulated ``(x_mm, y_mm) -> {quantity:
        value}`` points — for a caller (e.g. ``ScanMapWindow``'s CSV export)
        that needs the raw per-point data rather than the gridded image."""
        return dict(self._points)

    def image_view(self):
        """The underlying ``pyqtgraph.ImageView`` (``None`` if pyqtgraph is
        not installed) — for a caller (e.g. ``ScanMapWindow``'s PNG export)
        that needs the raw plot item rather than going through this widget's
        own API."""
        return self._image_view if _HAS_PG else None

    def grid_result(self) -> ScanGridResult | None:
        """The most recent :class:`~analysis.scan_grid.ScanGridResult` (for
        the currently selected quantity), or ``None`` before any data."""
        return self._grid_result

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
            self._chip_points.set_status("No data", "neutral")
            self._lbl_cursor.setText("x: -- mm   y: -- mm   value: --")
            return

        xs = [k[0] for k in self._points]
        ys = [k[1] for k in self._points]
        vals = [v.get(qty, float("nan")) for v in self._points.values()]
        result = points_to_grid(xs, ys, vals)
        self._grid_result = result
        self._pos, self._scale = grid_extent(result)

        grid = result.grid
        finite = grid[~np.isnan(grid)]
        if finite.size:
            # Autoscale the colorbar from nanmin/nanmax over sampled cells
            # only — unsampled/NaN cells never skew the colour range.
            vmin, vmax = float(np.nanmin(grid)), float(np.nanmax(grid))
            if vmin == vmax:
                vmax = vmin + 1e-9
            display = np.nan_to_num(grid, nan=vmin)
            self._image_view.setImage(
                display, autoRange=True, autoLevels=False, levels=(vmin, vmax),
                pos=self._pos, scale=self._scale,
            )
        else:
            display = np.nan_to_num(grid)
            self._image_view.setImage(
                display, autoRange=True, autoLevels=True,
                pos=self._pos, scale=self._scale,
            )

        n_total = int(grid.size)
        n_filled = n_total - result.n_missing
        status = "good" if result.n_missing == 0 else "busy"
        self._chip_points.set_status(
            f"{n_filled}/{n_total} pts", status,
            f"{result.n_missing} cells not yet sampled")
        self._update_cursor_readout()

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
