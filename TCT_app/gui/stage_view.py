"""Live visualisation of the motor stage / setup — 2D only, by design.

* ``StageView2D`` — top (X-Y) and side (X-Z) schematic with the soft-limit
  envelope, the current stage position, the origin, and an optional scan region.
  The side view IS the Z axis: Z is plotted there and mirrored as a live numeric
  chip in the header ("2D plus Z-Achse reicht voll" — Kaya, 2026-07-13).
* ``StageView`` — the panel-facing wrapper (header + legend + the 2D view).

Why there is no 3D view any more (removed 2026-07-13, Kaya: "die 3D view
brauchen wir auch nicht"): the old ``StageView3D`` hosted a
``pyqtgraph.opengl.GLViewWidget``, i.e. a ``QOpenGLWidget`` — a
**render-to-texture (RTT) child**.  Per the glass synthesis
(``docs/design/glass_council/SYNTHESIS.md`` §2, Thor's path-D), a single RTT
child anywhere under a QWidget top-level makes that whole window's per-pixel
DWM alpha impossible — no window material, for the entire cockpit, for as long
as the widget lives.  Deleting it makes the Motor panel material-capable when
detached and the CLASSIC main window RTT-free end to end.

GL is not banned, only *unhosted* GL is: content that genuinely needs OpenGL
must live in its **own native window** (``QWindow`` + ``createWindowContainer``,
or a separate top-level), where DWM composites it separately and it cannot
poison the parent's alpha.  That rule is enforced by
``tests/test_no_render_to_texture_children_in_gui.py``.

Both views expose ``set_position(x, y, z)``, ``set_limits(limits)`` and
``set_scan_region(...)`` so the owning panel can drive them from its position
poller.

Frame contract (docs/ARCHITECTURE.md "Motor frame contract"): every coordinate
handed to these views — position, limits envelope, scan region — must live in
ONE frame, the motor's USER frame (what ``get_position()`` returns; envelope =
``motor.limits_user_frame()``, never raw machine-frame ``motor.limits``).  The
owning panel re-pushes ``set_limits`` whenever the origin shifts (home / Zero
Here → ``MotorPanel.origin_changed``), so the envelope shifts with the marker
instead of the marker teleporting inside a stale machine-frame envelope.  The
plot origin ``(0, 0)`` marker is by definition the user-frame origin.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
)

from gui.status_widgets import StatusPill, StatusChip
from gui.app_settings import theme_mode
from gui.style import palette

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False


def _theme_from_settings() -> str:
    return theme_mode()


def _stage_colors(mode: str) -> dict[str, str]:
    p = palette(mode)
    return {
        "background": p["sunk"],
        "grid": p["hairline_strong"],
        "axis": p["muted"],
        "envelope": p["border_strong"],
        "position": p["accent"],
        "position_outline": p["material"],
        "origin": p["muted"],
        "scan": p["good"],
    }


def _rect_xy(x0: float, x1: float, y0: float, y1: float):
    """Closed-polyline coordinates for a rectangle outline."""
    return (np.array([x0, x1, x1, x0, x0]),
            np.array([y0, y0, y1, y1, y0]))


class StageView2D(QWidget):
    """Top (X-Y) + side (X-Z) schematic of the travel envelope and position."""

    def __init__(
        self,
        limits=None,
        parent: QWidget | None = None,
        theme_mode: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._x = self._y = self._z = 0.0
        self._limits = limits
        self._theme_mode = str(theme_mode) if theme_mode else _theme_from_settings()
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
        self.refresh_theme(self._theme_mode)

    def _make_plot(self, title: str, xlabel: str, ylabel: str) -> dict:
        colors = _stage_colors(self._theme_mode)
        w = pg.PlotWidget(title=title, background=colors["background"])
        w.setLabel("bottom", xlabel)
        w.setLabel("left", ylabel)
        w.showGrid(x=True, y=True, alpha=0.25)
        w.setAspectLocked(True)
        w.setMouseEnabled(x=False, y=False)
        envelope = w.plot(pen=pg.mkPen(colors["envelope"], width=2))
        scan = w.plot(pen=pg.mkPen(colors["scan"], width=1, style=Qt.PenStyle.DashLine))
        origin = pg.ScatterPlotItem(size=8, pen=pg.mkPen(colors["origin"]),
                                    brush=pg.mkBrush(colors["origin"]), symbol="+")
        w.addItem(origin)
        pos = pg.ScatterPlotItem(size=14, pen=pg.mkPen(colors["position_outline"], width=1),
                                 brush=pg.mkBrush(colors["position"]), symbol="o")
        w.addItem(pos)
        vline = pg.InfiniteLine(angle=90, movable=False,
                                pen=pg.mkPen(colors["position"], width=1, style=Qt.PenStyle.DotLine))
        hline = pg.InfiniteLine(angle=0, movable=False,
                                pen=pg.mkPen(colors["position"], width=1, style=Qt.PenStyle.DotLine))
        w.addItem(vline); w.addItem(hline)
        return {"w": w, "env": envelope, "scan": scan, "origin": origin,
                "pos": pos, "vline": vline, "hline": hline}

    def refresh_theme(self, mode: str | None = None) -> None:
        if mode:
            self._theme_mode = str(mode)
        if not _HAS_PG:
            return
        colors = _stage_colors(self._theme_mode)
        for plot in (self._top, self._side):
            widget = plot["w"]
            widget.setBackground(colors["background"])
            widget.showGrid(x=True, y=True, alpha=0.25)
            axis_pen = pg.mkPen(colors["axis"])
            grid_pen = pg.mkPen(colors["grid"])
            for axis_name in ("bottom", "left"):
                axis = widget.getPlotItem().getAxis(axis_name)
                axis.setPen(grid_pen)
                axis.setTickPen(grid_pen)
                axis.setTextPen(axis_pen)
            plot["env"].setPen(pg.mkPen(colors["envelope"], width=2))
            plot["scan"].setPen(pg.mkPen(colors["scan"], width=1, style=Qt.PenStyle.DashLine))
            plot["origin"].setPen(pg.mkPen(colors["origin"]))
            plot["origin"].setBrush(pg.mkBrush(colors["origin"]))
            plot["pos"].setPen(pg.mkPen(colors["position_outline"], width=1))
            plot["pos"].setBrush(pg.mkBrush(colors["position"]))
            plot["vline"].setPen(pg.mkPen(colors["position"], width=1, style=Qt.PenStyle.DotLine))
            plot["hline"].setPen(pg.mkPen(colors["position"], width=1, style=Qt.PenStyle.DotLine))

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


class StageView(QWidget):
    """Header + legend + the 2D schematic (the only stage view there is).

    Kept as a thin wrapper rather than folded into ``StageView2D`` because the
    owning panel (``gui/motor_panel.py``) drives it through this facade —
    ``set_limits`` / ``set_position`` / ``set_scan_region`` / ``refresh_theme``
    — and the header carries the live Z readout that pairs with the X-Z plot.
    """

    def __init__(
        self,
        limits=None,
        parent: QWidget | None = None,
        theme_mode: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_mode = str(theme_mode) if theme_mode else _theme_from_settings()
        self.setMinimumWidth(320)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # Header: title + the live Z readout.  The X-Z side plot already carries
        # Z geometrically; this chip states it as a number, so Z is legible at a
        # glance without reading a pixel off an axis (Kaya: "2d plus z achse
        # reicht voll").  Tokenized via the shared ``statusChip`` QSS hook — no
        # inline colour.
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Setup view</b>"))
        row.addStretch(1)
        self._z_chip = StatusChip("Z 0.000 mm", "neutral")
        self._z_chip.setToolTip("Live Z position (user frame) — also the "
                                "vertical axis of the side view below")
        row.addWidget(self._z_chip)
        lay.addLayout(row)

        legend = QHBoxLayout()
        legend.setSpacing(6)
        for chip in (
            StatusPill("Position", "good"),
            StatusPill("Limits", "neutral"),
            StatusPill("Scan area", "info"),
        ):
            legend.addWidget(chip)
        legend.addStretch(1)
        lay.addLayout(legend)

        self._v2d = StageView2D(limits, theme_mode=self._theme_mode)
        lay.addWidget(self._v2d, 1)

    # Fan-out to the 2D view -----------------------------------------------
    def set_limits(self, limits) -> None:
        self._v2d.set_limits(limits)

    def set_position(self, x: float, y: float, z: float) -> None:
        self._v2d.set_position(x, y, z)
        self._z_chip.setText(f"Z {z:.3f} mm")

    def set_scan_region(self, *a, **k) -> None:
        self._v2d.set_scan_region(*a, **k)

    def refresh_theme(self, mode: str | None = None) -> None:
        if mode:
            self._theme_mode = str(mode)
        self._v2d.refresh_theme(self._theme_mode)
