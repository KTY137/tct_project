"""Live visualisation of the motor stage / setup.

Two complementary views, switchable at runtime:

* ``StageView2D`` — top (X-Y) and side (X-Z) schematic with the soft-limit
  envelope, the current stage position, the origin, and an optional scan region.
* ``StageView3D`` — an OpenGL 3D box of the travel envelope with the DUT /
  current-position marker, a grid floor and a laser path.  Requires PyOpenGL;
  degrades to a hint label when it is missing.

Both expose ``set_position(x, y, z)``, ``set_limits(limits)`` and
``set_scan_region(...)`` so the owning panel can drive them from its position
poller.  ``StageView`` wraps both behind a 2D/3D toggle.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QButtonGroup, QSizePolicy, QFrame,
)

from gui.status_widgets import StatusPill

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

try:
    import pyqtgraph.opengl as gl
    _HAS_GL = True
except Exception:
    _HAS_GL = False


# Colours (RGB / RGBA)
_C_ENVELOPE = (90, 130, 200)
_C_POS      = (0, 200, 255)
_C_ORIGIN   = (150, 150, 150)
_C_SCAN     = (0, 230, 118)
_C_LASER    = (255, 70, 70)


def _rect_xy(x0: float, x1: float, y0: float, y1: float):
    """Closed-polyline coordinates for a rectangle outline."""
    return (np.array([x0, x1, x1, x0, x0]),
            np.array([y0, y0, y1, y1, y0]))


class StageView2D(QWidget):
    """Top (X-Y) + side (X-Z) schematic of the travel envelope and position."""

    def __init__(self, limits=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._x = self._y = self._z = 0.0
        self._limits = limits
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        if not _HAS_PG:
            lay.addWidget(QLabel("(install pyqtgraph for the stage view)"))
            return

        self._top = self._make_plot("Top view — X / Y", "X (mm)", "Y (mm)")
        self._side = self._make_plot("Side view — X / Z", "X (mm)", "Z (mm)")
        lay.addWidget(self._top["w"], 1)
        lay.addWidget(self._side["w"], 1)

        self.set_limits(limits)
        self.set_position(0.0, 0.0, 0.0)

    def _make_plot(self, title: str, xlabel: str, ylabel: str) -> dict:
        w = pg.PlotWidget(title=title)
        w.setLabel("bottom", xlabel)
        w.setLabel("left", ylabel)
        w.showGrid(x=True, y=True, alpha=0.25)
        w.setAspectLocked(True)
        w.setMouseEnabled(x=False, y=False)
        envelope = w.plot(pen=pg.mkPen(_C_ENVELOPE, width=2))
        scan = w.plot(pen=pg.mkPen(_C_SCAN, width=1, style=Qt.PenStyle.DashLine))
        origin = pg.ScatterPlotItem(size=8, pen=pg.mkPen(_C_ORIGIN),
                                    brush=pg.mkBrush(_C_ORIGIN), symbol="+")
        w.addItem(origin)
        pos = pg.ScatterPlotItem(size=14, pen=pg.mkPen("w", width=1),
                                 brush=pg.mkBrush(*_C_POS), symbol="o")
        w.addItem(pos)
        vline = pg.InfiniteLine(angle=90, movable=False,
                                pen=pg.mkPen(_C_POS, width=1, style=Qt.PenStyle.DotLine))
        hline = pg.InfiniteLine(angle=0, movable=False,
                                pen=pg.mkPen(_C_POS, width=1, style=Qt.PenStyle.DotLine))
        w.addItem(vline); w.addItem(hline)
        return {"w": w, "env": envelope, "scan": scan, "origin": origin,
                "pos": pos, "vline": vline, "hline": hline}

    def set_limits(self, limits) -> None:
        self._limits = limits
        if not _HAS_PG or limits is None:
            return
        ex, ey = _rect_xy(limits.x_min, limits.x_max, limits.y_min, limits.y_max)
        self._top["env"].setData(ex, ey)
        self._top["origin"].setData([0.0], [0.0])
        sx, sz = _rect_xy(limits.x_min, limits.x_max, limits.z_min, limits.z_max)
        self._side["env"].setData(sx, sz)
        self._side["origin"].setData([0.0], [0.0])

    def set_scan_region(self, x0, x1, y0, y1, z0=None, z1=None) -> None:
        if not _HAS_PG:
            return
        ex, ey = _rect_xy(x0, x1, y0, y1)
        self._top["scan"].setData(ex, ey)
        if z0 is not None and z1 is not None:
            sx, sz = _rect_xy(x0, x1, z0, z1)
            self._side["scan"].setData(sx, sz)

    def set_position(self, x: float, y: float, z: float) -> None:
        self._x, self._y, self._z = x, y, z
        if not _HAS_PG:
            return
        self._top["pos"].setData([x], [y])
        self._top["vline"].setPos(x); self._top["hline"].setPos(y)
        self._side["pos"].setData([x], [z])
        self._side["vline"].setPos(x); self._side["hline"].setPos(z)


class StageView3D(QWidget):
    """OpenGL 3D envelope box with a DUT / current-position marker."""

    def __init__(self, limits=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._limits = limits
        self._ok = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        if not _HAS_GL:
            lay.addWidget(QLabel("Install PyOpenGL for the 3D view:\n"
                                 "    pip install PyOpenGL"))
            return
        try:
            self._view = gl.GLViewWidget()
            self._view.setCameraPosition(distance=180, elevation=22, azimuth=-60)
            lay.addWidget(self._view)

            self._grid = gl.GLGridItem()
            self._grid.setSize(120, 120)
            self._grid.setSpacing(10, 10)
            self._view.addItem(self._grid)

            self._box = gl.GLLinePlotItem(width=2, antialias=True,
                                          color=(0.35, 0.51, 0.78, 1.0), mode="lines")
            self._view.addItem(self._box)

            self._laser = gl.GLLinePlotItem(width=2, antialias=True,
                                            color=(1.0, 0.27, 0.27, 0.9), mode="lines")
            self._view.addItem(self._laser)

            self._marker = gl.GLScatterPlotItem(size=14,
                                                color=(0.0, 0.78, 1.0, 1.0))
            self._marker.setGLOptions("translucent")
            self._view.addItem(self._marker)

            self._ok = True
            self.set_limits(limits)
            self.set_position(0.0, 0.0, 0.0)
        except Exception as exc:   # no GL context (e.g. headless) — show a hint
            while lay.count():
                lay.takeAt(0).widget().deleteLater()
            lay.addWidget(QLabel(f"3D view unavailable:\n{exc}"))

    @staticmethod
    def _box_edges(x0, x1, y0, y1, z0, z1) -> np.ndarray:
        corners = np.array([[x, y, z] for x in (x0, x1)
                            for y in (y0, y1) for z in (z0, z1)])
        # bit0=z, bit1=y, bit2=x → neighbours differ by one bit.
        segs = []
        for i in range(8):
            for bit in (1, 2, 4):
                j = i ^ bit
                if i < j:
                    segs.append(corners[i]); segs.append(corners[j])
        return np.array(segs, dtype=float)

    def set_limits(self, limits) -> None:
        self._limits = limits
        if not self._ok or limits is None:
            return
        self._box.setData(pos=self._box_edges(
            limits.x_min, limits.x_max, limits.y_min, limits.y_max,
            limits.z_min, limits.z_max))
        span = max(limits.x_max - limits.x_min, limits.y_max - limits.y_min, 20)
        self._grid.setSize(span * 1.5, span * 1.5)

    def set_position(self, x: float, y: float, z: float) -> None:
        if not self._ok:
            return
        self._marker.setData(pos=np.array([[x, y, z]]))
        # Laser path: vertical ray through the DUT position (visual aid).
        ztop = self._limits.z_max if self._limits is not None else z + 20
        zbot = self._limits.z_min if self._limits is not None else z - 20
        self._laser.setData(pos=np.array([[x, y, ztop], [x, y, zbot]]))


class StageView(QWidget):
    """2D schematic + 3D OpenGL view behind a segmented 2D/3D toggle."""

    def __init__(self, limits=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(320)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # Toggle row
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Setup view</b>"))
        row.addStretch(1)
        seg = QFrame()
        seg.setObjectName("segmented")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(2)
        self._btn2d = QPushButton("2D"); self._btn2d.setCheckable(True); self._btn2d.setChecked(True)
        self._btn3d = QPushButton("3D"); self._btn3d.setCheckable(True)
        for b in (self._btn2d, self._btn3d):
            b.setObjectName("segBtn")
            b.setMaximumWidth(48)
        grp = QButtonGroup(self); grp.setExclusive(True)
        grp.addButton(self._btn2d); grp.addButton(self._btn3d)
        seg_lay.addWidget(self._btn2d); seg_lay.addWidget(self._btn3d)
        row.addWidget(seg)
        lay.addLayout(row)

        legend = QHBoxLayout()
        legend.setSpacing(6)
        for chip in (
            StatusPill("Position", "good"),
            StatusPill("Limits", "neutral"),
            StatusPill("Scan area", "info"),
            StatusPill("Laser path", "armed"),
        ):
            legend.addWidget(chip)
        legend.addStretch(1)
        lay.addLayout(legend)

        self._stack = QStackedWidget()
        self._v2d = StageView2D(limits)
        self._v3d = StageView3D(limits)
        self._stack.addWidget(self._v2d)
        self._stack.addWidget(self._v3d)
        lay.addWidget(self._stack, 1)

        self._btn2d.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._btn3d.clicked.connect(lambda: self._stack.setCurrentIndex(1))

    # Fan-out to both views ------------------------------------------------
    def set_limits(self, limits) -> None:
        self._v2d.set_limits(limits)
        self._v3d.set_limits(limits)

    def set_position(self, x: float, y: float, z: float) -> None:
        self._v2d.set_position(x, y, z)
        self._v3d.set_position(x, y, z)

    def set_scan_region(self, *a, **k) -> None:
        self._v2d.set_scan_region(*a, **k)
