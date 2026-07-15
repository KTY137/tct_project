"""``ScanMapViewModel`` — the read-only-in-shape, fed-not-fetching data model
behind the shared 2-D scan-map widget (``gui/scan_map_view.py``).

U1.1 extraction (``docs/design/u1_staging.md`` §4.2): everything the scan-map
(a)-class tests pin as *data behavior* — not paint — moves here, out of
``ScanMapView``. This is a bare ``QObject`` (no widget import, no pyqtgraph
import), instantiable under a plain ``QCoreApplication``, and composes the
canonical grid math from :mod:`analysis.scan_grid` rather than re-deriving it
(``.claude/AGENT_PROTOCOL.md`` — physics/derivation code lives in
``analysis/``, GUI-adjacent code calls it). Owns:

- the points store — ``update_point``/``set_points`` normalization (incl.
  plain-``{quantity: value}`` dict entries), last-write-wins revisit,
  rounding-collision + duplicate/missing accounting;
- quantity selection (``QUANTITIES``/``QUANTITY_UNITS`` now live here;
  ``gui.scan_map_view`` imports and re-exports them for existing callers);
- grid derivation via :func:`analysis.scan_grid.points_to_grid` /
  :func:`analysis.scan_grid.grid_extent` — the math stays in ``analysis/``,
  this class only composes it;
- NaN semantics (a cell with no arrived point is NaN/"missing"; a point whose
  selected-quantity value is itself NaN is written through and counted
  separately — see ``analysis.scan_grid`` module docstring);
- cursor-readout derivation (``value_at(x, y)`` + ``cursor_text(x, y)``,
  including the empty-state and out-of-bounds dashes);
- CSV export as a data contract (``csv_rows()`` / ``write_csv(path)``),
  independent of any ``QFileDialog``.

Per ``docs/design/u1_staging.md`` §1.2, grid/image rebuilding is **lazy, not
timer-coalesced**: a mutating call (``update_point``/``set_points``/
``clear``/``set_quantity``) only marks the cached grid dirty; the next read
(``grid_result``/``image_extent``/``value_at``/``cursor_text``) rebuilds it if
needed. This VM owns no ``QTimer`` (a hard U1 constraint — async/coalescing
machinery is a *view* concern), yet the live-streaming perf property the
widget's own 15 Hz redraw timer relies on is preserved end to end: the widget
still batches many ``update_point`` calls behind its timer and only reads
``grid_result``/``image_extent`` once per repaint tick, so the O(N) rebuild in
here still runs at most once per coalesced repaint, never once per point.

**Never** (S2/§1.2 boundary, replicated by the standing-law tests below): a
reference to ``ScanController``/``StateMachine``/``ScanCoordinator``, a
``DangerGate``, or any start/stop/pause/resume/abort/arm/execute callable.
This class is *fed* by ``ScanMapView`` (which itself is fed by
``ScanViewerPanel``/``AnalysisPanel`` — plain ``ScanResult`` objects or plain
dicts already read off the wire); it reaches nothing.
"""
from __future__ import annotations

import csv

import numpy as np
from PySide6.QtCore import QObject, Signal

from analysis.scan_grid import ScanGridResult, grid_extent, points_to_grid

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


