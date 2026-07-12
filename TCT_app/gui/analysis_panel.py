"""
Post-scan analysis panel.

Loads an existing HDF5 run file and provides:
  - 2-D map re-plotting with any stored quantity (via the shared
    :class:`~gui.scan_map_view.ScanMapView` — the single map renderer, so
    viridis / NaN-honesty / colorbar-unit rules apply here too)
  - CCE vs. bias voltage curve (from a bias scan HDF5 file), with the
    depletion-voltage estimate drawn as an annotated line (design system §4)
  - Export analysis results to CSV

Cockpit v5 layout (design system §7 "Analysis"): the empty state is a
recent-runs list (newest first, click to load, plus a browse row); loading
swaps to a compact run-header bar over segmented 2D-map / CCE modes.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton,
    QDoubleSpinBox, QFileDialog, QStackedWidget,
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
from gui.panel_kit import Card, FigureCard, SegmentedControl, panel_header
from gui.scan_map_view import QUANTITIES, ScanMapView
from gui.status_widgets import StatusChip, flash_button, set_button_icon
from gui.style import DARK, PLOT_OVERLAY, SPACE_MD, SPACE_SM

# How many recent .h5 files the empty-state list offers.
_RECENT_RUNS_MAX = 8


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
        self._run_path: str = ""
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
        lay.addWidget(self._map_view, 1)

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
            self._vdep_line = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen(PLOT_OVERLAY, width=1, style=Qt.PenStyle.DashLine),
                label="V_dep ≈ {value:.1f} V",
                labelOpts={"position": 0.9, "color": PLOT_OVERLAY},
            )
            self._vdep_line.setVisible(False)
            self._cce_plot.addItem(self._vdep_line)
            lay.addWidget(self._cce_figure, 1)

            # V_dep estimate + convention/Q_ref provenance (§4: "CCE plots
            # label the convention + Q_ref used").
            self._lbl_vdep = QLabel("V_dep estimate: —")
            self._lbl_vdep.setObjectName("cardSubtitle")
            lay.addWidget(self._lbl_vdep)
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
            self._lbl_file.setToolTip(path)
            self._chip_file.set_status("File loaded", "good")
            self._chip_dataset.set_status(
                f"{len(self._data)} arrays", "good" if self._data else "warn"
            )
            self._replot_map()
            self._stack.setCurrentIndex(1)
            return True
        except Exception as exc:
            self._chip_file.set_status("Load error", "crit", str(exc))
            return False

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
        """Seed the shared map view from the loaded arrays. All rendering
        truth (viridis, NaN transparency, colorbar unit, missing/duplicate
        counts) lives in :class:`~gui.scan_map_view.ScanMapView`."""
        if not _HAS_PG or not self._data:
            return
        x = self._data.get("x_mm")
        y = self._data.get("y_mm")
        if x is None or y is None:
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
            self._chip_dataset.set_status("No bias data", "warn")
            QMessageBox.warning(
                self, "No bias data",
                "No 'bias_V' or 'dut_charge_pC' arrays found.\n"
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

        # Estimate V_dep: voltage where CCE reaches 98% of plateau — drawn
        # as an annotated line on the curve (§4), plus the text footnote.
        try:
            from analysis.efield_analysis import estimate_depletion_voltage
            v_dep = estimate_depletion_voltage(np.array(voltages), np.array(charges))
            if v_dep is not None:
                self._lbl_vdep.setText(f"V_dep estimate: {v_dep:.1f} V")
                self._vdep_line.setValue(float(v_dep))
                self._vdep_line.setVisible(True)
                self._chip_dataset.set_status(f"Vdep {v_dep:.1f} V", "info")
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