class ScanMapViewModel(QObject):
    """Points store + grid derivation + cursor/CSV data behind a 2-D scan
    map. Fed by plain method calls on the GUI thread; never fetches, never
    owns a timer or thread."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._points: dict[tuple[float, float], dict[str, float]] = {}
        self._n_duplicates = 0
        self._current_quantity: str = QUANTITIES[0]
        self._dirty = True
        self._grid_result: ScanGridResult | None = None
        self._pos: tuple[float, float] = (0.0, 0.0)
        self._scale: tuple[float, float] = (1.0, 1.0)

    # ------------------------------------------------------------------ #
    # Points store (fed)                                                  #
    # ------------------------------------------------------------------ #

    def update_point(self, result) -> None:
        """Accept one live ``controller.scan_controller.ScanResult`` —
        keyed by rounded ``(x_mm, y_mm)``, last-write-wins on revisit (the
        revisit is counted, never silently absorbed)."""
        x = round(float(result.point.x_mm), 6)
        y = round(float(result.point.y_mm), 6)
        if (x, y) in self._points:
            self._n_duplicates += 1
        self._points[(x, y)] = _extract_values(result)
        self._dirty = True
        self.changed.emit()

    def set_points(self, mapping_or_iterable) -> None:
        """Batch-load points, replacing any accumulated state.

        Accepts either a mapping of ``(x_mm, y_mm) -> ScanResult`` (or a
        plain ``{quantity: value}`` dict) — this store's own shape, for a
        fast bulk replace — or a flat iterable of ``ScanResult`` objects
        (each point's position read from ``result.point``)."""
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
        self._dirty = True
        self.changed.emit()

    def clear(self) -> None:
        """Remove all accumulated points and re-arm the duplicate counter."""
        self._points.clear()
        self._n_duplicates = 0
        self._dirty = True
        self.changed.emit()

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
        rather than the gridded image (e.g. this VM's own CSV export)."""
        return dict(self._points)

    # ------------------------------------------------------------------ #
    # Quantity selection                                                  #
    # ------------------------------------------------------------------ #

    def set_quantity(self, qty: str) -> None:
        """Select the displayed/exported quantity; a no-op for an unknown
        name or a re-selection of the already-current quantity (mirrors the
        widget combo box's own "only real changes redraw" behavior)."""
        if qty not in QUANTITIES or qty == self._current_quantity:
            return
        self._current_quantity = qty
        self._dirty = True
        self.changed.emit()

    def current_quantity(self) -> str:
        return self._current_quantity

    # ------------------------------------------------------------------ #
    # Grid derivation (composes analysis.scan_grid — never re-derives it)  #
    # ------------------------------------------------------------------ #

    def grid_result(self) -> ScanGridResult | None:
        """The most recent :class:`~analysis.scan_grid.ScanGridResult` for
        the currently selected quantity, or ``None`` before any data.
        Rebuilds first if a mutation happened since the last read."""
        self._rebuild_if_dirty()
        return self._grid_result

    def image_extent(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """``(pos, scale)`` for ``pyqtgraph.ImageView.setImage``/
        ``ImageItem`` — the render-only companion to :meth:`grid_result`,
        from the same :func:`analysis.scan_grid.grid_extent` call made
        during the last rebuild."""
        self._rebuild_if_dirty()
        return self._pos, self._scale

    def _rebuild_if_dirty(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        if not self._points:
            self._grid_result = None
            self._pos, self._scale = (0.0, 0.0), (1.0, 1.0)
            return
        xs = [k[0] for k in self._points]
        ys = [k[1] for k in self._points]
        vals = [v.get(self._current_quantity, float("nan")) for v in self._points.values()]
        result = points_to_grid(xs, ys, vals)
        self._grid_result = result
        self._pos, self._scale = grid_extent(result)

    # ------------------------------------------------------------------ #
    # Cursor readout                                                      #
    # ------------------------------------------------------------------ #

    def value_at(self, x_mm: float, y_mm: float) -> float | None:
        """The current-quantity value at the grid cell nearest ``(x_mm,
        y_mm)``, or ``None`` before any data / outside the sampled extent /
        for an unsampled (NaN) cell."""
        result = self.grid_result()
        if result is None:
            return None
        grid = result.grid
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

    def cursor_text(self, x_mm: float | None = None, y_mm: float | None = None) -> str:
        """Formatted cursor-readout text — the empty-state default before
        any motion, dashes out of bounds/unsampled, else the coordinate +
        current-quantity value."""
        if x_mm is None or y_mm is None:
            return "x: -- mm   y: -- mm   value: --"
        value = self.value_at(x_mm, y_mm)
        qty = self._current_quantity
        if value is None:
            return f"x: {x_mm:.4f} mm   y: {y_mm:.4f} mm   {qty}: --"
        return f"x: {x_mm:.4f} mm   y: {y_mm:.4f} mm   {qty}: {value:.6g}"

    # ------------------------------------------------------------------ #
    # CSV export (data contract — dialog-free)                            #
    # ------------------------------------------------------------------ #

    def csv_rows(self) -> list[list[str]]:
        """Header + one row per accumulated point for the currently
        selected quantity, sorted by ``(x_mm, y_mm)`` — header-only when
        empty."""
        qty = self._current_quantity
        rows: list[list[str]] = [["x_mm", "y_mm", qty]]
        for (x, y), values in sorted(self._points.items()):
            val = values.get(qty, float("nan"))
            rows.append([f"{x:.6f}", f"{y:.6f}", f"{val:.8g}"])
        return rows

    def write_csv(self, path) -> None:
        """Write :meth:`csv_rows` to *path* — the write half behind the
        widget's CSV export toolbutton, dialog-free for programmatic/tested
        use."""
        with open(path, "w", newline="") as fh:
            writer = csv.writer(fh)
            for row in self.csv_rows():
                writer.writerow(row)
